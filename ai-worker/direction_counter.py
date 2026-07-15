class DirectionCounter:
    """Phat hien huong di chuyen (inbound/outbound) qua 1 duong ao nam ngang.

    Moi camera stream (moi thread trong ai-worker) phai tu tao rieng 1
    instance cua class nay - cung ly do nhu VehicleClassifier: track_id
    bi danh so lai tu dau o moi stream, dung chung se lan state.
    """

    def __init__(self, y_ratio: float, inbound_when: str):
        if inbound_when not in ("increasing", "decreasing"):
            raise ValueError("inbound_when phai la 'increasing' hoac 'decreasing'")

        self.y_ratio = y_ratio
        self.inbound_when = inbound_when

        self.last_y = {}
        self.counted = set()
        self.last_seen = {}

    def update(self, track_id: int, centroid_y: float, frame_height: float, frame_index: int):
        line_y = frame_height * self.y_ratio
        prev_y = self.last_y.get(track_id)
        self.last_y[track_id] = centroid_y

        if prev_y is None or track_id in self.counted:
            return None

        prev_side = prev_y < line_y
        current_side = centroid_y < line_y
        if prev_side == current_side:
            return None

        movement = "increasing" if centroid_y > prev_y else "decreasing"
        direction = "inbound" if movement == self.inbound_when else "outbound"

        self.counted.add(track_id)
        return direction

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
            self.last_y.pop(track_id, None)
            self.counted.discard(track_id)
