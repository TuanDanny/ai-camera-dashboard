from collections import defaultdict
from types import SimpleNamespace

import numpy as np

from tracker_hailo.byte_tracker import BYTETracker

# Track_id cua moi BYTETracker rieng tu dem tu 0 - de gop lai thanh 1 ID
# duy nhat khong trung giua cac lop, offset theo class_id. 100_000 du lon
# de khong bao gio dung id that cua 1 tracker (thuc te moi tram khong bao
# gio co qua vai chuc nghin track lien tuc trong 1 phien chay).
_ID_OFFSET_PER_CLASS = 100_000


class ClassAwareTracker:
    """Bo tracking theo TUNG LOP xe - moi class_id 1 BYTETracker rieng.

    Khac voi cach dung 1 tracker chung cho tat ca cac lop roi phai "doan
    lai" class sau khi tracking (dung IoU so voi detection goc - de gan
    nham khi 2 loai xe khac nhau dung/di chuyen gan nhau), cach nay tach
    han tu dau: tracker cua "car" khong bao gio thay box cua "motorbike",
    nen khong the ghep nham ID giua 2 loai xe khac nhau. Loi giu nguyen
    thuat toan cot loi cua ByteTrack (Kalman filter + Hungarian matching,
    vendor tu tracker_hailo/) - chi viet moi lop quan ly nhieu instance
    theo class o day.
    """

    def __init__(self, target_classes, track_thresh=0.25, track_buffer=30,
                 match_thresh=0.8, frame_rate=30, mot20=False):
        args = SimpleNamespace(
            track_thresh=track_thresh,
            track_buffer=track_buffer,
            match_thresh=match_thresh,
            mot20=mot20,
        )
        self._trackers = {
            cls: BYTETracker(args, frame_rate=frame_rate)
            for cls in target_classes
        }

    def update(self, detections):
        """detections: list (x1, y1, x2, y2, score, class_id) tu
        HailoDetector.detect(). Tra ve list (track_id, class_id, score,
        x1, y1, x2, y2) - track_id da duy nhat toan cuc (offset theo lop),
        toa do da lam tron ve int o he pixel goc."""
        by_class = defaultdict(list)
        for x1, y1, x2, y2, score, cls in detections:
            if cls in self._trackers:
                by_class[cls].append([x1, y1, x2, y2, score])

        results = []
        for cls, tracker in self._trackers.items():
            dets_for_class = by_class.get(cls, [])
            arr = (np.array(dets_for_class, dtype=float) if dets_for_class
                   else np.empty((0, 5), dtype=float))
            online_tracks = tracker.update(arr)
            for t in online_tracks:
                x1, y1, x2, y2 = t.tlbr
                global_track_id = cls * _ID_OFFSET_PER_CLASS + t.track_id
                results.append((global_track_id, cls, float(t.score),
                                 int(x1), int(y1), int(x2), int(y2)))
        return results
