"""
Debug viewer: hien thi truc tiep nhung gi ai-worker dang nhin thay va nhan
dien, dung THAT su config.yaml cua ai-worker (khong phai ban gia lap
rieng). Khong publish MQTT, chi ve box + nhan len man hinh.

Can chay bang mot python co opencv KHONG phai ban "headless" (ai-worker/
.venv dung opencv-python-headless, khong ho tro cv2.imshow). Dung venv
rieng ai-worker/.venv-view:

    cd ai-worker
    python3 -m venv .venv-view
    .venv-view/bin/pip install opencv-python pyyaml
    .venv-view/bin/python3 view_stream.py --backend relay

Che do mac dinh/nhe nhat la "relay" (chi nhan lai ket qua main.py da xu ly
san qua socket, xem pipeline/frame_broadcast.py) - chi can opencv-python +
pyyaml o tren la du, khong can ultralytics/torch gi ca. Che do "hailo" (tu
mo NPU rieng de debug khi main.py khong chay) can them wiring toi
hailo_platform cua he thong (file .pth) - xem WALKTHROUGH.md muc 6-7.

Nhan Q hoac ESC tren cua so de thoat.
"""
import argparse
import os
import sys
import time
import yaml
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

CONF_THRESH = config['model']['conf']
TARGET_CLASSES = config['model']['classes']

STREAM = config['streams'][0]
STREAM_URL = STREAM['url']
STATION_ID = STREAM['station_id']

# y_ratio: vi tri vach dem xe (0-1, ty le chieu cao khung hinh) - doc
# truc tiep tu config giong main.py, KHONG can truyen qua socket vi
# view_stream.py chi xem 1 station duy nhat (config['streams'][0]) nen
# doc thang tu config la du, don gian hon.
_direction_cfg = STREAM.get('direction_line', {})
Y_RATIO = _direction_cfg.get('y_ratio', config['direction']['default_y_ratio'])

COCO_MAP = {3: "motorbike", 2: "car", 7: "truck", 5: "bus", 1: "bicycle"}
# Mau box theo tung loai xe (BGR), khop voi mau cot tren dashboard Traffic
# Overview - xem cung dinh nghia trong pipeline/frame_broadcast.py.
CATEGORY_COLORS_BGR = {
    "motorbike": (0, 165, 255),
    "car": (242, 148, 87),
    "truck": (211, 0, 148),
    "bus": (0, 200, 0),
    "bicycle": (255, 255, 0),
    "unknown": (150, 150, 150),
}
COUNT_LINE_COLOR_BGR = (0, 0, 255)
WINDOW_NAME = f"AI Worker live view - {STATION_ID}"

_arg_parser = argparse.ArgumentParser()
_arg_parser.add_argument(
    "--backend", choices=["hailo", "relay"], default="relay",
    help="'relay' (mac dinh): KHONG tu chay YOLO, chi nhan lai ket qua NPU "
         "da xu ly san tu main.py qua socket (nhe nhat, main.py phai dang "
         "chay). 'hailo': tu mo NPU rieng de debug (chi dung duoc khi "
         "main.py KHONG dang chay - Hailo-8L chi co 1 device vat ly)."
)
_args = _arg_parser.parse_args()

MODEL_BACKEND = _args.backend
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


def main():
    print(f"[INFO] Backend: {MODEL_BACKEND}")
    print(f"[INFO] Dang ket noi stream: {STREAM_URL}")

    if MODEL_BACKEND == 'relay':
        from pipeline.frame_broadcast import socket_frame_source
        # socket_frame_source() la generator: goi ham o day KHONG chay gi
        # ca (ke ca connect()) - loi mat ket noi chi xay ra khi bat dau
        # iterate, nen duoc bat o try/except quanh vong lap for ben duoi,
        # khong phai o day.
        source = socket_frame_source()
    else:  # MODEL_BACKEND == 'hailo'
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
                    "'view_stream.py --backend relay' de xem cung luc voi main.py dang giu NPU."
                )
                return
            raise
        source = hailo_frame_source(
            hailo_instance, STREAM_URL, TARGET_CLASSES, conf=CONF_THRESH,
            buffer_size=1,
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

            line_y = int(frame.shape[0] * Y_RATIO)
            cv2.line(frame, (0, line_y), (frame.shape[1], line_y), COUNT_LINE_COLOR_BGR, 2)

            for cls_id, confidence, x1, y1, x2, y2 in boxes:
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

                category = COCO_MAP.get(cls_id, "unknown")
                color = CATEGORY_COLORS_BGR.get(category, CATEGORY_COLORS_BGR["unknown"])
                active_count += 1

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"{category} {confidence:.2f}"
                cv2.putText(
                    frame, label, (x1, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA
                )

            cv2.putText(
                frame, f"Frame {frame_index} | Detections: {active_count}",
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
