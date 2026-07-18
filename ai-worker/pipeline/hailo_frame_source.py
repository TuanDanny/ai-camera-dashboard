import queue
import threading
import time

import cv2

from pipeline.hailo_detector import HailoDetector
from pipeline.hailo_tracker import ClassAwareTracker

DEFAULT_BUFFER_SIZE = 1
STREAM_DOWN_THRESHOLD = 25  # so lan doc frame lien tiep that bai truoc khi bao "mat ket noi"


def hailo_frame_source(hailo_instance, url, target_classes, conf=0.10,
                        buffer_size=DEFAULT_BUFFER_SIZE,
                        track_thresh=0.25, track_buffer=30, match_thresh=0.8,
                        on_stream_down=None, on_stream_recovered=None,
                        on_frame_dropped=None):
    """Sinh (frame, boxes, inference_ms, fps) qua NPU Hailo, kien truc
    producer-consumer bat dong bo (xem npu_plan.md muc 3.3):

    - 1 thread nen (producer) doc frame tu RTSP -> detect (HailoDetector)
      -> track (ClassAwareTracker) -> dong goi khung -> day vao buffer noi
      bo. KHONG BAO GIO cho consumer - neu buffer day, ghi de khung cu
      nhat (drop-oldest).
    - Ham nay (generator, chay o thread cua nguoi goi = "consumer") chi
      lay khung MOI NHAT tu buffer, KHONG BAO GIO cho producer qua lau
      (dung timeout).

    hailo_instance: PHAI duoc tao san boi nguoi goi qua
    pipeline.hailo_source.create_hailo() TU 1 THREAD DUY NHAT (xem
    hailo_source.py va npu_plan.md muc 2.2b/3.4) - ham nay khong tu tao
    Hailo() moi, chi nhan lai instance co san.

    boxes tra ve: list (track_id, class_id, score, x1, y1, x2, y2) - CUNG
    hinh dang voi pipeline.frame_source.cpu_frame_source() de main.py/
    view_stream.py dung chung 1 vong lap khong can biet dang dung backend
    nao.

    buffer_size: do sau buffer.
      - 1 (mac dinh): luon giu dung ban moi nhat, ghi de ban cu ngay khi
        co ban moi - dung cho view truc tiep (view_stream.py), uu tien
        toc do hien thi/FPS cao nhat, mat khung khong sao.
      - 3-5: dung cho nhanh dem xe that (main.py) - lop dem an toan chong
        mat khung khi tieu thu (CPU) khung ngan bat thuong. Van co gioi
        han cung, khong vo han.
    on_frame_dropped(dropped_count): callback tuy chon, goi moi lan buffer
    day phai ghi de 1 khung cu - de do dac THAT co bao gio rot khung hay
    khong (npu_plan.md muc 3.3), thay vi doan.
    on_stream_down(attempt) / on_stream_recovered(): callback tuy chon,
    giong het interface cua cpu_frame_source - de main.py tu quyet dinh
    lam gi (vd publish alert), module nay khong biet gi ve MQTT.
    """
    detector = HailoDetector(hailo_instance, classes=target_classes, conf=conf)
    tracker = ClassAwareTracker(target_classes, track_thresh=track_thresh,
                                 track_buffer=track_buffer, match_thresh=match_thresh)

    buffer = queue.Queue(maxsize=buffer_size)
    dropped_count = 0
    stop_flag = threading.Event()

    def producer():
        nonlocal dropped_count
        cap = cv2.VideoCapture(url)
        fail_streak = 0
        stream_down_alerted = False

        while not stop_flag.is_set():
            ok, frame = cap.read()
            if not ok:
                fail_streak += 1
                if fail_streak >= STREAM_DOWN_THRESHOLD and not stream_down_alerted:
                    if on_stream_down:
                        on_stream_down(fail_streak)
                    stream_down_alerted = True
                time.sleep(0.2)
                cap.release()
                cap = cv2.VideoCapture(url)
                continue

            if fail_streak > 0:
                fail_streak = 0
                if stream_down_alerted:
                    if on_stream_recovered:
                        on_stream_recovered()
                    stream_down_alerted = False

            t0 = time.perf_counter()
            dets = detector.detect(frame)
            boxes = tracker.update(dets)
            elapsed = time.perf_counter() - t0
            inference_ms = int(elapsed * 1000)
            fps = 1.0 / elapsed if elapsed > 0 else 0.0

            if buffer.full():
                try:
                    buffer.get_nowait()
                    dropped_count += 1
                    if on_frame_dropped:
                        on_frame_dropped(dropped_count)
                except queue.Empty:
                    pass
            buffer.put((frame, boxes, inference_ms, fps))

        cap.release()

    producer_thread = threading.Thread(target=producer, daemon=True)
    producer_thread.start()

    try:
        while True:
            try:
                yield buffer.get(timeout=1.0)
            except queue.Empty:
                continue
    finally:
        # Phai doi producer thread DUNG HAN (join) truoc khi tra quyen
        # dieu khien lai cho nguoi goi - neu khong, nguoi goi co the dong
        # hailo_instance (.close()) ngay sau vong lap "for...in source",
        # trong khi producer thread van dang chay .run() tren instance do
        # -> crash native. Luu y: neu vong lap ngoai chi "break" thay vi
        # goi het iterator/source.close() tuong minh, Python KHONG dam bao
        # goi finally nay ngay lap tuc - nguoi goi ham nay nen tu goi
        # source.close() tuong minh sau vong lap for de dam bao dung dung
        # luc (xem vi du trong docstring/test).
        stop_flag.set()
        producer_thread.join(timeout=5)
