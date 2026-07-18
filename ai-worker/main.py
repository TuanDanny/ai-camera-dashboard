import os
import sys
import time
import json
import threading
import queue
import argparse
import yaml
import cv2
import numpy as np
import paho.mqtt.client as mqtt

from vehicle_classifier import VehicleClassifier
from direction_counter import DirectionCounter

# Fix Qt Wayland crash
os.environ["QT_QPA_PLATFORM"] = "xcb"

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

MQTT_HOST = config['server']['mqtt_host']
MQTT_PORT = config['server']['mqtt_port']
MQTT_USER = config['server']['mqtt_username']
MQTT_PASS = config['server']['mqtt_password']

MODEL_PATH = config['model']['path']
CONF_THRESH = config['model']['conf']
IMGSZ = config['model']['imgsz']
IOU_THRESH = config['model']['iou']
TARGET_CLASSES = config['model']['classes']
MAX_DET = config['model']['max_det']
TRACKER_CONFIG = config['model']['tracker_config']
CLASS_MIN_CONF = config['classifier']['class_min_conf']

MODEL_BACKEND = config['model'].get('backend', 'cpu')
HAILO_HEF_PATH = config['model'].get('hailo_hef_path', 'auto')

# Attempt to load NPU dependencies
HAS_HAILO = False
if MODEL_BACKEND == 'hailo':
    try:
        from hailo_yolo import HailoYolo
        from tracker_hailo.byte_tracker import BYTETracker
        from types import SimpleNamespace
        with open(TRACKER_CONFIG, "r") as f:
            _tcfg = yaml.safe_load(f)
        BYTETRACK_ARGS = SimpleNamespace(
            track_thresh=_tcfg.get('track_high_thresh', 0.25),
            track_buffer=_tcfg.get('track_buffer', 30),
            match_thresh=_tcfg.get('match_thresh', 0.8),
            mot20=not _tcfg.get('fuse_score', True),
        )
        HAS_HAILO = True
    except Exception as e:
        print(f"[WARN] Failed to load Hailo: {e}")

if not HAS_HAILO:
    import torch
    torch.set_num_threads(os.cpu_count() or 4)
    from ultralytics import YOLO

COCO_MAP = {3: "motorbike", 2: "car", 7: "truck", 5: "bus", 1: "bicycle"}
client = mqtt.Client(client_id="ai_worker_full")
client.username_pw_set(MQTT_USER, MQTT_PASS)

def on_connect(c, userdata, flags, rc):
    if rc == 0: print("[INFO] MQTT Connected")
client.on_connect = on_connect

def _iou(box_a, box_b):
    xa, ya = max(box_a[0], box_b[0]), max(box_a[1], box_b[1])
    xb, yb = min(box_a[2], box_b[2]), min(box_a[3], box_b[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    area_a = max(1e-5, (box_a[2] - box_a[0]) * (box_a[3] - box_a[1]))
    area_b = max(1e-5, (box_b[2] - box_b[0]) * (box_b[3] - box_b[1]))
    return inter / (area_a + area_b - inter + 1e-5)

def hailo_frame_source(url, station_id):
    hef = None if HAILO_HEF_PATH == 'auto' else HAILO_HEF_PATH
    detector = HailoYolo(classes=TARGET_CLASSES, conf=CONF_THRESH, hef_path=hef)
    tracker = BYTETracker(BYTETRACK_ARGS)
    
    from fast_rtsp import FastRTSPReader
    cap = FastRTSPReader(url)
    
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
                
            t0 = time.perf_counter()
            raw_dets = detector.detect(frame)
            dets = []
            
            if raw_dets:
                boxes_arr = np.array([[x1, y1, x2, y2, score] for x1, y1, x2, y2, score, _ in raw_dets])
                online_tracks = tracker.update(boxes_arr)
                for track in online_tracks:
                    x1, y1, x2, y2 = track.tlbr
                    best_cls, best_conf, best_iou = 0, track.score, 0.0
                    for dx1, dy1, dx2, dy2, dscore, dcls in raw_dets:
                        iou = _iou((x1, y1, x2, y2), (dx1, dy1, dx2, dy2))
                        if iou > best_iou:
                            best_iou, best_cls, best_conf = iou, dcls, dscore
                    dets.append((track.track_id, best_cls, best_conf, int(x1), int(y1), int(x2), int(y2)))
                    
            el = time.perf_counter() - t0
            yield frame, dets, frame.shape[0], int(el*1000), (1.0/el if el>0 else 0)
    finally:
        cap.release()
        detector.close()

def cpu_frame_source(url, station_id):
    model = YOLO(MODEL_PATH)
    device = 'cuda' if cv2.cuda.getCudaEnabledDeviceCount() > 0 else 'cpu'
    results = model.track(source=url, persist=True, stream=True, conf=CONF_THRESH, imgsz=IMGSZ, iou=IOU_THRESH, classes=TARGET_CLASSES, max_det=MAX_DET, tracker=TRACKER_CONFIG, device=device, verbose=False)
    for r in results:
        frame = r.orig_img.copy()
        el = sum(r.speed.values()) + 1e-6
        fps = 1000.0 / el
        dets = []
        if r.boxes and r.boxes.is_track:
            for box in r.boxes:
                dets.append((int(box.id[0].item()), int(box.cls[0].item()), float(box.conf[0].item()), *[int(x) for x in box.xyxy[0].tolist()]))
        yield frame, dets, r.orig_shape[0], int(r.speed.get('inference', 0)), fps

def process_stream(stream_info, view_queue=None):
    url = stream_info['url']
    station_id = stream_info['station_id']
    
    classifier = VehicleClassifier(CLASS_MIN_CONF, config['classifier']['lock_after'])
    direction_counter = DirectionCounter(config['direction']['default_y_ratio'], config['direction']['default_inbound_when'])
    
    if MODEL_BACKEND == 'hailo' and HAS_HAILO:
        print(f"[INFO] [{station_id}] Running YOLO on device: Hailo NPU")
        frame_source_fn = hailo_frame_source
    else:
        print(f"[INFO] [{station_id}] Running YOLO on device: CPU")
        frame_source_fn = cpu_frame_source
        
    last_pub = time.time()
    counts = {"interval_inbound": 0, "interval_outbound": 0, "interval_confidences": [], "tracked_ids": {c: set() for c in COCO_MAP.values()}}
    frame_index = 0
    
    try:
        for frame, dets, frame_height, inference_ms, fps in frame_source_fn(url, station_id):
            frame_index += 1
            
            for track_id, cls_id, confidence, x1, y1, x2, y2 in dets:
                locked_cls = classifier.get_locked_class(track_id, cls_id, confidence)
                classifier.mark_seen(track_id, frame_index)
                category = COCO_MAP.get(locked_cls, "unknown")
                counts["tracked_ids"][category].add(track_id)
                counts["interval_confidences"].append(confidence)
                
                cy = (y1 + y2) / 2
                crossing = direction_counter.update(track_id, cy, frame_height, frame_index)
                direction_counter.mark_seen(track_id, frame_index)
                if crossing == "inbound": counts["interval_inbound"] += 1
                elif crossing == "outbound": counts["interval_outbound"] += 1
                
            if view_queue is not None:
                if view_queue.full():
                    try: view_queue.get_nowait()
                    except: pass
                view_queue.put((frame.copy(), dets, fps, inference_ms))
                
            classifier.cleanup_old_tracks(frame_index)
            direction_counter.cleanup_old_tracks(frame_index)
            
            now = time.time()
            if now - last_pub >= config['publish']['interval_s']:
                total = counts["interval_inbound"] + counts["interval_outbound"]
                if total > 0:
                    avg_conf = sum(counts["interval_confidences"])/len(counts["interval_confidences"])
                    payload = {
                        "station_id": station_id,
                        "timestamp": int(now),
                        "total_count": total,
                        "inbound": counts["interval_inbound"],
                        "outbound": counts["interval_outbound"],
                        "by_class": {k: len(v) for k, v in counts["tracked_ids"].items()},
                        "avg_confidence": round(avg_conf, 2)
                    }
                    client.publish(config['publish']['topic_template'].format(station_id=station_id), json.dumps(payload))
                    print(f"[{station_id}] Published AI Telemetry (Total: {total})")
                counts["interval_inbound"] = counts["interval_outbound"] = 0
                counts["interval_confidences"].clear()
                for v in counts["tracked_ids"].values(): v.clear()
                last_pub = now
                
    except Exception as e:
        print(f"[ERROR] Stream {station_id} failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--view', action='store_true')
    args = parser.parse_args()
    
    view_queue = queue.Queue(maxsize=1) if args.view else None
    
    try: client.connect(MQTT_HOST, MQTT_PORT, 60)
    except: pass
    client.loop_start()
    
    threads = []
    for stream in config['streams']:
        t = threading.Thread(target=process_stream, args=(stream, view_queue), daemon=True)
        t.start()
        threads.append(t)
        
    if args.view:
        cv2.namedWindow("AI Worker", cv2.WINDOW_NORMAL)
        while True:
            try:
                frame, dets, fps, inference_ms = view_queue.get(timeout=0.05)
                for track_id, cls_id, confidence, x1, y1, x2, y2 in dets:
                    category = COCO_MAP.get(cls_id, "obj")
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f"ID {track_id} {category} {confidence:.2f}", (x1, max(y1-5, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
                cv2.putText(frame, f"Speed: {fps:.1f} FPS ({inference_ms}ms)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            except queue.Empty:
                pass
            
            if 'frame' in locals(): cv2.imshow("AI Worker", frame)
            if cv2.waitKey(1) & 0xFF in [27, ord('q'), ord('Q')]: break
        cv2.destroyAllWindows()
    else:
        for t in threads: t.join()
