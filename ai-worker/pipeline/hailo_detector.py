import numpy as np
import cv2


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
        resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

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

        dets = []
        for class_id, class_dets in enumerate(raw):
            if self.classes is not None and class_id not in self.classes:
                continue
            for det in class_dets:
                score = float(det[4])
                if score < self.conf:
                    continue
                x1, y1, x2, y2 = self._denormalize(det[:4], size, padding_length, img_h, img_w)
                dets.append((x1, y1, x2, y2, score, class_id))
        return dets
