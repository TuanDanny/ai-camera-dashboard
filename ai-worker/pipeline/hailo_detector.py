import numpy as np
import cv2

# NMS-by-class tren chip Hailo lam rieng cho TUNG LOP (80 mang tach biet),
# nen 2 van de trung lap khac nhau co the lot qua:
# (1) trung lap TRONG CUNG 1 lop - vd 2 box cua "car" gan sat nhau (da xac
#     nhan thuc te bang test anh xe tinh: 1 xe that nhung thinh thoang co
#     them 1 box thu 2 hoi khac kich thuoc, confidence thap hon).
# (2) trung lap GIUA CAC LOP KHAC NHAU - vd model tu tin ca "car" (0.85) va
#     "truck" (0.60) cho CUNG 1 vung anh (YOLO la multi-label per-class,
#     hoan toan co the xay ra) - da xac nhan thuc te qua bao cao nguoi
#     dung: 1 xe that hien ra 2 box, 1 gan "car" 1 gan "truck". Vi
#     ClassAwareTracker dung 1 BYTETracker RIENG cho tung lop, 2 box nay
#     se thanh 2 track SONG SONG cho CUNG 1 xe -> ca 2 deu cat vach ->
#     dem 2 lan, 2 loai khac nhau.
# Ca 2 truong hop deu la "cung 1 vung khong gian, nhieu box chong lan" -
# nen chi can 1 lan NMS software chay TOAN CUC (khong phan biet lop, xem
# cach goi trong detect() ben duoi) la giai quyet duoc ca 2, giu lai box
# confidence cao nhat trong moi nhom chong lan bat ke no tu nhan la lop gi.
# Ngưỡng 0.5 (cũ) qua thap - da xac nhan bang test hinh hoc thuc te: 2 XE
# KHAC NHAU di gan nhau (rat pho bien voi xe may VN) co the co IoU 0.54-0.74
# (vd lech 15-30px tren box rong ~100px), bi ngo nhan la "trung lap cua
# cung 1 xe" va bi xoa oan -> dem thieu khi nhieu xe cat vach cung luc. Nang
# len 0.8: box trung lap THAT (cung 1 xe, model xuat du 1 box do NMS-by-
# class tren chip khong loc duoc) do duoc IoU ~0.87-0.9 trong test thuc te,
# van > 0.8 nen van bi loc dung; con 2 xe that di gan/rat gan nhau (IoU
# 0.54-0.74) gio < 0.8 nen duoc giu lai ca 2. Khong co nguong nao an toan
# tuyet doi 100% (2 xe ep sat qua muc co the vuot ca 0.8) nhung 0.8 la diem
# can bang tot hon han 0.5 dua tren so lieu do duoc.
_DEDUP_IOU_THRESH = 0.8


def _nms_dedup(boxes, scores, iou_thresh=_DEDUP_IOU_THRESH):
    """Tra ve danh sach index nen GIU LAI, sau khi loc bo box trung lap
    (IoU > iou_thresh voi 1 box confidence cao hon trong CUNG danh sach).
    boxes: list [x1,y1,x2,y2]. Chuan NMS greedy, khong dung thu vien ngoai."""
    if not boxes:
        return []
    boxes_arr = np.asarray(boxes, dtype=np.float64)
    scores_arr = np.asarray(scores, dtype=np.float64)
    x1, y1, x2, y2 = boxes_arr[:, 0], boxes_arr[:, 1], boxes_arr[:, 2], boxes_arr[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores_arr.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[rest] - inter
        iou = np.where(union > 0, inter / union, 0.0)
        order = rest[iou <= iou_thresh]
    return keep


class HailoDetector:
    """Tien xu ly + inference + giai ma NMS-by-class cho model YOLOv8s tren
    Hailo-8L. KHONG tu tao Hailo() ben trong - nhan 1 instance da khoi tao
    san (qua pipeline.hailo_source.create_hailo(), goi tu 1 thread duy nhat
    - xem hailo_source.py) lam tham so, chi goi .run() tren instance do.

    Model .hef nay co NMS-by-class bake san tren chip (xem hailortcli
    parse-hef): output la 1 list 80 phan tu (1 per COCO class), moi phan tu
    la mang [x1,y1,x2,y2,score] da normalize 0-1. Cong thuc preprocess
    (letterbox, khong doi mau BGR->RGB) va denormalize duoc giu nguyen tu
    ban da kiem chung dung truoc day (khop dung cach model duoc compile -
    khong phai cho de "thiet ke lai cho hay hon", chi can dung).
    """

    def __init__(self, hailo_instance, classes=None, conf=0.10):
        self._hailo = hailo_instance
        self.classes = set(classes) if classes else None
        self.conf = conf
        self.input_h, self.input_w, _ = self._hailo.get_input_shape()

    def _preprocess(self, frame_bgr):
        img_h, img_w = frame_bgr.shape[:2]
        scale = min(self.input_w / img_w, self.input_h / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)
        # INTER_LINEAR (thay INTER_CUBIC) - re hon dang ke, giu native call
        # ngan hon => giam cua so co the bi gianh GIL boi thread khac dung
        # luc dang resize (da do duoc bang py-spy: 1 lan FPS rot xuong
        # 16.6fps trung khop chinh xac luc dung 508ms tai dong resize nay -
        # xem npu_plan.md). Chat luong resize giam nhe khong dang ke o day
        # vi anh chi dung de letterbox truoc khi dua vao NPU, khong phai
        # anh hien thi cuoi cung.
        resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        padded = np.full((self.input_h, self.input_w, 3), 114, dtype=np.uint8)
        x_off = (self.input_w - new_w) // 2
        y_off = (self.input_h - new_h) // 2
        padded[y_off:y_off + new_h, x_off:x_off + new_w] = resized
        return padded

    @staticmethod
    def _denormalize(box, size, padding_length, img_h, img_w):
        box = [int(v * size) for v in box]
        for i in range(4):
            if i % 2 == 0:
                if img_h != size:
                    box[i] -= padding_length
            else:
                if img_w != size:
                    box[i] -= padding_length
        return [box[1], box[0], box[3], box[2]]

    def detect(self, frame_bgr):
        """Tra ve list (x1, y1, x2, y2, score, class_id) da loc theo
        self.classes/self.conf, toa do o he pixel cua frame_bgr goc."""
        img_h, img_w = frame_bgr.shape[:2]
        preprocessed = self._preprocess(frame_bgr)
        raw = self._hailo.run(preprocessed)

        size = max(img_h, img_w)
        padding_length = int(abs(img_h - img_w) / 2)

        # Gom TAT CA lop lai thanh 1 danh sach duy nhat truoc, roi moi loc
        # trung lap 1 LAN DUY NHAT TREN TOAN BO (xem giai thich o
        # _DEDUP_IOU_THRESH) - khong con dedup rieng tung lop nhu truoc,
        # de bat duoc ca truong hop model tu tin nham 2 lop khac nhau cho
        # cung 1 vung anh.
        candidates = []
        for class_id, class_dets in enumerate(raw):
            if self.classes is not None and class_id not in self.classes:
                continue
            for det in class_dets:
                score = float(det[4])
                if score < self.conf:
                    continue
                x1, y1, x2, y2 = self._denormalize(det[:4], size, padding_length, img_h, img_w)
                candidates.append((x1, y1, x2, y2, score, class_id))

        if not candidates:
            return []

        boxes = [c[:4] for c in candidates]
        scores = [c[4] for c in candidates]
        return [candidates[i] for i in _nms_dedup(boxes, scores)]
