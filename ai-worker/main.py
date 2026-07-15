import os
import sys
import time
import json
import threading
import yaml
import cv2
import paho.mqtt.client as mqtt

from vehicle_classifier import VehicleClassifier
from direction_counter import DirectionCounter

try:
    import torch
    # Without this, torch's CPU backend does not use all available cores by
    # default - measured ~2.6x slower on a 4-core Pi (2.6 fps vs 6.8 fps at
    # the same imgsz/tracker settings) when this was left unset.
    torch.set_num_threads(os.cpu_count() or 4)
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False
    print("[WARN] 'ultralytics' package chua duoc cai dat.")

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

MQTT_HOST = config['server']['mqtt_host']
MQTT_PORT = config['server']['mqtt_port']
MQTT_USER = config['server']['mqtt_username']
MQTT_PASS = config['server']['mqtt_password']
PUBLISH_INTERVAL = config['publish']['interval_s']
# Vehicle counting keeps its own longer window (PUBLISH_INTERVAL) so a slow
# or stopped vehicle isn't recounted every few seconds - this separate,
# faster pulse is only for fps/inference_ms, which have no such window
# dependency and are safe to report as often as we like.
STATUS_INTERVAL = config['publish'].get('status_interval_s', 3)
STATUS_TOPIC_TEMPLATE = config['publish'].get('status_topic_template', 'traffic/station/{station_id}/ai_status')
MODEL_PATH = config['model']['path']
CONF_THRESH = config['model']['conf']
IMGSZ = config['model']['imgsz']
IOU_THRESH = config['model']['iou']
MAX_DET = config['model']['max_det']
TARGET_CLASSES = config['model']['classes']
TRACKER_CONFIG = os.path.join(os.path.dirname(__file__), config['model']['tracker_config'])

LOCK_AFTER = config['classifier']['lock_after']
CLASS_MIN_CONF = config['classifier']['class_min_conf']

DEFAULT_Y_RATIO = config['direction']['default_y_ratio']
DEFAULT_INBOUND_WHEN = config['direction']['default_inbound_when']

# Mapping COCO class indices to SHTP vehicle categories
# 0: person, 1: bicycle, 2: car, 3: motorcycle (motorbike), 5: bus, 7: truck
COCO_MAP = {
    3: "motorbike",
    2: "car",
    7: "truck",
    5: "bus",
    1: "bicycle"
}

# MQTT Client Setup
client = mqtt.Client(client_id="ai_worker_gpu")
client.username_pw_set(MQTT_USER, MQTT_PASS)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[INFO] AI Worker connected to MQTT Broker successfully.")
    else:
        print(f"[ERROR] Connection failed with code {rc}")

client.on_connect = on_connect

# Connect to MQTT
try:
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"[ERROR] Could not connect to MQTT Broker: {e}")
    sys.exit(1)

# AI Processing per stream
def process_stream(stream_info):
    station_id = stream_info['station_id']
    url = stream_info['url']
    location = stream_info['location_name']
    topic = config['publish']['topic_template'].format(station_id=station_id)
    status_topic = STATUS_TOPIC_TEMPLATE.format(station_id=station_id)

    print(f"[INFO] Starting AI Worker Thread for {station_id} ({location}) -> Stream: {url}")

    # Initialize trackers
    # We maintain a set of tracked vehicle IDs seen in the current 10s interval
    tracked_ids = {cat: set() for cat in COCO_MAP.values()}
    tracked_ids["unknown"] = set()

    # One classifier per stream/thread - state is never shared across stations
    classifier = VehicleClassifier(CLASS_MIN_CONF, LOCK_AFTER)

    direction_cfg = stream_info.get('direction_line', {})
    y_ratio = direction_cfg.get('y_ratio', DEFAULT_Y_RATIO)
    inbound_when = direction_cfg.get('inbound_when', DEFAULT_INBOUND_WHEN)
    direction_counter = DirectionCounter(y_ratio, inbound_when)

    frame_index = 0
    interval_confidences = []
    detections_raw_count = 0
    interval_inbound = 0
    interval_outbound = 0

    interval_start = time.time()
    status_interval_start = time.time()
    seq = 0

    STREAM_RETRY_LIMIT = 5
    STREAM_RETRY_BACKOFF_S = 5

    if not HAS_YOLO:
        raise RuntimeError("'ultralytics' khong duoc cai dat - AI Worker can no de chay voi du lieu that.")

    attempt = 0
    while True:
        attempt += 1
        try:
            # Load YOLO model (automatically downloads if not present)
            model = YOLO(MODEL_PATH)

            # Select device: GPU (cuda) if available, otherwise CPU
            device = 'cuda' if cv2.cuda.getCudaEnabledDeviceCount() > 0 else 'cpu'
            print(f"[INFO] [{station_id}] Running YOLO on device: {device} (attempt {attempt})")

            # Run tracker
            results = model.track(
                source=url,
                persist=True,
                stream=True,
                conf=CONF_THRESH,
                imgsz=IMGSZ,
                iou=IOU_THRESH,
                classes=TARGET_CLASSES,
                max_det=MAX_DET,
                tracker=TRACKER_CONFIG,
                device=device,
                verbose=False
            )

            for r in results:
                frame_index += 1

                # Calculate processing stats
                inference_ms = int(r.speed.get('inference', 0.0))
                fps = 1000.0 / (sum(r.speed.values()) + 1e-6)

                boxes = r.boxes
                if boxes is not None and boxes.is_track:
                    frame_height = r.orig_shape[0]
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        track_id = int(box.id[0].item())
                        confidence = float(box.conf[0].item())

                        locked_cls = classifier.get_locked_class(track_id, cls_id, confidence)
                        classifier.mark_seen(track_id, frame_index)

                        category = COCO_MAP.get(locked_cls, "unknown")
                        tracked_ids[category].add(track_id)

                        interval_confidences.append(confidence)
                        detections_raw_count += 1

                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        centroid_y = (y1 + y2) / 2
                        crossing = direction_counter.update(track_id, centroid_y, frame_height, frame_index)
                        direction_counter.mark_seen(track_id, frame_index)

                        if crossing == "inbound":
                            interval_inbound += 1
                        elif crossing == "outbound":
                            interval_outbound += 1

                classifier.cleanup_old_tracks(frame_index)
                direction_counter.cleanup_old_tracks(frame_index)

                now = time.time()

                # Fast, independent pulse for live fps/inference_ms - does
                # not touch tracked_ids/interval_* (those stay on
                # PUBLISH_INTERVAL so vehicle counting is unaffected).
                if now - status_interval_start >= STATUS_INTERVAL:
                    status_payload = {
                        "station_id": station_id,
                        "timestamp": int(now),
                        "fps": round(fps, 1),
                        "inference_ms": inference_ms
                    }
                    client.publish(status_topic, json.dumps(status_payload), qos=0)
                    status_interval_start = now

                # Check if interval is up to publish stats
                if now - interval_start >= PUBLISH_INTERVAL:
                    # Compile data
                    motorbike_cnt = len(tracked_ids["motorbike"])
                    car_cnt = len(tracked_ids["car"])
                    truck_cnt = len(tracked_ids["truck"])
                    bus_cnt = len(tracked_ids["bus"])
                    bicycle_cnt = len(tracked_ids["bicycle"])
                    unknown_cnt = len(tracked_ids["unknown"])
                    total_cnt = motorbike_cnt + car_cnt + truck_cnt + bus_cnt + bicycle_cnt + unknown_cnt

                    avg_confidence = round(sum(interval_confidences) / len(interval_confidences), 2) if interval_confidences else 0.0
                    min_confidence = round(min(interval_confidences), 2) if interval_confidences else 0.0

                    payload = {
                        "v": 1,
                        "station_id": station_id,
                        "timestamp": int(now),
                        "seq": seq,
                        "interval_seconds": PUBLISH_INTERVAL,
                        "data": {
                            "vehicles": {
                                "motorbike": motorbike_cnt,
                                "car": car_cnt,
                                "truck": truck_cnt,
                                "bus": bus_cnt,
                                "bicycle": bicycle_cnt,
                                "unknown": unknown_cnt
                            },
                            "total": total_cnt,
                            "direction": {
                                "inbound": interval_inbound,
                                "outbound": interval_outbound
                            },
                            "avg_confidence": avg_confidence,
                            "min_confidence": min_confidence,
                            "detections_raw": detections_raw_count,
                            "detections_filtered": total_cnt,
                            "lighting_condition": "day" if 6 <= time.localtime().tm_hour < 18 else "night"
                        },
                        "status": {
                            "fps": round(fps, 1),
                            "inference_ms": inference_ms,
                            "stream_status": "ok"
                        }
                    }

                    client.publish(topic, json.dumps(payload), qos=1)
                    print(f"[{station_id}] Published AI Telemetry (Total: {total_cnt})")

                    # Reset interval
                    tracked_ids = {cat: set() for cat in COCO_MAP.values()}
                    tracked_ids["unknown"] = set()
                    interval_confidences = []
                    detections_raw_count = 0
                    interval_inbound = 0
                    interval_outbound = 0
                    interval_start = now
                    seq += 1

            # The tracker generator ended without raising - treat this the
            # same as a dropped connection and retry instead of giving up.
            print(f"[WARN] [{station_id}] Stream ended unexpectedly (attempt {attempt}).")

        except Exception as e:
            print(f"[ERROR] [{station_id}] YOLO processing failed (attempt {attempt}): {e}")

        if attempt % STREAM_RETRY_LIMIT == 0:
            print(f"[ERROR] [{station_id}] {STREAM_RETRY_LIMIT} lien tiep khong ket noi duoc stream that - "
                  f"kiem tra lai camera/nguon RTSP. Tiep tuc retry, KHONG phat sinh du lieu gia.")

        time.sleep(STREAM_RETRY_BACKOFF_S)

def main():
    threads = []
    for stream in config['streams']:
        t = threading.Thread(target=process_stream, args=(stream,))
        t.daemon = True
        t.start()
        threads.append(t)

    print("[INFO] AI Worker is running. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping AI Worker...")
        client.loop_stop()
        client.disconnect()
        print("[INFO] AI Worker stopped.")

if __name__ == "__main__":
    main()
