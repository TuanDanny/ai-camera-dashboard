import gc
import os
import sys
import time
import json
import threading
import yaml
import paho.mqtt.client as mqtt

from vehicle_classifier import VehicleClassifier
from direction_counter import DirectionCounter
from pipeline.frame_source import cpu_frame_source
from pipeline.frame_broadcast import FrameBroadcaster

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
ALERT_TOPIC_TEMPLATE = config['publish'].get('alert_topic_template', 'traffic/station/{station_id}/alert')
MODEL_PATH = config['model']['path']
CONF_THRESH = config['model']['conf']
IMGSZ = config['model']['imgsz']
IOU_THRESH = config['model']['iou']
MAX_DET = config['model']['max_det']
TARGET_CLASSES = config['model']['classes']
TRACKER_CONFIG = os.path.join(os.path.dirname(__file__), config['model']['tracker_config'])

MODEL_BACKEND = config['model'].get('backend', 'cpu')
HAILO_HEF_PATH = config['model'].get('hailo_hef_path', 'auto')

# Import "tre" (chi khi thuc su can) - may chi chay backend cpu khong bat
# buoc phai cai duoc hailo_platform/picamera2 (thu vien dac thu phan cung,
# chi cai qua apt, khong co tren PyPI).
HAS_HAILO = False
if MODEL_BACKEND == 'hailo':
    try:
        from pipeline.hailo_source import create_hailo, DEFAULT_HEF_PATH as _HAILO_DEFAULT_HEF
        from pipeline.hailo_frame_source import hailo_frame_source
        HAS_HAILO = True
    except ImportError as e:
        print(f"[WARN] model.backend=hailo nhung khong import duoc thu vien Hailo: {e}")

    with open(TRACKER_CONFIG, 'r') as f:
        _tracker_yaml = yaml.safe_load(f)
    HAILO_TRACK_THRESH = _tracker_yaml.get('track_high_thresh', 0.25)
    HAILO_TRACK_BUFFER = _tracker_yaml.get('track_buffer', 30)
    HAILO_MATCH_THRESH = _tracker_yaml.get('match_thresh', 0.8)

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

def publish_alert(station_id, severity, code, message, details=None):
    alert_topic = ALERT_TOPIC_TEMPLATE.format(station_id=station_id)
    payload = {
        "station_id": station_id,
        "timestamp": int(time.time()),
        "severity": severity,
        "code": code,
        "message": message,
        "details": details or {}
    }
    client.publish(alert_topic, json.dumps(payload), qos=1)

# Connect to MQTT
try:
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"[ERROR] Could not connect to MQTT Broker: {e}")
    sys.exit(1)

# AI Processing per stream
def process_stream(stream_info, hailo_instance=None, broadcaster=None):
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

    def on_stream_down(attempt):
        publish_alert(station_id, "critical", "stream_offline",
                      f"Stream {station_id} mat ket noi sau {attempt} lan thu lai lien tiep.",
                      {"attempts": attempt})

    def on_stream_recovered():
        publish_alert(station_id, "info", "stream_recovered",
                      f"Stream {station_id} da ket noi lai binh thuong.")

    def on_frame_dropped(dropped_count):
        # Rot khung o day nghia la buffer NPU (buffer_size=4) day - CPU
        # (VehicleClassifier/DirectionCounter/publish) khong theo kip NPU.
        # Chi log de theo doi thuc te (npu_plan.md muc 3.3), khong publish
        # alert MQTT vi 1-2 khung le te khong phai su co nghiem trong.
        print(f"[WARN] [{station_id}] Buffer NPU day, da rot {dropped_count} "
              f"khung tich luy - CPU co the dang cham hon NPU.")

    if MODEL_BACKEND == 'hailo':
        if not HAS_HAILO:
            raise RuntimeError(
                "model.backend=hailo nhung khong import duoc thu vien Hailo - "
                "kiem tra lai venv co duoc wiring file .pth toi "
                "/usr/lib/python3/dist-packages chua (xem README/WALKTHROUGH)."
            )
        source = hailo_frame_source(
            hailo_instance, url, TARGET_CLASSES, conf=CONF_THRESH,
            buffer_size=4,
            track_thresh=HAILO_TRACK_THRESH, track_buffer=HAILO_TRACK_BUFFER,
            match_thresh=HAILO_MATCH_THRESH,
            on_stream_down=on_stream_down, on_stream_recovered=on_stream_recovered,
            on_frame_dropped=on_frame_dropped
        )
    else:
        source = cpu_frame_source(
            station_id, url, MODEL_PATH, CONF_THRESH, IMGSZ, IOU_THRESH,
            TARGET_CLASSES, MAX_DET, TRACKER_CONFIG,
            on_stream_down=on_stream_down, on_stream_recovered=on_stream_recovered
        )

    for frame, boxes, inference_ms, fps in source:
        frame_index += 1
        frame_height = frame.shape[0]

        # Phat lai khung + ket qua da xu ly qua socket cho view_stream.py
        # (neu co client dang xem) - KHONG chay YOLO lan 2 nua. publish()
        # cuc nhe (chi ghi de bien), khong lam cham vong lap NPU o day.
        if broadcaster is not None:
            broadcaster.publish(station_id, frame, boxes, inference_ms, fps)

        for track_id, cls_id, confidence, x1, y1, x2, y2 in boxes:
            locked_cls = classifier.get_locked_class(track_id, cls_id, confidence)
            classifier.mark_seen(track_id, frame_index)

            category = COCO_MAP.get(locked_cls, "unknown")
            tracked_ids[category].add(track_id)

            interval_confidences.append(confidence)
            detections_raw_count += 1

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

def main():
    # QUAN TRONG: moi Hailo() PHAI khoi tao tu CUNG 1 thread duy nhat (o day
    # la main thread) TRUOC khi mo thread rieng cho tung stream - da kiem
    # chung bang thu nghiem thuc te rang 2 OS thread khac nhau tu khoi tao
    # rieng se gay loi native "Resource deadlock avoided" du co khoa
    # (xem npu_plan.md muc 2.2b, pipeline/hailo_source.py). Thread xu ly
    # tung stream sau do CHI duoc goi .run() tren instance da co san.
    hailo_instances = {}
    if MODEL_BACKEND == 'hailo' and HAS_HAILO:
        hef_path = _HAILO_DEFAULT_HEF if HAILO_HEF_PATH == 'auto' else HAILO_HEF_PATH
        for stream in config['streams']:
            hailo_instances[stream['station_id']] = create_hailo(hef_path)

    # Chi 1 FrameBroadcaster duy nhat cho ca main.py (khong phai 1 cai/
    # stream) - view_stream.py cung chi xem dung 1 camera
    # (config['streams'][0]), nen chi station DAU TIEN moi phat qua
    # socket, khop dung hanh vi hien tai. Neu sau nay can xem duoc nhieu
    # camera thi phai thiet ke lai (xem npu_plan.md phan con mo).
    broadcaster = FrameBroadcaster()

    threads = []
    for i, stream in enumerate(config['streams']):
        hailo_instance = hailo_instances.get(stream['station_id'])
        stream_broadcaster = broadcaster if i == 0 else None
        t = threading.Thread(target=process_stream, args=(stream, hailo_instance, stream_broadcaster))
        t.daemon = True
        t.start()
        threads.append(t)

    # Da dieu tra thuc te (xem npu_plan.md): FPS NPU (do tuc thoi tung
    # frame, khong lam muot) thinh thoang rot khong deu (vd 45 -> 12-13fps)
    # ngay ca khi CPU dang o max freq (loai governor) VA khung hinh khong
    # co detection nao (loai workload dong xe) - dau hieu kinh dien cua GC
    # (Garbage Collector) chu ky day (gen-2) dung ca interpreter vai chuc ms
    # khong bao truoc. Doi vai giay de moi thread stream khoi tao xong cac
    # object "tinh" (detector/tracker/classifier...) roi "dong bang" toan
    # bo vao 1 generation vinh vien khong bi GC quet lai (gc.freeze()) -
    # giam han chi phi moi lan GC full phai duyet qua toan bo object nay.
    # Nang nguong GC (mac dinh 700,10,10) de giam han tan suat thu gom -
    # KHONG tat han (gc.disable()) vi tien trinh chay lien tuc nhieu ngay,
    # van can GC don dep reference cycle (vd closure trong producer thread)
    # de tranh ri bo nho dai han.
    time.sleep(2)
    gc.collect()
    gc.freeze()
    gc.set_threshold(50_000, 50, 50)
    print("[INFO] Da tune GC (freeze + nang nguong) de giam FPS rot do GC pause.")

    print("[INFO] AI Worker is running. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping AI Worker...")
        broadcaster.close()
        client.loop_stop()
        client.disconnect()
        print("[INFO] AI Worker stopped.")

if __name__ == "__main__":
    main()
