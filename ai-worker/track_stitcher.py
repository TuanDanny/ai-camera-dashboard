class TrackStitcher:
    """Ghep 1 track_id MOI cua ByteTrack voi 1 canonical_id da biet truoc do,
    neu vi tri xuat hien dau tien cua no gan voi vi tri cuoi cung cua 1
    track vua "mat dau" gan day.

    Ly do can co class nay: ByteTrack tu giu 1 track "mat dau" song trong
    track_buffer frame (xem traffic_bytetrack.yaml) cho vao gan lai DUNG
    track_id cu neu no xuat hien lai kip thoi gian do. Nhung neu bi che
    khuat/mat dau LAU HON track_buffer, ByteTrack se cap 1 track_id MOI HOAN
    TOAN khi xe xuat hien lai - va viec dem theo track_id (tracked_ids set
    trong main.py) se tinh nham thanh 2 xe du thuc te chi la 1.

    Class nay khong thay the ByteTrack, chi xu ly phan "khoang giua": tu luc
    ByteTrack bo cuoc (sau track_buffer frame) toi luc chac chan la xe khac
    (qua max_gap_frames). min_gap_frames nen >= track_buffer de khong giay
    vao viec ByteTrack da tu lo tot roi, va max_gap_frames nen < gia tri
    max_missing_frames cua VehicleClassifier/DirectionCounter (mac dinh 90)
    de dam bao khi ghep duoc, state (class da khoa, da qua vach chua...)
    cua canonical_id van con song, chua bi cleanup_old_tracks() xoa mat.

    Moi camera stream (moi thread trong ai-worker) phai tu tao rieng 1
    instance cua class nay - cung ly do nhu VehicleClassifier/DirectionCounter.
    """

    def __init__(self, max_distance_px=120, min_gap_frames=30, max_gap_frames=60):
        self.max_distance_px = max_distance_px
        self.min_gap_frames = min_gap_frames
        self.max_gap_frames = max_gap_frames

        self.canonical_of = {}   # raw_id (ByteTrack) -> canonical_id (dung de dem)
        self.raw_last_seen = {}  # raw_id -> frame_index cuoi cung thay raw_id nay
        self.last_position = {}  # canonical_id -> (x, y, frame_index cuoi cung thay)

    def resolve(self, raw_id: int, x: float, y: float, frame_index: int) -> int:
        self.raw_last_seen[raw_id] = frame_index

        if raw_id in self.canonical_of:
            canonical_id = self.canonical_of[raw_id]
        else:
            canonical_id = self._find_match(x, y, frame_index)
            if canonical_id is None:
                canonical_id = raw_id
            self.canonical_of[raw_id] = canonical_id

        self.last_position[canonical_id] = (x, y, frame_index)
        return canonical_id

    def _find_match(self, x, y, frame_index):
        best_id, best_dist = None, self.max_distance_px
        for canonical_id, (px, py, prev_frame) in self.last_position.items():
            gap = frame_index - prev_frame
            # gap < min_gap_frames: con qua som, danh phan nay cho ByteTrack
            # tu no gan lai (track_buffer) - khong duoc "cuop" mot track
            # dang con active o day.
            # gap > max_gap_frames: qua lau, coi la xe khac, khong ghep nua.
            if gap < self.min_gap_frames or gap > self.max_gap_frames:
                continue
            dist = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
            if dist < best_dist:
                best_dist, best_id = dist, canonical_id
        return best_id

    def cleanup_old_tracks(self, frame_index: int, max_missing_frames: int = None) -> None:
        limit = max_missing_frames if max_missing_frames is not None else self.max_gap_frames

        stale_raw = [
            raw_id for raw_id, seen_frame in self.raw_last_seen.items()
            if frame_index - seen_frame > limit
        ]
        for raw_id in stale_raw:
            self.raw_last_seen.pop(raw_id, None)
            self.canonical_of.pop(raw_id, None)

        stale_canonical = [
            canonical_id for canonical_id, (_, _, prev_frame) in self.last_position.items()
            if frame_index - prev_frame > limit
        ]
        for canonical_id in stale_canonical:
            self.last_position.pop(canonical_id, None)
