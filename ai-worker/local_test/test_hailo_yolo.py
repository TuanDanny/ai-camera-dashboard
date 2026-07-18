"""
Kiem chung toan tien/hau xu ly cua HailoYolo (letterbox preprocess +
denormalize NMS-by-class output) bang so lieu gia - KHONG can phan cung
Hailo that. Phan nay la toan hoc thuan tuy, tach rieng khoi phan chi chay
duoc tren may co NPU (da test thu cong voi anh that, xem ghi chu trong
hailo_yolo.py).

Luu y quan trong ve _denormalize: box dau vao (det[:4] tu Hailo) o thu tu
[ymin, xmin, ymax, xmax] (kieu TF NMS), KHONG phai [x1,y1,x2,y2]. Ham nay
tu swap lai thanh [xmin,ymin,xmax,ymax] o buoc return - da kiem chung bang
anh that (xem lich su chat), cac test ben duoi tinh tay dung thu tu nay.
"""
import sys
import numpy as np

AI_WORKER_DIR = "/home/shtp/ai-camera-dashboard/ai-worker"
sys.path.insert(0, AI_WORKER_DIR)

from hailo_yolo import HailoYolo  # noqa: E402


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    return condition


class FakeHailoDevice:
    """Gia lap picamera2.devices.hailo.Hailo - khong dung phan cung that."""

    def __init__(self, raw_output=None):
        self._raw_output = raw_output

    def get_input_shape(self):
        return (640, 640, 3)

    def run(self, _preprocessed):
        return self._raw_output


class FakeHailoYolo(HailoYolo):
    """HailoYolo nhung bo qua __init__ that (khong mo phan cung), chi gan
    thang cac thuoc tinh can cho _preprocess/_denormalize/detect."""

    def __init__(self, raw_output=None, classes=None, conf=0.10):
        self.input_h, self.input_w = 640, 640
        self.classes = set(classes) if classes else None
        self.conf = conf
        self._hailo = FakeHailoDevice(raw_output)


def test_denormalize_square_frame():
    print("\n--- Kich ban 1: frame vuong (khong padding) ---")
    box = HailoYolo._denormalize([0.25, 0.25, 0.75, 0.75], size=640, padding_length=0,
                                  img_h=640, img_w=640)
    # ymin=0.25*640=160, xmin=0.25*640=160, ymax=0.75*640=480, xmax=0.75*640=480
    # khong padding (frame vuong) -> swap thanh [xmin,ymin,xmax,ymax] = [160,160,480,480]
    return check("box vuong khong padding dung [160,160,480,480]", box == [160, 160, 480, 480])


def test_denormalize_wide_frame_padding():
    print("\n--- Kich ban 2: frame ngang 1280x720 (nhu camera thuc te) ---")
    img_h, img_w = 720, 1280
    size = max(img_h, img_w)  # 1280
    padding_length = int(abs(img_h - img_w) / 2)  # 280

    # dau vao [ymin, xmin, ymax, xmax] = [0.4, 0.5, 0.6, 0.6]
    box = HailoYolo._denormalize([0.4, 0.5, 0.6, 0.6], size, padding_length, img_h, img_w)
    # ymin=0.4*1280=512 -280(img_h!=size)=232 ; xmin=0.5*1280=640 (khong tru, img_w==size)
    # ymax=0.6*1280=768 -280=488          ; xmax=0.6*1280=768 (khong tru)
    # swap -> [xmin,ymin,xmax,ymax] = [640,232,768,488]
    return check("box trong frame ngang tru padding dung truc y, swap dung thu tu",
                 box == [640, 232, 768, 488])


def test_preprocess_output_shape():
    print("\n--- Kich ban 3: preprocess tra ve dung kich thuoc input model (640x640x3) ---")
    detector = FakeHailoYolo()
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    padded = detector._preprocess(frame)
    return check("preprocess tra ve dung shape (640,640,3)", padded.shape == (640, 640, 3))


def test_detect_filters_by_class_and_conf():
    print("\n--- Kich ban 4: detect() loc dung theo class va nguong confidence ---")

    raw = [[] for _ in range(80)]
    raw[2] = [[0.1, 0.1, 0.2, 0.2, 0.9], [0.3, 0.3, 0.4, 0.4, 0.05]]  # car: 1 qua nguong, 1 duoi nguong
    raw[0] = [[0.5, 0.5, 0.6, 0.6, 0.99]]  # person - khong nam trong classes quan tam

    detector = FakeHailoYolo(raw_output=raw, classes={1, 2, 3, 5, 7}, conf=0.10)
    frame = np.zeros((640, 640, 3), dtype=np.uint8)
    dets = detector.detect(frame)

    only_car_above_thresh = len(dets) == 1 and dets[0][5] == 2 and dets[0][4] == 0.9
    return check("detect() chi giu 1 box class=car conf=0.9, bo qua person va box duoi nguong",
                 only_car_above_thresh)


def main():
    results = [
        test_denormalize_square_frame(),
        test_denormalize_wide_frame_padding(),
        test_preprocess_output_shape(),
        test_detect_filters_by_class_and_conf(),
    ]

    print(f"\n=== Ket qua: {sum(results)}/{len(results)} kich ban PASS ===")
    if all(results):
        print("TAT CA PASS")
    else:
        print("CO KICH BAN FAIL - kiem tra lai truoc khi dua vao main.py")


if __name__ == "__main__":
    main()
