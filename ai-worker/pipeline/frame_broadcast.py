import base64
import json
import os
import socket
import struct
import threading

import cv2

DEFAULT_SOCKET_PATH = "/tmp/shtp_ai_worker_view.sock"
JPEG_QUALITY = 80


class FrameBroadcaster:
    """Phat lai khung hinh + ket qua da xu ly boi NPU (frame, boxes,
    inference_ms, fps) qua 1 Unix domain socket cuc bo, de view_stream.py
    (chay o tien trinh khac) nhan lai va hien thi ma KHONG phai tu chay
    YOLO rieng nua (tranh 2 pipeline AI song song lang phi).

    Buoc 1: chi phan mo socket + chap nhan ket noi. Chua co publish() -
    xem npu_plan.md muc 10 Buoc 2.

    Ho tro 1 client tai 1 thoi diem (MVP, dung thuc te hien tai) - client
    moi ket noi vao se thay the client cu (dong ket noi cu).
    """

    def __init__(self, socket_path=DEFAULT_SOCKET_PATH):
        self.socket_path = socket_path
        self._client_conn = None
        self._client_lock = threading.Lock()
        self._stop_flag = threading.Event()

        # Xoa file socket cu neu con sot lai tu lan chay truoc bi crash -
        # bind() se loi "Address already in use" neu file van con ton tai
        # tren dia (dac diem cua Unix domain socket, khac TCP thuong).
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(self.socket_path)
        self._server_sock.listen(1)

        # "Hop thu 1 ngan" giu ban tin moi nhat can phat - publish() chi
        # ghi de bien nay (cuc nhanh), khong tu encode/gui - viec encode
        # JPEG + gui qua socket (cham hon) chay o _sender_loop, thread
        # RIENG, de KHONG BAO GIO lam cham vong lap NPU dang goi publish().
        self._latest = None
        self._latest_lock = threading.Lock()
        self._new_data_event = threading.Event()

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        self._sender_thread = threading.Thread(target=self._sender_loop, daemon=True)
        self._sender_thread.start()

    def _accept_loop(self):
        while not self._stop_flag.is_set():
            try:
                conn, _ = self._server_sock.accept()
            except OSError:
                break
            with self._client_lock:
                if self._client_conn is not None:
                    try:
                        self._client_conn.close()
                    except OSError:
                        pass
                self._client_conn = conn

    def has_client(self):
        with self._client_lock:
            return self._client_conn is not None

    def publish(self, station_id, frame, boxes, inference_ms, fps):
        """Ghi de khung MOI NHAT can phat - khong encode/gui gi o day, chi
        1 phep gan bien co khoa (cuc nhanh), an toan de goi tu vong lap
        NPU chinh moi frame ma khong lo lam cham no."""
        with self._latest_lock:
            self._latest = (station_id, frame, boxes, inference_ms, fps)
        self._new_data_event.set()

    def _sender_loop(self):
        while not self._stop_flag.is_set():
            got_new_data = self._new_data_event.wait(timeout=1.0)
            if not got_new_data:
                continue
            self._new_data_event.clear()

            with self._client_lock:
                conn = self._client_conn
            if conn is None:
                continue

            with self._latest_lock:
                item = self._latest
            if item is None:
                continue
            station_id, frame, boxes, inference_ms, fps = item

            ok, jpeg_buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if not ok:
                continue

            payload = {
                "station_id": station_id,
                "jpeg_b64": base64.b64encode(jpeg_buf.tobytes()).decode('ascii'),
                "boxes": [list(b) for b in boxes],
                "inference_ms": inference_ms,
                "fps": fps,
            }
            body = json.dumps(payload).encode('utf-8')
            header = struct.pack('>I', len(body))
            try:
                conn.sendall(header + body)
            except OSError:
                # Client mat ket noi/gui loi - dong lai, doi client sau ket
                # noi lai qua _accept_loop. Khong raise - khong duoc lam
                # gian doan vong lap NPU dang goi publish().
                with self._client_lock:
                    if self._client_conn is conn:
                        try:
                            conn.close()
                        except OSError:
                            pass
                        self._client_conn = None

    def close(self):
        self._stop_flag.set()
        self._new_data_event.set()
        try:
            self._server_sock.close()
        except OSError:
            pass
        with self._client_lock:
            if self._client_conn is not None:
                try:
                    self._client_conn.close()
                except OSError:
                    pass
                self._client_conn = None
        # Phai doi 2 thread nen DUNG HAN truoc khi close() tra ve - bai
        # hoc tu bug da gap o hailo_frame_source.py (npu_plan.md muc Buoc
        # 4): neu khong join(), thread nen co the van dang o giua 1 loi
        # goi he thong (socket op) luc tien trinh chinh bat dau thoat,
        # gay loi native "Aborted" khong ro rang.
        self._accept_thread.join(timeout=2)
        self._sender_thread.join(timeout=2)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
