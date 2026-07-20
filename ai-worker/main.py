import gc
import os
import sys
import time
import json
import threading
from collections import Counter
import yaml
import paho.mqtt.client as mqtt

# Da dieu tra thuc te (py-spy, xem npu_plan.md): moi lan Thread-3
# (process_stream, tieu thu) chay cum publish MQTT dinh ky (json.dumps +
# client.publish), Thread-4 (producer, do FPS NPU) bi dip nhe ngay sau do
# (2/2 lan bat duoc deu dip) - dau hieu tranh chap GIL. Mac dinh CPython
# nhuong GIL cho thread khac moi 5ms (sys.getswitchinterval()) - giam
# xuong 1ms de producer lay lai GIL nhanh hon khi bi giu, giam do tre toi
# da phai cho. Khong doi kien truc/thread nao, rui ro thap.
sys.setswitchinterval(0.001)

from direction_counter import DirectionCounter
from pipeline.frame_source import cpu_frame_source
from pipeline.frame_broadcast import FrameBroadcaster

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

MQTT_HOST = config['server']['mqtt_host']
MQTT_PORT = config['server']['mqtt_port']
MQTT_USER = config['server']['mqtt_username']
MQTT_PASS = config['server']['mqtt_password']
PUBLISH_INTERVAL = config['publish']['interval_s']
# Vehicle counting keeps its own longer window (PUBLISH_INTERVAL) so a slow
# or stopped vehicle isn't recounted every few seconds - this separate,
# faster pulse is only for fps/inference_ms, which have no such window
# dependency and are safe to report as often as we like.
STATUS_INTERVAL = config['publish'].get('status_interval_s', 3)
STATUS_TOPIC_TEMPLATE = config['publish'].get('status_topic_template', 'traffic/station/{station_id}/ai_status')
ALERT_TOPIC_TEMPLATE = config['publish'].get('alert_topic_template', 'traffic/station/{station_id}/alert')
MODEL_PATH = config['model']['path']
CONF_THRESH = config['model']['conf']
IMGSZ = config['model']['imgsz']
IOU_THRESH = config['model']['iou']
MAX_DET = config['model']['max_det']
TARGET_CLASSES = config['model']['classes']

MODEL_BACKEND = config['model'].get('backend', 'cpu')
HAILO_HEF_PATH = config['model'].get('hailo_hef_path', 'auto')

# Import "tre" (chi khi thuc su can) - may chi chay backend cpu khong bat
# buoc phai cai duoc hailo_platform/picamera2 (thu vien dac thu phan cung,
# chi cai qua apt, khong co tren PyPI).
HAS_HAILO = False
if MODEL_BACKEND == 'hailo':
    try:
        from pipeline.hailo_source import create_hailo, DEFAULT_HEF_PATH as _HAILO_DEFAULT_HEF
        from pipeline.hailo_frame_source import hailo_frame_source
        HAS_HAILO = True
    except ImportError as e:
        print(f"[WARN] model.backend=hailo nhung khong import duoc thu vien Hailo: {e}")

DEFAULT_Y_RATIO = config['direction']['default_y_ratio']

# Mapping COCO class indices to SHTP vehicle categories
# 0: person, 1: bicycle, 2: car, 3: motorcycle (motorbike), 5: bus, 7: truck
COCO_MAP = {
    3: "motorbike",
    2: "car",
    7: "truck",
    5: "bus",
    1: "bicycle"
}

# MQTT Client Setup
client = mqtt.Client(client_id="ai_worker_gpu")
client.username_pw_set(MQTT_USER, MQTT_PASS)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[INFO] AI Worker connected to MQTT Broker successfully.")
    else:
        print(f"[ERROR] Connection failed with code {rc}")

client.on_connect = on_connect

def publish_alert(station_id, severity, code, message, details=None):
    alert_topic = ALERT_TOPIC_TEMPLATE.format(station_id=station_id)
    payload = {
        "station_id": station_id,
        "timestamp": int(time.time()),
        "severity": severity,
        "code": code,
        "message": message,
        "details": details or {}
    }
    client.publish(alert_topic, json.dumps(payload), qos=1)

# Connect to MQTT
try:
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"[ERROR] Could not connect to MQTT Broker: {e}")
    sys.exit(1)

# AI Processing per stream
def process_stream(stream_info, hailo_instance=None, broadcaster=None):
    station_id = stream_info['station_id']
    url = stream_info['url']
    location = stream_info['location_name']
    topic = config['publish']['topic_template'].format(station_id=station_id)
    status_topic = STATUS_TOPIC_TEMPLATE.format(station_id=station_id)

    print(f"[INFO] Starting AI Worker Thread for {station_id} ({location}) -> Stream: {url}")

    # Dem theo kieu "cat qua vach" - chi +1 dung 1 lan/o vi tri khi
    # DirectionCounter bao co cat qua vach, KHONG BAO GIO dem lai cho toi
    # khi vat the roi khoi dai quanh vach (xem direction_counter.py). Da bo
    # tracking (ByteTrack)/track_id hoan toan - chi con dung YOLO tho +
    # vach do de dem, don gian toi da theo yeu cau.
    interval_category_counts = Counter()

    direction_cfg = stream_info.get('direction_line', {})
    y_ratio = direction_cfg.get('y_ratio', DEFAULT_Y_RATIO)
    direction_counter = DirectionCounter(y_ratio)

    frame_index = 0
    interval_confidences = []
    detections_raw_count = 0

    interval_start = time.time()
    status_interval_start = time.time()
    seq = 0

    def on_stream_down(attempt):
        publish_alert(station_id, "critical", "stream_offline",
                      f"Stream {station_id} mat ket noi sau {attempt} lan thu lai lien tiep.",
                      {"attempts": attempt})

    def on_stream_recovered():
        publish_alert(station_id, "info", "stream_recovered",
                      f"Stream {station_id} da ket noi lai binh thuong.")

    def on_frame_dropped(dropped_count):
        # Rot khung o day nghia la buffer NPU (buffer_size=4) day - CPU
        # (DirectionCounter/publish) khong theo kip NPU.
        # Chi log de theo doi thuc te (npu_plan.md muc 3.3), khong publish
        # alert MQTT vi 1-2 khung le te khong phai su co nghiem trong.
        print(f"[WARN] [{station_id}] Buffer NPU day, da rot {dropped_count} "
              f"khung tich luy - CPU co the dang cham hon NPU.")

    if MODEL_BACKEND == 'hailo':
        if not HAS_HAILO:
            raise RuntimeError(
                "model.backend=hailo nhung khong import duoc thu vien Hailo - "
                "kiem tra lai venv co duoc wiring file .pth toi "
                "/usr/lib/python3/dist-packages chua (xem README/WALKTHROUGH)."
            )
        source = hailo_frame_source(
            hailo_instance, url, TARGET_CLASSES, conf=CONF_THRESH,
            buffer_size=4,
            on_stream_down=on_stream_down, on_stream_recovered=on_stream_recovered,
            on_frame_dropped=on_frame_dropped
        )
    else:
        source = cpu_frame_source(
            station_id, url, MODEL_PATH, CONF_THRESH, IMGSZ, IOU_THRESH,
            TARGET_CLASSES, MAX_DET,
            on_stream_down=on_stream_down, on_stream_recovered=on_stream_recovered
        )

    for frame, boxes, inference_ms, fps in source:
        frame_index += 1
        frame_height = frame.shape[0]

        # Phat lai khung + ket qua da xu ly qua socket cho view_stream.py
        # (neu co client dang xem) - KHONG chay YOLO lan 2 nua. publish()
        # cuc nhe (chi ghi de bien), khong lam cham vong lap NPU o day.
        # y_ratio dinh kem de ben nhan (frame_broadcast._draw_boxes_for_mjpeg)
        # ve dung vach do o dung vi tri dang dem xe qua.
        if broadcaster is not None:
            broadcaster.publish(station_id, frame, boxes, inference_ms, fps, y_ratio=y_ratio)

        any_crossing_this_frame = False
        for cls_id, confidence, x1, y1, x2, y2 in boxes:
            interval_confidences.append(confidence)
            detections_raw_count += 1

            centroid_x = (x1 + x2) / 2
            centroid_y = (y1 + y2) / 2
            crossing = direction_counter.update(centroid_x, centroid_y, frame_height, frame_index)

            # CHI dem xe dung luc thuc su cat qua vach - DirectionCounter tu
            # chong dem lai theo "o" vi tri (xem direction_counter.py), nen
            # 1 vat the dung yen/di cham qua vach van chi +1 DUNG 1 LAN cho
            # toi khi roi khoi dai quanh vach. Dung thang class_id ma model
            # dang bao O DUNG FRAME cat vach - khong con tracking/binh chon
            # nhieu frame nhu truoc.
            if crossing is not None:
                category = COCO_MAP.get(cls_id, "unknown")
                interval_category_counts[category] += 1
                any_crossing_this_frame = True

        direction_counter.end_frame(frame_index)

        now = time.time()

        # Fast, independent pulse for live fps/inference_ms - does
        # not touch tracked_ids/interval_* (those stay on
        # PUBLISH_INTERVAL so vehicle counting is unaffected).
        if now - status_interval_start >= STATUS_INTERVAL:
            status_payload = {
                "station_id": station_id,
                "timestamp": int(now),
                "fps": round(fps, 1),
                "inference_ms": inference_ms
            }
            client.publish(status_topic, json.dumps(status_payload), qos=0)
            status_interval_start = now

        # Gui ngay khi vua co xe cat qua vach (khong cho du PUBLISH_INTERVAL
        # nua) - dashboard cap nhat tuc thi thay vi tre toi da 10s. Van giu
        # nhip PUBLISH_INTERVAL cho luc KHONG co xe nao ca (gui du lieu
        # avg_confidence/detections_raw/lighting_condition dinh ky, tranh
        # dashboard "im lang" hoan toan luc duong vang xe).
        if any_crossing_this_frame or now - interval_start >= PUBLISH_INTERVAL:
            # Compile data - interval_category_counts chi tang luc THUC SU
            # cat qua vach (xem vong lap o tren), khong phai snapshot track
            # dang co trong khung.
            motorbike_cnt = interval_category_counts.get("motorbike", 0)
            car_cnt = interval_category_counts.get("car", 0)
            truck_cnt = interval_category_counts.get("truck", 0)
            bus_cnt = interval_category_counts.get("bus", 0)
            bicycle_cnt = interval_category_counts.get("bicycle", 0)
            unknown_cnt = interval_category_counts.get("unknown", 0)
            total_cnt = sum(interval_category_counts.values())

            avg_confidence = round(sum(interval_confidences) / len(interval_confidences), 2) if interval_confidences else 0.0
            min_confidence = round(min(interval_confidences), 2) if interval_confidences else 0.0

            payload = {
                "v": 1,
                "station_id": station_id,
                "timestamp": int(now),
                "seq": seq,
                "interval_seconds": PUBLISH_INTERVAL,
                "data": {
                    "vehicles": {
                        "motorbike": motorbike_cnt,
                        "car": car_cnt,
                        "truck": truck_cnt,
                        "bus": bus_cnt,
                        "bicycle": bicycle_cnt,
                        "unknown": unknown_cnt
                    },
                    "total": total_cnt,
                    # Khong con tracking (ByteTrack/track_id) nen khong con
                    # cach nao biet huong di chuyen THAT cua xe tai thoi
                    # diem cat vach - luon gui 0 (khong bo field de khoi
                    # phai sua schema Postgres/Node-RED/panel Grafana dang
                    # doc 2 cot nay, xem npu_plan.md).
                    "direction": {
                        "inbound": 0,
                        "outbound": 0
                    },
                    "avg_confidence": avg_confidence,
                    "min_confidence": min_confidence,
                    "detections_raw": detections_raw_count,
                    "detections_filtered": total_cnt,
                    "lighting_condition": "day" if 6 <= time.localtime().tm_hour < 18 else "night"
                },
                "status": {
                    "fps": round(fps, 1),
                    "inference_ms": inference_ms,
                    "stream_status": "ok"
                }
            }

            client.publish(topic, json.dumps(payload), qos=1)
            print(f"[{station_id}] Published AI Telemetry (Total: {total_cnt})")

            # Reset interval
            interval_category_counts = Counter()
            interval_confidences = []
            detections_raw_count = 0
            interval_start = now
            seq += 1

def main():
    # QUAN TRONG: moi Hailo() PHAI khoi tao tu CUNG 1 thread duy nhat (o day
    # la main thread) TRUOC khi mo thread rieng cho tung stream - da kiem
    # chung bang thu nghiem thuc te rang 2 OS thread khac nhau tu khoi tao
    # rieng se gay loi native "Resource deadlock avoided" du co khoa
    # (xem npu_plan.md muc 2.2b, pipeline/hailo_source.py). Thread xu ly
    # tung stream sau do CHI duoc goi .run() tren instance da co san.
    hailo_instances = {}
    if MODEL_BACKEND == 'hailo' and HAS_HAILO:
        hef_path = _HAILO_DEFAULT_HEF if HAILO_HEF_PATH == 'auto' else HAILO_HEF_PATH
        for stream in config['streams']:
            hailo_instances[stream['station_id']] = create_hailo(hef_path)

    # Chi 1 FrameBroadcaster duy nhat cho ca main.py (khong phai 1 cai/
    # stream) - view_stream.py cung chi xem dung 1 camera
    # (config['streams'][0]), nen chi station DAU TIEN moi phat qua
    # socket, khop dung hanh vi hien tai. Neu sau nay can xem duoc nhieu
    # camera thi phai thiet ke lai (xem npu_plan.md phan con mo).
    broadcaster = FrameBroadcaster()

    threads = []
    for i, stream in enumerate(config['streams']):
        hailo_instance = hailo_instances.get(stream['station_id'])
        stream_broadcaster = broadcaster if i == 0 else None
        t = threading.Thread(target=process_stream, args=(stream, hailo_instance, stream_broadcaster))
        t.daemon = True
        t.start()
        threads.append(t)

    # Da dieu tra thuc te (xem npu_plan.md): FPS NPU (do tuc thoi tung
    # frame, khong lam muot) thinh thoang rot khong deu (vd 45 -> 12-13fps)
    # ngay ca khi CPU dang o max freq (loai governor) VA khung hinh khong
    # co detection nao (loai workload dong xe) - dau hieu kinh dien cua GC
    # (Garbage Collector) chu ky day (gen-2) dung ca interpreter vai chuc ms
    # khong bao truoc. Doi vai giay de moi thread stream khoi tao xong cac
    # object "tinh" (detector/direction_counter...) roi "dong bang" toan
    # bo vao 1 generation vinh vien khong bi GC quet lai (gc.freeze()) -
    # giam han chi phi moi lan GC full phai duyet qua toan bo object nay.
    # Nang nguong GC (mac dinh 700,10,10) de giam han tan suat thu gom -
    # KHONG tat han (gc.disable()) vi tien trinh chay lien tuc nhieu ngay,
    # van can GC don dep reference cycle (vd closure trong producer thread)
    # de tranh ri bo nho dai han.
    time.sleep(2)
    gc.collect()
    gc.freeze()
    gc.set_threshold(50_000, 50, 50)
    print("[INFO] Da tune GC (freeze + nang nguong) de giam FPS rot do GC pause.")

    print("[INFO] AI Worker is running. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping AI Worker...")
        broadcaster.close()
        client.loop_stop()
        client.disconnect()
        print("[INFO] AI Worker stopped.")

if __name__ == "__main__":
    main()
