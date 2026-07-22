"""
Kiem chung Phase 5: import THAT main.py, gia lap YOLO/MQTT/cv2 de dieu khien
chinh xac kich ban loi (stream ket thuc em dep khong exception - dung nguyen
nhan gay UnboundLocalError truoc day), xem process_stream() co con crash
hay khong va co thu lai (retry) dung nhu thiet ke moi khong.
"""
import os
import sys
import types
import time

AI_WORKER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AI_WORKER_DIR)

# ---- Stub cv2 ----
cv2_stub = types.ModuleType("cv2")
cv2_stub.cuda = types.SimpleNamespace(getCudaEnabledDeviceCount=lambda: 0)
sys.modules["cv2"] = cv2_stub

# ---- Stub paho.mqtt.client ----
paho_mod = types.ModuleType("paho")
paho_mqtt_mod = types.ModuleType("paho.mqtt")
paho_mqtt_client_mod = types.ModuleType("paho.mqtt.client")


class FakeMQTTClient:
    def __init__(self, client_id=""):
        self.client_id = client_id
        self.on_connect = None

    def username_pw_set(self, user, pw):
        pass

    def connect(self, host, port, keepalive):
        print(f"[fake mqtt] connect({host}, {port}) - gia vo thanh cong, khong that su goi mang")

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def publish(self, topic, payload, qos=0):
        print(f"[fake mqtt] publish -> topic={topic}")


paho_mqtt_client_mod.Client = FakeMQTTClient
sys.modules["paho"] = paho_mod
sys.modules["paho.mqtt"] = paho_mqtt_mod
sys.modules["paho.mqtt.client"] = paho_mqtt_client_mod

# ---- Stub ultralytics.YOLO ----
ultralytics_mod = types.ModuleType("ultralytics")

attempt_counter = {"n": 0}


class FakeYOLO:
    def __init__(self, model_path):
        print(f"[fake yolo] loaded model_path={model_path}")

    def predict(self, **kwargs):
        attempt_counter["n"] += 1
        n = attempt_counter["n"]
        print(f"[fake yolo] predict() called - day la lan goi thu {n}")

        if n == 1:
            raise RuntimeError("gia lap loi tam thoi (vd: RTSP glitch)")

        # Tu lan thu 2 tro di: gia lap stream ket thuc em dep, KHONG nem
        # exception gi ca - day chinh la kich ban gay UnboundLocalError
        # truoc day (HAS_YOLO_FALLBACK khong bao gio duoc gan).
        return iter([])


ultralytics_mod.YOLO = FakeYOLO
sys.modules["ultralytics"] = ultralytics_mod

# ---- Gio moi import main.py THAT ----
import main  # noqa: E402

print("\n=== import main.py THANH CONG (khong bi UnboundLocalError khi dinh nghia module) ===\n")

print("=== Goi process_stream() that, quan sat trong ~35 giay ===\n")
main.process_stream({
    "station_id": "TEST-RETRY",
    "url": "dummy-url-khong-quan-trong-vi-da-fake-yolo",
    "location_name": "Test Phase 5",
})
