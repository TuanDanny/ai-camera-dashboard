import http.server
import json
import os
import socket
import struct
import threading
import time
import urllib.parse

import cv2
import numpy as np

DEFAULT_SOCKET_PATH = "/tmp/shtp_ai_worker_view.sock"
JPEG_QUALITY = 80
# Neu client khong doc kip trong tung nay giay, coi nhu client "chet"/
# treo, dong ket noi thay vi de conn.sendall() cho vo thoi han (xem
# _accept_loop). socket.timeout la alias cua TimeoutError, la subclass cua
# OSError - da duoc bat dung boi "except OSError" co san trong _sender_loop.
SEND_TIMEOUT_S = 0.3

# MJPEG-over-HTTP: de nhung truc tiep vao panel "Text" (HTML) cua Grafana
# qua the <img src=".../stream">, khong can plugin/JS gi ca - trinh duyet
# tu render multipart/x-mixed-replace nhu anh dong. Khac voi Unix socket
# (gui frame goc + box roi, client tu ve), o day PHAI ve box+nhan luon
# vao anh truoc khi encode vi <img> khong chay duoc code de tu ve.
MJPEG_HTTP_PORT = 8090
MJPEG_POLL_INTERVAL_S = 0.05  # ~20fps cho xem qua dashboard - du muot,
                              # khong can bang FPS NPU that (45+fps se
                              # ton CPU ve/encode nhieu hon can thiet cho
                              # muc dich xem tong quan qua web).
_MJPEG_COCO_MAP = {3: "motorbike", 2: "car", 7: "truck", 5: "bus", 1: "bicycle"}

# Mau box theo tung loai xe (BGR - OpenCV dung nguoc thu tu so voi RGB),
# khop voi mau cot cua tung panel "Total X Today" tren dashboard
# Traffic Overview (grafana/dashboards/traffic_overview.json) de nhin
# giua video va dashboard ra cung 1 mau la hieu ngay dang loai nao.
_CATEGORY_COLORS_BGR = {
    "motorbike": (0, 165, 255),   # cam
    "car": (242, 148, 87),        # xanh duong
    "truck": (211, 0, 148),       # tim
    "bus": (0, 200, 0),           # xanh la
    "bicycle": (255, 255, 0),     # xanh cyan (dashboard khong co panel rieng, tu chon)
    "unknown": (150, 150, 150),   # xam
}
_COUNT_LINE_COLOR_BGR = (0, 0, 255)  # do


def _draw_boxes_for_mjpeg(frame, boxes, y_ratio=None):
    """Ve box (mau theo loai xe) + nhan + vach dem (do) len 1 BAN SAO cua
    frame (KHONG sua frame goc - frame goc con duoc dung chung boi Unix
    socket sender de gui cho view_stream.py, sua tai cho se lam "lem" box
    vao ca duong do)."""
    annotated = frame.copy()

    if y_ratio is not None:
        line_y = int(annotated.shape[0] * y_ratio)
        cv2.line(annotated, (0, line_y), (annotated.shape[1], line_y), _COUNT_LINE_COLOR_BGR, 2)

    for cls_id, confidence, x1, y1, x2, y2 in boxes:
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        category = _MJPEG_COCO_MAP.get(cls_id, "unknown")
        color = _CATEGORY_COLORS_BGR.get(category, _CATEGORY_COLORS_BGR["unknown"])
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"{category} {confidence:.2f}"
        cv2.putText(
            annotated, label, (x1, max(y1 - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA
        )
    return annotated


_off_placeholder_cache = None


def _get_off_placeholder_jpeg():
    """Anh tinh 'da tat' - tra ve ngay lap tuc (khong stream) khi query param
    ?on=0, de nut bat/tat tren Grafana thuc su ngung ton CPU ve/encode ben
    main.py, khong chi an giao dien. Cache lai vi noi dung khong doi."""
    global _off_placeholder_cache
    if _off_placeholder_cache is None:
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(
            img, "Live view dang TAT", (60, 170),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (128, 128, 128), 2, cv2.LINE_AA
        )
        cv2.putText(
            img, "Bam nut Bat o thanh cong cu de xem", (60, 210),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 100), 1, cv2.LINE_AA
        )
        ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        _off_placeholder_cache = buf.tobytes() if ok else b''
    return _off_placeholder_cache


class _MJPEGRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # im lang - khong spam stdout cua main.py moi request

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/snapshot':
            self._handle_snapshot()
            return
        if parsed.path != '/stream':
            self.send_error(404)
            return
        query = urllib.parse.parse_qs(parsed.query)
        # Mac dinh "1" (bat) de van test truc tiep duoc qua curl/browser
        # khong can query param - nut bat/tat tren Grafana se luon gui
        # ro rang ?on=0 hoac ?on=1.
        is_on = query.get('on', ['1'])[0] != '0'
        if not is_on:
            # TAT: tra ve 1 anh tinh DUY NHAT roi dong ket noi ngay - hoan
            # toan khong dong cham toi broadcaster._latest/ve box/encode
            # lien tuc, dung y muon "bam tat la het ton CPU main.py".
            placeholder = _get_off_placeholder_jpeg()
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(placeholder)))
            self.send_header('Cache-Control', 'no-cache, private')
            self.end_headers()
            try:
                self.wfile.write(placeholder)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return

        broadcaster = self.server.broadcaster
        try:
            self.send_response(200)
            self.send_header('Age', '0')
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            while not broadcaster._stop_flag.is_set():
                with broadcaster._latest_lock:
                    item = broadcaster._latest
                if item is not None:
                    _, frame, boxes, _, _, y_ratio = item
                    annotated = _draw_boxes_for_mjpeg(frame, boxes, y_ratio=y_ratio)
                    ok, jpeg_buf = cv2.imencode(
                        '.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
                    )
                    if ok:
                        jpeg_bytes = jpeg_buf.tobytes()
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(jpeg_bytes)))
                        self.end_headers()
                        self.wfile.write(jpeg_bytes)
                        self.wfile.write(b'\r\n')
                time.sleep(MJPEG_POLL_INTERVAL_S)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # client dong tab/mat mang - binh thuong, khong phai loi

    def _handle_snapshot(self):
        """GET /snapshot - tra ve DUNG 1 anh JPEG hien tai (khong phai
        multipart lien tuc nhu /stream) - dung cho tg_bot/ (lenh view/
        snapshot) hoac bat ky noi nao chi can 1 khung hinh don le, khong
        can giu ket noi mo lien tuc."""
        broadcaster = self.server.broadcaster
        with broadcaster._latest_lock:
            item = broadcaster._latest
        if item is None:
            self.send_error(503, "Chua co khung hinh nao (ai-worker moi khoi dong?)")
            return

        _, frame, boxes, _, _, y_ratio = item
        annotated = _draw_boxes_for_mjpeg(frame, boxes, y_ratio=y_ratio)
        ok, jpeg_buf = cv2.imencode(
            '.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
        )
        if not ok:
            self.send_error(500, "Khong encode duoc JPEG")
            return
        jpeg_bytes = jpeg_buf.tobytes()
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(jpeg_bytes)))
            self.send_header('Cache-Control', 'no-cache, private')
            self.end_headers()
            self.wfile.write(jpeg_bytes)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


class _MJPEGServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, broadcaster, *args, **kwargs):
        self.broadcaster = broadcaster
        super().__init__(*args, **kwargs)


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

        # HTTP MJPEG rieng (port khac, khong dung chung Unix socket) - de
        # nhung truc tiep vao Grafana qua the <img>. Chi ton CPU ve/encode
        # LUC CO REQUEST dang mo (xem _MJPEGRequestHandler.do_GET) - dong
        # tab/gap panel lai la ngung ngay, khong chay nen khi khong ai xem.
        self._mjpeg_server = _MJPEGServer(
            self, ('0.0.0.0', MJPEG_HTTP_PORT), _MJPEGRequestHandler
        )
        self._mjpeg_thread = threading.Thread(target=self._mjpeg_server.serve_forever, daemon=True)
        self._mjpeg_thread.start()

    def _accept_loop(self):
        while not self._stop_flag.is_set():
            try:
                conn, _ = self._server_sock.accept()
            except OSError:
                break
            # QUAN TRONG: neu khong dat timeout, client ket noi vao nhung
            # khong doc gi (vd cua so bi dung, GUI treo) se lam OS socket
            # buffer day dan, roi conn.sendall() trong _sender_loop se
            # CHAN VO THOI HAN - da do duoc thuc te lam FPS NPU tut ~10%
            # (44.8 -> 40.5fps trung binh) du publish() ban than khong
            # block. Dat timeout ngan de gioi han toi da thoi gian
            # _sender_loop co the bi "ket" cho 1 client cham.
            conn.settimeout(SEND_TIMEOUT_S)
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

    def publish(self, station_id, frame, boxes, inference_ms, fps, y_ratio=None):
        """Ghi de khung MOI NHAT can phat - khong encode/gui gi o day, chi
        1 phep gan bien co khoa (cuc nhanh), an toan de goi tu vong lap
        NPU chinh moi frame ma khong lo lam cham no. y_ratio: vi tri vach
        dem xe (0-1, ty le chieu cao khung hinh) - chi dung de VE (o
        MJPEG), khong anh huong gi toi logic dem xe that trong main.py."""
        with self._latest_lock:
            self._latest = (station_id, frame, boxes, inference_ms, fps, y_ratio)
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
            station_id, frame, boxes, inference_ms, fps, y_ratio = item

            ok, jpeg_buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if not ok:
                continue

            # Khong con ma hoa base64 (tung lam anh JPEG phinh them ~33%
            # kich thuoc + ton CPU ma hoa/giai ma that su o ca 2 dau - da do
            # duoc day chinh la nguyen nhan chinh khien FPS hien thi chi dat
            # ~20fps thay vi ~40-45fps cua NPU that). Gui rieng 2 phan:
            # metadata JSON nho (khong co anh) + khoi JPEG nhi phan tho,
            # moi phan tu co 4 byte dau ghi do dai.
            meta = {
                "station_id": station_id,
                "boxes": [list(b) for b in boxes],
                "inference_ms": inference_ms,
                "fps": fps,
            }
            meta_bytes = json.dumps(meta).encode('utf-8')
            jpeg_bytes = jpeg_buf.tobytes()
            try:
                _send_framed(conn, meta_bytes)
                _send_framed(conn, jpeg_bytes)
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

        # shutdown() bat serve_forever() dung vong lap (goi tu thread khac
        # thread dang chay serve_forever la an toan, day la cach lam chuan
        # cua http.server). server_close() dong socket lang nghe han.
        self._mjpeg_server.shutdown()
        self._mjpeg_server.server_close()
        self._mjpeg_thread.join(timeout=2)


def _recv_exact(sock, n):
    """Doc dung n byte tu socket (recv() co the tra ve it hon n byte moi
    lan goi - phai lap lai cho du). Tra ve None neu ket noi bi dong giua
    chung (EOF) truoc khi du n byte."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _send_framed(conn, data):
    """Gui 1 khoi du lieu voi 4 byte dau ghi do dai (length-prefixed
    framing) - dung chung cho ca phan JSON metadata va phan JPEG nhi phan."""
    conn.sendall(struct.pack('>I', len(data)) + data)


def _recv_framed(sock):
    """Doc 1 khoi du lieu duoc dong goi boi _send_framed(). Tra ve None
    neu ket noi bi dong giua chung (EOF)."""
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    length = struct.unpack('>I', header)[0]
    return _recv_exact(sock, length)


def socket_frame_source(socket_path=DEFAULT_SOCKET_PATH, connect_timeout=5.0):
    """Generator phia client: ket noi vao FrameBroadcaster dang chay trong
    main.py, nhan lien tuc, giai ma, yield (frame, boxes, inference_ms,
    fps) - CUNG hinh dang voi cpu_frame_source()/hailo_frame_source() de
    view_stream.py dung chung 1 vong lap ve/hien thi, khong doi gi.

    Khac voi cpu_frame_source/hailo_frame_source, ham nay KHONG tu chay
    YOLO - chi nhan lai ket qua da tinh san tu main.py (NPU), nen ben goi
    (view_stream.py) hau nhu khong ton CPU cho inference nua.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(connect_timeout)
    try:
        sock.connect(socket_path)
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout) as e:
        raise RuntimeError(
            f"Khong ket noi duoc toi main.py qua socket '{socket_path}' - "
            f"main.py co dang chay va co bat FrameBroadcaster (backend "
            f"hailo) khong?"
        ) from e
    sock.settimeout(None)  # ve blocking mode binh thuong cho vong doc chinh

    try:
        while True:
            meta_bytes = _recv_framed(sock)
            if meta_bytes is None:
                raise RuntimeError(
                    "Mat ket noi toi main.py (co the main.py da bi tat) - "
                    "khong con nhan duoc du lieu qua socket nua."
                )
            meta = json.loads(meta_bytes.decode('utf-8'))

            jpeg_bytes = _recv_framed(sock)
            if jpeg_bytes is None:
                raise RuntimeError(
                    "main.py dong ket noi giua chung luc dang gui du lieu."
                )

            frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            boxes = [tuple(b) for b in meta["boxes"]]
            inference_ms = meta["inference_ms"]
            fps = meta["fps"]

            yield frame, boxes, inference_ms, fps
    finally:
        sock.close()
