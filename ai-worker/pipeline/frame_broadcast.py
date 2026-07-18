import os
import socket
import threading

DEFAULT_SOCKET_PATH = "/tmp/shtp_ai_worker_view.sock"


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

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

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

    def close(self):
        self._stop_flag.set()
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
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
