"""
Debug viewer: hien thi truc tiep nhung gi ai-worker dang nhin thay va nhan
dien, dung THAT su config.yaml + VehicleClassifier cua ai-worker (khong
phai ban gia lap rieng). Khong publish MQTT, chi ve box + nhan len man hinh.

Can chay bang mot python co opencv KHONG phai ban "headless" (ai-worker/
.venv dung opencv-python-headless, khong ho tro cv2.imshow). yolo-cam/.venv
da co san opencv co GUI (QT5) nen dung tam interpreter do de chay script nay:

    cd ai-worker
    /home/shtp/yolo-cam/.venv/bin/python3 view_stream.py

Nhan Q hoac ESC tren cua so de thoat.
"""
import os
import sys
import time
import yaml
import cv2
from ultralytics import YOLO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vehicle_classifier import VehicleClassifier  # noqa: E402

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

LOCK_AFTER = config['classifier']['lock_after']
CLASS_MIN_CONF = config['classifier']['class_min_conf']

STREAM = config['streams'][0]
STREAM_URL = STREAM['url']
STATION_ID = STREAM['station_id']

COCO_MAP = {3: "motorbike", 2: "car", 7: "truck", 5: "bus", 1: "bicycle"}
WINDOW_NAME = f"AI Worker live view - {STATION_ID}"


def main():
    print(f"[INFO] Dang tai model: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)
    classifier = VehicleClassifier(CLASS_MIN_CONF, LOCK_AFTER)

    print(f"[INFO] Dang ket noi stream: {STREAM_URL}")
    results = model.track(
        source=STREAM_URL,
        persist=True,
        stream=True,
        conf=CONF_THRESH,
        imgsz=IMGSZ,
        iou=IOU_THRESH,
        classes=TARGET_CLASSES,
        max_det=MAX_DET,
        tracker=TRACKER_CONFIG,
        device='cpu',
        verbose=False,
    )

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    frame_index = 0
    display_fps = 0.0
    prev_time = time.perf_counter()
    print("[INFO] Nhan Q hoac ESC tren cua so de thoat.")

    for r in results:
        now = time.perf_counter()
        elapsed = now - prev_time
        prev_time = now
        current_fps = 1.0 / elapsed if elapsed > 0 else 0.0
        # Lam muot FPS qua thoi gian, giong cach yolo_cam_live.py da lam,
        # de khong nhay so lien tuc tung frame.
        display_fps = current_fps if display_fps == 0 else display_fps * 0.85 + current_fps * 0.15

        frame_index += 1
        frame = r.orig_img.copy()
        active_count = 0

        boxes = r.boxes
        if boxes is not None and boxes.is_track:
            for box in boxes:
                cls_id = int(box.cls[0].item())
                track_id = int(box.id[0].item())
                confidence = float(box.conf[0].item())
                x1, y1, x2, y2 = box.xyxy[0].int().tolist()

                locked_cls = classifier.get_locked_class(track_id, cls_id, confidence)
                classifier.mark_seen(track_id, frame_index)
                category = COCO_MAP.get(locked_cls, "unknown")
                active_count += 1

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = f"ID {track_id} {category} {confidence:.2f}"
                cv2.putText(
                    frame, label, (x1, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA
                )

        classifier.cleanup_old_tracks(frame_index)

        cv2.putText(
            frame, f"Frame {frame_index} | Active tracks: {active_count}",
            (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA
        )
        cv2.putText(
            frame, f"FPS: {display_fps:.1f}",
            (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA
        )
        cv2.imshow(WINDOW_NAME, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            break

    cv2.destroyAllWindows()
    print("[INFO] Da dong.")


if __name__ == "__main__":
    main()
