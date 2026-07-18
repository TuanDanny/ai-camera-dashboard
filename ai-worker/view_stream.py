"""
Optimized Multi-Threaded Debug Viewer for AI Worker.
Tach luong AI (Producer - 45 FPS NPU) va luong Hien thi (Consumer - GUI Display)
de cv2.imshow KHONG giam FPS cua chip Hailo NPU.
"""
import argparse
import os
import sys
import time
import threading
import queue
from types import SimpleNamespace
import numpy as np
import yaml
import cv2
from fast_rtsp import FastRTSPReader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vehicle_classifier import VehicleClassifier

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

MODEL_PATH = config['model']['path']
CONF_THRESH = config['model']['conf']
IMGSZ = config['model']['imgsz']
IOU_THRESH = config['model']['iou']
MAX_DET = config['model']['max_det']
TARGET_CLASSES = config['model']['classes']
TRACKER_CONFIG = os.path.join(os.path.dirname(__file__), config['model']['tracker_config'])

_arg_parser = argparse.ArgumentParser()
_arg_parser.add_argument("--backend", choices=["cpu", "hailo"], default=None,
                          help="Ep backend rieng cho view_stream.py")
_args = _arg_parser.parse_args()

MODEL_BACKEND = _args.backend if _args.backend else config['model'].get('backend', 'cpu')
HAILO_HEF_PATH = config['model'].get('hailo_hef_path', 'auto')

with open(TRACKER_CONFIG, 'r') as f:
    _tracker_yaml = yaml.safe_load(f)
BYTETRACK_ARGS = SimpleNamespace(
    track_thresh=_tracker_yaml.get('track_high_thresh', 0.25),
    track_buffer=_tracker_yaml.get('track_buffer', 30),
    match_thresh=_tracker_yaml.get('match_thresh', 0.8),
    mot20=not _tracker_yaml.get('fuse_score', True),
)

if MODEL_BACKEND != 'hailo':
    import torch
    torch.set_num_threads(os.cpu_count() or 4)
    from ultralytics import YOLO
else:
    from hailo_yolo import HailoYolo
    from tracker_hailo.byte_tracker import BYTETracker

def _iou(box_a, box_b):
    xa, ya = max(box_a[0], box_b[0]), max(box_a[1], box_b[1])
    xb, yb = min(box_a[2], box_b[2]), min(box_a[3], box_b[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    area_a = max(1e-5, (box_a[2] - box_a[0]) * (box_a[3] - box_a[1]))
    area_b = max(1e-5, (box_b[2] - box_b[0]) * (box_b[3] - box_b[1]))
    return inter / (area_a + area_b - inter + 1e-5)

LOCK_AFTER = config['classifier']['lock_after']
CLASS_MIN_CONF = config['classifier']['class_min_conf']

STREAM = config['streams'][0]
STREAM_URL = STREAM['url']
STATION_ID = STREAM['station_id']

COCO_MAP = {3: "motorbike", 2: "car", 7: "truck", 5: "bus", 1: "bicycle"}
WINDOW_NAME = f"AI Worker live view (Multi-Threaded) - {STATION_ID}"


class AsyncAIProducer(threading.Thread):
    """
    Luong AI Worker Doc cap & NPU Inference chay doc lap ben duoi.
    Luu ket qua vao Queue (maxsize=1, drop-oldest) de GUI Thread khong bao gio gay nghan.
    """
    def __init__(self, backend, stream_url):
        super().__init__(daemon=True)
        self.backend = backend
        self.stream_url = stream_url
        self.result_queue = queue.Queue(maxsize=1)
        self.running = True
        self.ai_fps = 0.0
        self.error_message = None

    def run(self):
        try:
            if self.backend == 'hailo':
                hef_path = None if HAILO_HEF_PATH == 'auto' else HAILO_HEF_PATH
                kwargs = {"classes": TARGET_CLASSES, "conf": CONF_THRESH}
                if hef_path: kwargs["hef_path"] = hef_path
                detector = HailoYolo(**kwargs)
                tracker = BYTETracker(BYTETRACK_ARGS)
            else:
                model = YOLO(MODEL_PATH)

            cap = FastRTSPReader(self.stream_url)
            if not cap.isOpened():
                self.error_message = f"Khong mo duoc stream {self.stream_url}"
                return

            prev_t = time.perf_counter()
            while self.running:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.01)
                    continue

                t0 = time.perf_counter()
                dets = []

                if self.backend == 'hailo':
                    raw_dets = detector.detect(frame)
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
                else:
                    results = model.track(
                        source=frame, persist=True, conf=CONF_THRESH,
                        imgsz=IMGSZ, iou=IOU_THRESH, classes=TARGET_CLASSES,
                        max_det=MAX_DET, tracker=TRACKER_CONFIG, device='cpu', verbose=False
                    )
                    if results and len(results) > 0 and results[0].boxes is not None and results[0].boxes.is_track:
                        boxes = results[0].boxes
                        for box in boxes:
                            cls_id = int(box.cls[0].item())
                            track_id = int(box.id[0].item())
                            confidence = float(box.conf[0].item())
                            x1, y1, x2, y2 = box.xyxy[0].int().tolist()
                            dets.append((track_id, cls_id, confidence, x1, y1, x2, y2))

                el = time.perf_counter() - t0
                cur_fps = 1.0 / el if el > 0 else 0.0
                self.ai_fps = cur_fps if self.ai_fps == 0 else self.ai_fps * 0.85 + cur_fps * 0.15

                # Put to queue non-blocking (drop oldest if GUI consumer is slower)
                if self.result_queue.full():
                    try: self.result_queue.get_nowait()
                    except queue.Empty: pass
                self.result_queue.put((frame.copy(), dets, self.ai_fps))

            cap.release()
            if self.backend == 'hailo': detector.close()
        except Exception as e:
            self.error_message = str(e)


def main():
    print(f"[INFO] Backend: {MODEL_BACKEND}")
    classifier = VehicleClassifier(CLASS_MIN_CONF, LOCK_AFTER)

    print(f"[INFO] Khởi động Luồng AI Producer bất đồng bộ (Multi-Threaded)...")
    producer = AsyncAIProducer(MODEL_BACKEND, STREAM_URL)
    producer.start()

    
    # Auto-set display environment variables if running inside SSH or terminal without DISPLAY
    if "DISPLAY" not in os.environ:
        os.environ["DISPLAY"] = ":0"
    if "WAYLAND_DISPLAY" not in os.environ:
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
    if "XDG_RUNTIME_DIR" not in os.environ:
        os.environ["XDG_RUNTIME_DIR"] = "/run/user/1000"
    # Fallback platform plugin if xcb fails
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "wayland;xcb;offscreen"

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    frame_index = 0
    display_fps = 0.0
    prev_time = time.perf_counter()
    print("[INFO] Nhan Q hoac ESC tren cua so de thoat.")

    while producer.running:
        if producer.error_message:
            print(f"[ERROR] AI Producer gap loi: {producer.error_message}")
            break

        try:
            # Grab latest AI processed frame (timeout 0.5s)
            frame, dets, ai_fps = producer.result_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        now = time.perf_counter()
        elapsed = now - prev_time
        prev_time = now
        current_fps = 1.0 / elapsed if elapsed > 0 else 0.0
        display_fps = current_fps if display_fps == 0 else display_fps * 0.85 + current_fps * 0.15

        frame_index += 1
        active_count = 0

        for track_id, cls_id, confidence, x1, y1, x2, y2 in dets:
            locked_cls = classifier.get_locked_class(track_id, cls_id, confidence)
            classifier.mark_seen(track_id, frame_index)
            category = COCO_MAP.get(locked_cls, "unknown")
            active_count += 1

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"ID {track_id} {category} {confidence:.2f}"
            cv2.putText(frame, label, (x1, max(y1 - 8, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # Draw Header Telemetry Overlay right on the video
        header_text = f"AI NPU Speed: {ai_fps:.1f} FPS | Display GUI: {display_fps:.1f} FPS | Active Objects: {active_count}"
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 35), (0, 0, 0), -1)
        cv2.putText(frame, header_text, (15, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

        cv2.imshow(WINDOW_NAME, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in [ord('q'), ord('Q'), 27]:
            break

    producer.running = False
    producer.join(timeout=2)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
