import time
from collections import defaultdict
from types import SimpleNamespace

import numpy as np

from tracker_hailo.byte_tracker import BYTETracker

# He so lam muot EMA cho toc do frame do duoc thuc te - thap de khong
# nhay lien tuc theo tung frame don le (vd 1 frame bi cham dot bien khong
# lam buffer_size doi ngay), nhung van bam sat xu huong that trong vai
# giay.
_FPS_EMA_ALPHA = 0.1

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
                 match_thresh=0.8, frame_rate=30, mot20=True):
        # mot20 o day thuc chat la co "TAT fuse_score" cua ByteTrack hay
        # khong (ten "mot20" la ke thua tu tracker_hailo/byte_tracker.py
        # goc, gan voi 1 bo du lieu benchmark, khong lien quan gi den y
        # nghia o day). fuse_score nhan IoU voi confidence cua detection
        # thanh 1 cost duy nhat truoc khi so voi match_thresh - da xac
        # nhan bang test thuc te: chi can confidence dao dong xuong trung
        # binh (vd 0.22-0.30, rat pho bien luc xe dang di chuyen/mo/che
        # khuat nhe) CONG VOI IoU khong hoan hao (thuc te binh thuong voi
        # vat the dang di chuyen) la du de vuot nguong match_thresh=0.80,
        # DU vi tri track du doan dung gan hoan hao. mot20=True (mac dinh
        # moi) tat co che nay, chi con dung IoU thuan (khong phu thuoc
        # confidence) - on dinh hon nhieu qua thu nghiem voi vat the
        # dung yen VA chuyen dong that.
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
        # track_buffer trong config la "so frame o 30fps" (quy uoc goc cua
        # ByteTrack) - luu lai de tinh QUY DOI sang so frame thuc te moi
        # khi toc do do duoc thay doi, thay vi dung 1 frame_rate hang so
        # co dinh luc khoi tao (da xac dinh thuc te: NPU chay ~45-55fps,
        # khong phai 30 - neu giu co dinh 30, buffer_size/max_time_lost
        # cua BYTETracker se ngan hon y dinh gan 1 nua thoi gian thuc,
        # khien track "quen" xe qua nhanh luc bi che khuat -> doi ID oan
        # -> dem trung. Xem npu_plan.md.
        self._track_buffer_frames_at_30fps = track_buffer
        self._fps_ema = float(frame_rate)
        self._last_update_ts = None

    def _refresh_buffer_size(self):
        """Do toc do THAT giua 2 lan .update() lien tiep (khoang cach wall-
        clock thuc su giua cac lan tracker nhan detection, khong gia dinh
        truoc), lam muot bang EMA, roi tinh lai buffer_size/max_time_lost
        cua MOI BYTETracker con de dai "nho" thuc te (tinh bang giay) luon
        giu nguyen dung nhu config du toc do xu ly thuc te co bien dong."""
        now = time.perf_counter()
        if self._last_update_ts is not None:
            elapsed = now - self._last_update_ts
            if elapsed > 0:
                instant_fps = 1.0 / elapsed
                self._fps_ema = (
                    self._fps_ema * (1 - _FPS_EMA_ALPHA)
                    + instant_fps * _FPS_EMA_ALPHA
                )
                new_buffer_size = max(
                    1, int(self._fps_ema / 30.0 * self._track_buffer_frames_at_30fps)
                )
                for tracker in self._trackers.values():
                    tracker.buffer_size = new_buffer_size
                    tracker.max_time_lost = new_buffer_size
        self._last_update_ts = now

    def update(self, detections):
        """detections: list (x1, y1, x2, y2, score, class_id) tu
        HailoDetector.detect(). Tra ve list (track_id, class_id, score,
        x1, y1, x2, y2) - track_id da duy nhat toan cuc (offset theo lop),
        toa do da lam tron ve int o he pixel goc."""
        self._refresh_buffer_size()
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
