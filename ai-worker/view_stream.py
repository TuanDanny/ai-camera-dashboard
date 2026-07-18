"""
Debug viewer: hien thi truc tiep nhung gi ai-worker dang nhin thay va nhan
dien, dung THAT su config.yaml + VehicleClassifier cua ai-worker (khong
phai ban gia lap rieng). Khong publish MQTT, chi ve box + nhan len man hinh.

Can chay bang mot python co opencv KHONG phai ban "headless" (ai-worker/
.venv dung opencv-python-headless, khong ho tro cv2.imshow). Dung venv
rieng ai-worker/.venv-view (co opencv-python ban day du + torch cai qua
pip, KHONG phai ban torch cua he thong - xem ghi chu ben duoi):

    cd ai-worker
    python3 -m venv .venv-view
    .venv-view/bin/pip install ultralytics opencv-python ncnn pyyaml
    .venv-view/bin/python3 view_stream.py

Luu y: yolo-cam/.venv cung co opencv GUI nhung duoc tao voi
--system-site-packages nen "torch" cua no thuc ra la ban apt cua he
thong (cham hon ro ret tren ARM64 - do luong that: ~2.1fps so voi
~10.4fps cua ban pip trong .venv-view, cung 1 model/tham so). Vi vay
KHONG dung venv cua yolo-cam cho script nay.

Nhan Q hoac ESC tren cua so de thoat.
"""
import argparse
import os
import sys
import time
import yaml
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vehicle_classifier import VehicleClassifier  # noqa: E402
from pipeline.frame_source import cpu_frame_source  # noqa: E402

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

_arg_parser = argparse.ArgumentParser()
_arg_parser.add_argument(
    "--backend", choices=["cpu", "hailo", "relay"], default=None,
    help="Ep backend rieng cho view_stream.py, bo qua model.backend trong "
         "config.yaml. 'relay': KHONG tu chay YOLO, chi nhan lai ket qua "
         "NPU da xu ly san tu main.py qua socket (nhe nhat, main.py phai "
         "dang chay). 'cpu'/'hailo': tu chay YOLO rieng nhu truoc."
)
_args = _arg_parser.parse_args()

MODEL_BACKEND = _args.backend if _args.backend else config['model'].get('backend', 'cpu')
HAILO_HEF_PATH = config['model'].get('hailo_hef_path', 'auto')

# Import "tre" - xem giai thich trong main.py
HAS_HAILO = False
if MODEL_BACKEND == 'hailo':
    try:
        from pipeline.hailo_source import create_hailo, DEFAULT_HEF_PATH as _HAILO_DEFAULT_HEF
        from pipeline.hailo_frame_source import hailo_frame_source
        HAS_HAILO = True
    except ImportError as e:
        print(f"[WARN] --backend hailo nhung khong import duoc thu vien Hailo: {e}")

    with open(TRACKER_CONFIG, 'r') as f:
        _tracker_yaml = yaml.safe_load(f)
    HAILO_TRACK_THRESH = _tracker_yaml.get('track_high_thresh', 0.25)
    HAILO_TRACK_BUFFER = _tracker_yaml.get('track_buffer', 30)
    HAILO_MATCH_THRESH = _tracker_yaml.get('match_thresh', 0.8)


def main():
    classifier = VehicleClassifier(CLASS_MIN_CONF, LOCK_AFTER)

    print(f"[INFO] Backend: {MODEL_BACKEND}")
    print(f"[INFO] Dang ket noi stream: {STREAM_URL}")

    if MODEL_BACKEND == 'relay':
        from pipeline.frame_broadcast import socket_frame_source
        try:
            source = socket_frame_source()
        except RuntimeError as e:
            print(f"[ERROR] {e}")
            return
    elif MODEL_BACKEND == 'hailo':
        if not HAS_HAILO:
            print("[ERROR] --backend hailo nhung khong import duoc thu vien Hailo - "
                  "kiem tra lai venv co duoc wiring file .pth chua.")
            return

        hef_path = _HAILO_DEFAULT_HEF if HAILO_HEF_PATH == 'auto' else HAILO_HEF_PATH
        try:
            hailo_instance = create_hailo(hef_path)
        except Exception as e:
            if "OUT_OF_PHYSICAL_DEVICES" in str(e) or "not enough free devices" in str(e):
                print(
                    "[ERROR] Khong mo duoc NPU Hailo - dang co tien trinh khac (thuong la "
                    "main.py) giu thiet bi roi. Hailo-8L chi co 1 device vat ly, khong the "
                    "dung song song 2 tien trinh OS rieng biet cung mo NPU. Dung main.py "
                    "truoc roi chay lai view_stream.py, hoac chay "
                    "'view_stream.py --backend cpu' de xem cung luc voi main.py dang giu NPU."
                )
                return
            raise
        source = hailo_frame_source(
            hailo_instance, STREAM_URL, TARGET_CLASSES, conf=CONF_THRESH,
            buffer_size=1,
            track_thresh=HAILO_TRACK_THRESH, track_buffer=HAILO_TRACK_BUFFER,
            match_thresh=HAILO_MATCH_THRESH,
        )
    else:
        print(f"[INFO] Dang tai model: {MODEL_PATH}")
        source = cpu_frame_source(
            STATION_ID, STREAM_URL, MODEL_PATH, CONF_THRESH, IMGSZ, IOU_THRESH,
            TARGET_CLASSES, MAX_DET, TRACKER_CONFIG
        )

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    frame_index = 0
    display_fps = 0.0
    prev_time = time.perf_counter()
    print("[INFO] Nhan Q hoac ESC tren cua so de thoat.")

    # QUAN TRONG (che do relay): socket_frame_source() chi tao generator,
    # CHUA ket noi gi ca cho toi khi bi iterate lan dau - nen loi mat ket
    # noi (main.py chua chay, hoac bi tat giua luc dang xem) xay ra TRONG
    # vong lap for ben duoi, khong phai o dong goi ham. Boc RuntimeError o
    # day de bao loi ro rang thay vi traceback tho.
    try:
        for orig_frame, boxes, inference_ms, fps in source:
            now = time.perf_counter()
            elapsed = now - prev_time
            prev_time = now
            current_fps = 1.0 / elapsed if elapsed > 0 else 0.0
            # Lam muot FPS qua thoi gian, giong cach yolo_cam_live.py da lam,
            # de khong nhay so lien tuc tung frame.
            display_fps = current_fps if display_fps == 0 else display_fps * 0.85 + current_fps * 0.15

            frame_index += 1
            frame = orig_frame.copy()
            active_count = 0

            for track_id, cls_id, confidence, x1, y1, x2, y2 in boxes:
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

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
    except RuntimeError as e:
        print(f"[ERROR] {e}")

    # Goi tuong minh source.close() truoc khi thoat - voi backend hailo/
    # relay, dam bao producer/client thread nen dung han truoc khi tra
    # quyen dieu khien (xem npu_plan.md muc Buoc 4 - bug da phat hien:
    # dong tai nguyen trong luc thread van chay se crash native).
    source.close()
    cv2.destroyAllWindows()
    print("[INFO] Da dong.")


if __name__ == "__main__":
    main()
