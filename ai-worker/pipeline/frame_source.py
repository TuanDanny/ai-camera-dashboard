import time
import cv2

try:
    import torch
    # Without this, torch's CPU backend does not use all available cores by
    # default - measured ~2.6x slower on a 4-core Pi (2.6 fps vs 6.8 fps at
    # the same imgsz/tracker settings) when this was left unset.
    import os
    torch.set_num_threads(os.cpu_count() or 4)
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False

STREAM_RETRY_LIMIT = 5
STREAM_RETRY_BACKOFF_S = 5


def cpu_frame_source(station_id, url, model_path, conf_thresh, imgsz, iou_thresh,
                      target_classes, max_det, tracker_config,
                      on_stream_down=None, on_stream_recovered=None):
    """Sinh (frame, boxes, inference_ms, fps) cho tung frame da qua YOLO+tracker.

    frame: anh goc (r.orig_img) - KHONG copy, ben goi tu copy() neu can ve
    len anh ma khong muon dung chung buffer voi ultralytics.
    boxes: list cac tuple (track_id, cls_id, confidence, x1, y1, x2, y2).
    Tu quan ly viec load model va retry/backoff khi mat stream - khong bao
    gio tra ve False/None, chi (re)raise neu 'ultralytics' khong cai duoc.
    on_stream_down(attempt) / on_stream_recovered() la callback tuy chon de
    ben goi (main.py) tu quyet dinh lam gi (vd publish alert) - module nay
    khong biet gi ve MQTT.
    """
    if not HAS_YOLO:
        raise RuntimeError("'ultralytics' khong duoc cai dat - AI Worker can no de chay voi du lieu that.")

    attempt = 0
    stream_down_alerted = False
    while True:
        attempt += 1
        try:
            model = YOLO(model_path)

            device = 'cuda' if cv2.cuda.getCudaEnabledDeviceCount() > 0 else 'cpu'
            print(f"[INFO] [{station_id}] Running YOLO on device: {device} (attempt {attempt})")

            results = model.track(
                source=url,
                persist=True,
                stream=True,
                conf=conf_thresh,
                imgsz=imgsz,
                iou=iou_thresh,
                classes=target_classes,
                max_det=max_det,
                tracker=tracker_config,
                device=device,
                verbose=False
            )

            got_frame = False
            for r in results:
                if not got_frame:
                    got_frame = True
                    attempt = 0
                    if stream_down_alerted:
                        if on_stream_recovered:
                            on_stream_recovered()
                        stream_down_alerted = False

                inference_ms = int(r.speed.get('inference', 0.0))
                fps = 1000.0 / (sum(r.speed.values()) + 1e-6)

                boxes = []
                if r.boxes is not None and r.boxes.is_track:
                    for box in r.boxes:
                        cls_id = int(box.cls[0].item())
                        track_id = int(box.id[0].item())
                        confidence = float(box.conf[0].item())
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        boxes.append((track_id, cls_id, confidence, x1, y1, x2, y2))

                yield r.orig_img, boxes, inference_ms, fps

            # Generator tracker ket thuc ma khong raise - coi nhu mat ket noi,
            # retry thay vi bo cuoc.
            print(f"[WARN] [{station_id}] Stream ended unexpectedly (attempt {attempt}).")

        except Exception as e:
            print(f"[ERROR] [{station_id}] YOLO processing failed (attempt {attempt}): {e}")

        if attempt > 0 and attempt % STREAM_RETRY_LIMIT == 0:
            print(f"[ERROR] [{station_id}] {STREAM_RETRY_LIMIT} lien tiep khong ket noi duoc stream that - "
                  f"kiem tra lai camera/nguon RTSP. Tiep tuc retry, KHONG phat sinh du lieu gia.")
            if not stream_down_alerted:
                if on_stream_down:
                    on_stream_down(attempt)
                stream_down_alerted = True

        time.sleep(STREAM_RETRY_BACKOFF_S)
