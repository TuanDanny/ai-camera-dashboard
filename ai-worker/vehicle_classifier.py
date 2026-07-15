from collections import defaultdict


class VehicleClassifier:
    """Bo phieu & khoa class xe cho tung track_id.

    Moi camera stream (moi thread trong ai-worker) phai tu tao rieng
    1 instance cua class nay - khong dung chung 1 instance cho nhieu
    stream, vi track_id cua ByteTrack bi danh so lai tu dau o moi stream.
    """

    def __init__(self, class_min_conf, lock_after=5):
        self.class_min_conf = class_min_conf
        self.lock_after = lock_after

        self.class_votes = defaultdict(lambda: defaultdict(float))
        self.class_observations = defaultdict(int)
        self.locked_classes = {}
        self.last_seen = {}

    def get_locked_class(self, track_id: int, class_id: int, confidence: float) -> int:
        if track_id in self.locked_classes:
            return self.locked_classes[track_id]

        min_conf = self.class_min_conf.get(class_id, 0.15)

        if confidence >= min_conf:
            self.class_votes[track_id][class_id] += confidence
            self.class_observations[track_id] += 1

        if self.class_observations[track_id] >= self.lock_after:
            self.locked_classes[track_id] = max(
                self.class_votes[track_id],
                key=self.class_votes[track_id].get
            )

        return self.locked_classes.get(track_id, class_id)

    def mark_seen(self, track_id: int, frame_index: int) -> None:
        self.last_seen[track_id] = frame_index

    def cleanup_old_tracks(self, frame_index: int, max_missing_frames: int = 90) -> None:
        expired_ids = [
            track_id
            for track_id, seen_frame in self.last_seen.items()
            if frame_index - seen_frame > max_missing_frames
        ]

        for track_id in expired_ids:
            self.last_seen.pop(track_id, None)
            self.class_votes.pop(track_id, None)
            self.class_observations.pop(track_id, None)
            self.locked_classes.pop(track_id, None)
