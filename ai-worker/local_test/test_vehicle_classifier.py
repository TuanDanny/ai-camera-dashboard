import sys

AI_WORKER_DIR = "/home/shtp/ai-camera-dashboard/ai-worker"
sys.path.insert(0, AI_WORKER_DIR)

from vehicle_classifier import VehicleClassifier  # noqa: E402


def main():
    clf = VehicleClassifier(class_min_conf={2: 0.18, 7: 0.18}, lock_after=5)

    sequence = [(2, 0.30), (7, 0.25), (2, 0.40), (2, 0.35), (2, 0.50), (2, 0.20)]

    for frame_index, (class_id, confidence) in enumerate(sequence, start=1):
        result = clf.get_locked_class(track_id=1, class_id=class_id, confidence=confidence)
        clf.mark_seen(track_id=1, frame_index=frame_index)
        print(f"frame {frame_index}: class_id={class_id} conf={confidence:.2f} -> ket qua = {result}")

    print("\nlocked_classes:", clf.locked_classes)


if __name__ == "__main__":
    main()
