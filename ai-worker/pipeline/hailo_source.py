import threading

from picamera2.devices.hailo import Hailo

DEFAULT_HEF_PATH = "/usr/share/hailo-models/yolov8s_h8l.hef"

# picamera2.devices.hailo.Hailo.__init__() co doan:
#     if Hailo.TARGET is None:
#         Hailo.TARGET = VDevice(params)
# Day la check-then-act KHONG atomic. Da kiem chung bang thu nghiem thuc te
# (4 kich ban khac nhau) rang van de KHONG chi la race condition don gian
# co the fix bang 1 lock Python:
#   - 2 OS thread KHAC NHAU, ca hai dang SONG DONG THOI, moi ben tu goi
#     create_hailo() (du co lock serialize thu tu goi) -> LOI native
#     "Resource deadlock avoided" (khong phai segfault nhu doan ban dau).
#   - Chi 1 thread con duy nhat tu khoi tao (khong tranh chap gi) -> OK.
#   - Ca 2 lan khoi tao trong CUNG 1 thread (vd main thread, tuan tu), sau
#     do goi .run() dong thoi tu nhieu thread KHAC -> OK, hoan toan on dinh.
#   - Thread A khoi tao + chay + dong (.close()) + join XONG HOAN TOAN, roi
#     moi thread B (thread OS khac) khoi tao -> OK (vi luc nay A da giai
#     phong het, khong con 2 "chu so huu" song song nua).
#
# => RANG BUOC KIEN TRUC THAT SU: TAT CA loi goi create_hailo() (cho MOI
# camera/luong) BAT BUOC phai thuc hien tu CUNG 1 thread duy nhat (khuyen
# nghi: main thread cua tien trinh, truoc khi mo cac thread xu ly rieng cho
# tung camera) - thread con SAU DO chi duoc goi .run() tren instance da co
# san, KHONG duoc tu goi create_hailo()/Hailo() de tao instance moi cho
# rieng no. Lock duoi day van giu lai nhu 1 lop an toan bo sung (chan dung
# truong hop vi pham quy tac tren xay ra dung luc tuc thoi), nhung KHONG
# du de thay the cho viec tuan thu dung kien truc "khoi tao tap trung 1
# noi" - day la diem quan trong can nho khi noi day pipeline o cac buoc sau.
_hailo_init_lock = threading.Lock()


def create_hailo(hef_path=DEFAULT_HEF_PATH):
    """Khoi tao 1 Hailo() instance.

    CANH BAO: chi duoc goi ham nay tu 1 thread duy nhat cho toan bo vong doi
    ung dung (vd main thread, truoc khi spawn thread rieng cho tung camera).
    Goi tu nhieu thread khac nhau - du co the ket qua co the "co ve chay
    duoc" luc test nhanh - da duoc chung minh gay loi native khong on dinh
    (xem ghi chu o tren). Lock o day chi bao ve truong hop tranh chap tuc
    thoi trong CUNG 1 thread goi lien tiep nhanh, khong thay the duoc quy
    tac kien truc nay.
    """
    with _hailo_init_lock:
        return Hailo(hef_path)
