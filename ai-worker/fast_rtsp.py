import cv2
import threading
import time
import os

class FastRTSPReader:
    def __init__(self, url):
        self.url = url
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        self.latest_frame = None
        self.running = True
        self.lock = threading.Lock()
        
        self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        empty_count = 0
        while self.running:
            if not self.cap.isOpened():
                time.sleep(1)
                self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                continue

            ok, frame = self.cap.read()
            if ok:
                empty_count = 0
                with self.lock:
                    self.latest_frame = frame
            else:
                empty_count += 1
                if empty_count > 100: # 1 second without frames
                    self.cap.release()
                    empty_count = 0
                time.sleep(0.01)

    def read(self):
        with self.lock:
            if self.latest_frame is not None:
                return True, self.latest_frame.copy()
            return False, None

    def isOpened(self):
        return True # Always pretend opened so main loop doesn't crash, we reconnect in bg

    def release(self):
        self.running = False
        if self.cap: self.cap.release()
