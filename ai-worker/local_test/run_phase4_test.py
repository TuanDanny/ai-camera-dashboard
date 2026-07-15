import os
import sys
import yaml

AI_WORKER_DIR = "/home/shtp/ai-camera-dashboard/ai-worker"
sys.path.insert(0, AI_WORKER_DIR)
from vehicle_classifier import VehicleClassifier  # noqa: E402
from direction_counter import DirectionCounter  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
VIDEO = os.path.join(BASE, "traffic-test-30s.mkv")
MODEL_PATH = os.path.join(BASE, "yolov8n_ncnn_model")

with open(os.path.join(AI_WORKER_DIR, "config.yaml")) as f:
    config = yaml.safe_load(f)

IMGSZ = config["model"]["imgsz"]
CONF_THRESH = config["model"]["conf"]
IOU_THRESH = config["model"]["iou"]
MAX_DET = config["model"]["max_det"]
TARGET_CLASSES = config["model"]["classes"]
TRACKER_CONFIG = os.path.join(AI_WORKER_DIR, config["model"]["tracker_config"])
LOCK_AFTER = config["classifier"]["lock_after"]
CLASS_MIN_CONF = config["classifier"]["class_min_conf"]
DEFAULT_Y_RATIO = config["direction"]["default_y_ratio"]
DEFAULT_INBOUND_WHEN = config["direction"]["default_inbound_when"]

COCO_MAP = {3: "motorbike", 2: "car", 7: "truck", 5: "bus", 1: "bicycle"}
LOG_EVERY = 60


def test_a_isolation():
    print("=" * 70)
    print("TEST A - 2 tram doc lap, cung track_id=1, khong duoc lan state")
    print("=" * 70)

    clf_a = VehicleClassifier(CLASS_MIN_CONF, LOCK_AFTER)
    clf_b = VehicleClassifier(CLASS_MIN_CONF, LOCK_AFTER)

    print(f"id(clf_a) = {id(clf_a)}  |  id(clf_b) = {id(clf_b)}  (phai la 2 object khac nhau)")

    # Tram A: track_id=1 lien tuc la xe may (class 3)
    for conf in [0.30, 0.35, 0.40, 0.45, 0.50]:
        clf_a.get_locked_class(track_id=1, class_id=3, confidence=conf)

    # Tram B: cung track_id=1 nhung lien tuc la o to (class 2)
    for conf in [0.30, 0.35, 0.40, 0.45, 0.50]:
        clf_b.get_locked_class(track_id=1, class_id=2, confidence=conf)

    print(f"Tram A (ky vong khoa vao class 3 - motorbike): locked_classes = {clf_a.locked_classes}")
    print(f"Tram B (ky vong khoa vao class 2 - car):       locked_classes = {clf_b.locked_classes}")

    ok = clf_a.locked_classes.get(1) == 3 and clf_b.locked_classes.get(1) == 2
    print(f"\n=> KET QUA TEST A: {'PASS - hoan toan doc lap' if ok else 'FAIL - bi lan state!'}")
    print()


def test_b_real_run():
    print("=" * 70)
    print("TEST B - chay that voi model YOLO + video, dung dung tham so Phase 3")
    print("=" * 70)

    from ultralytics import YOLO

    model = YOLO(MODEL_PATH)
    classifier = VehicleClassifier(CLASS_MIN_CONF, LOCK_AFTER)

    tracked_ids = {cat: set() for cat in COCO_MAP.values()}
    tracked_ids["unknown"] = set()
    interval_confidences = []
    detections_raw_count = 0
    frame_index = 0

    results = model.track(
        source=VIDEO,
        persist=True,
        stream=True,
        conf=CONF_THRESH,
        imgsz=IMGSZ,
        iou=IOU_THRESH,
        classes=TARGET_CLASSES,
        max_det=MAX_DET,
        tracker=TRACKER_CONFIG,
        device="cpu",
        verbose=False,
    )

    for r in results:
        frame_index += 1
        boxes = r.boxes
        if boxes is not None and boxes.is_track:
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

                if frame_index % LOG_EVERY == 0:
                    print(
                        f"frame={frame_index:>4} track_id={track_id:<3} "
                        f"raw_cls={cls_id}({COCO_MAP.get(cls_id, '?'):<10}) "
                        f"locked_cls={locked_cls}({category:<10}) conf={confidence:.2f}"
                    )

        classifier.cleanup_old_tracks(frame_index)

    avg_conf = round(sum(interval_confidences) / len(interval_confidences), 2) if interval_confidences else 0.0
    min_conf = round(min(interval_confidences), 2) if interval_confidences else 0.0

    print(f"\n=== KET QUA SAU {frame_index} FRAME ===")
    print(f"tracked_ids theo loai: { {k: len(v) for k, v in tracked_ids.items()} }")
    print(f"avg_confidence = {avg_conf}   min_confidence = {min_conf}")
    print(f"detections_raw = {detections_raw_count}  (thay vi total*2 gia truoc day)")
    print(f"classifier.locked_classes = {classifier.locked_classes}")


def test_c_direction():
    print("=" * 70)
    print("TEST C - dem inbound/outbound that qua duong ao, tren cung video")
    print("=" * 70)

    from ultralytics import YOLO

    model = YOLO(MODEL_PATH)
    direction_counter = DirectionCounter(DEFAULT_Y_RATIO, DEFAULT_INBOUND_WHEN)

    frame_index = 0
    inbound_total = 0
    outbound_total = 0

    results = model.track(
        source=VIDEO,
        persist=True,
        stream=True,
        conf=CONF_THRESH,
        imgsz=IMGSZ,
        iou=IOU_THRESH,
        classes=TARGET_CLASSES,
        max_det=MAX_DET,
        tracker=TRACKER_CONFIG,
        device="cpu",
        verbose=False,
    )

    for r in results:
        frame_index += 1
        boxes = r.boxes
        if boxes is not None and boxes.is_track:
            frame_height = r.orig_shape[0]
            for box in boxes:
                track_id = int(box.id[0].item())
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                centroid_y = (y1 + y2) / 2

                crossing = direction_counter.update(track_id, centroid_y, frame_height, frame_index)
                direction_counter.mark_seen(track_id, frame_index)

                if crossing is not None:
                    print(f"frame={frame_index:>4} track_id={track_id:<4} CROSSED -> {crossing}")
                    if crossing == "inbound":
                        inbound_total += 1
                    else:
                        outbound_total += 1

        direction_counter.cleanup_old_tracks(frame_index)

    print(f"\n=== KET QUA SAU {frame_index} FRAME ===")
    print(f"inbound_total = {inbound_total}   outbound_total = {outbound_total}")
    print(f"tong so xe da dem huong = {inbound_total + outbound_total}")


if __name__ == "__main__":
    test_a_isolation()
    test_b_real_run()
    test_c_direction()
