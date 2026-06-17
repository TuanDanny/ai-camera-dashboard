import time
import json
import random
import threading
import argparse
import base64
import paho.mqtt.client as mqtt

# --- Configuration ---
BROKER = "localhost"
PORT = 1883
USER = "edge_device"
PASSWORD = "MqttEdge2026!"

class EdgeSimulator:
    def __init__(self, station_id):
        self.station_id = station_id
        self.client = mqtt.Client(client_id=f"sim_{station_id}")
        self.client.username_pw_set(USER, PASSWORD)
        
        # Last Will & Testament (LWT)
        lwt_topic = f"traffic/station/{self.station_id}/heartbeat"
        lwt_payload = json.dumps({
            "station_id": self.station_id,
            "timestamp": 0,
            "status": "offline_unexpected"
        })
        self.client.will_set(lwt_topic, payload=lwt_payload, qos=1, retain=True)

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        # Config state
        self.telemetry_interval = 60
        self.heartbeat_interval = 30
        self.seq = 0
        self.running = False

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"[{self.station_id}] Connected to MQTT Broker")
            self.client.subscribe(f"traffic/station/{self.station_id}/command")
            self.client.subscribe(f"traffic/station/{self.station_id}/config")
            self.client.subscribe("traffic/station/broadcast/command")
        else:
            print(f"[{self.station_id}] Failed to connect, return code {rc}")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            print(f"[{self.station_id}] Received on {msg.topic}: {payload}")
            
            if "command" in msg.topic:
                if payload.get("command") == "set_interval":
                    new_interval = payload.get("params", {}).get("interval_seconds", 60)
                    self.telemetry_interval = new_interval
                    print(f"[{self.station_id}] Changed telemetry interval to {new_interval}s")
                elif payload.get("command") == "capture_snapshot":
                    self.send_snapshot()
        except Exception as e:
            print(f"[{self.station_id}] Error parsing message: {e}")

    def send_telemetry(self):
        self.seq += 1
        
        motorbike = random.randint(5, 50)
        car = random.randint(1, 10)
        truck = random.randint(0, 3)
        bus = random.randint(0, 2)
        bicycle = random.randint(0, 5)
        unknown = 0
        total = motorbike + car + truck + bus + bicycle + unknown
        
        payload = {
            "v": 1,
            "station_id": self.station_id,
            "timestamp": int(time.time()),
            "seq": self.seq,
            "interval_seconds": self.telemetry_interval,
            "data": {
                "vehicles": {
                    "motorbike": motorbike,
                    "car": car,
                    "truck": truck,
                    "bus": bus,
                    "bicycle": bicycle,
                    "unknown": unknown
                },
                "total": total,
                "direction": {
                    "inbound": total // 2 + 1,
                    "outbound": total // 2
                },
                "avg_confidence": round(random.uniform(0.75, 0.95), 3),
                "min_confidence": round(random.uniform(0.5, 0.7), 3),
                "detections_raw": total * random.randint(2, 4),
                "detections_filtered": total,
                "lighting_condition": "day"
            },
            "status": {
                "cpu_temp_c": round(random.uniform(40, 60), 1),
                "enclosure_temp_c": round(random.uniform(35, 50), 1),
                "input_voltage_v": 12.1,
                "signal_rssi_dbm": random.randint(-85, -60),
                "signal_quality_pct": random.randint(60, 100),
                "free_memory_kb": 120000,
                "disk_usage_pct": 45,
                "fps": round(random.uniform(8.0, 12.0), 1),
                "inference_ms": random.randint(80, 150)
            }
        }
        self.client.publish(f"traffic/station/{self.station_id}/telemetry", json.dumps(payload), qos=1)
        print(f"[{self.station_id}] Sent telemetry seq {self.seq}")

    def send_heartbeat(self):
        payload = {
            "station_id": self.station_id,
            "timestamp": int(time.time()),
            "status": "active",
            "uptime_seconds": 3600,
            "hardware": {
                "cpu_temp_c": round(random.uniform(40, 60), 1),
                "enclosure_temp_c": round(random.uniform(35, 50), 1),
                "input_voltage_v": 12.1,
                "signal_rssi_dbm": random.randint(-85, -60),
                "signal_quality_pct": random.randint(60, 100),
                "free_memory_kb": 120000,
                "disk_usage_pct": 45,
                "fps": round(random.uniform(8.0, 12.0), 1),
                "inference_ms": random.randint(80, 150)
            },
            "watchdog": {
                "luckfox_ok": True,
                "esp32_ok": True
            },
            "camera_status": "ok",
            "last_reboot_reason": "power_on"
        }
        self.client.publish(f"traffic/station/{self.station_id}/heartbeat", json.dumps(payload), qos=1, retain=True)

    def send_network_quality(self):
        payload = {
            "station_id": self.station_id,
            "timestamp": int(time.time()),
            "network": {
                "operator": "Viettel",
                "technology": "4G",
                "band": "B3",
                "rssi_dbm": random.randint(-90, -60),
                "rsrp_dbm": random.randint(-110, -80),
                "rsrq_db": random.randint(-15, -3),
                "sinr_db": random.randint(5, 25),
                "latency_ms": random.randint(20, 150),
                "packet_loss_percent": round(random.uniform(0.0, 2.5), 2),
                "reconnect_count": random.randint(0, 5),
                "bytes_sent_total": random.randint(1000000, 5000000),
                "bytes_received_total": random.randint(500000, 2000000),
                "mqtt_reconnect_count": random.randint(0, 2)
            }
        }
        self.client.publish(f"traffic/station/{self.station_id}/network_quality", json.dumps(payload), qos=1)

    def send_alert(self):
        if random.random() < 0.05:
            payload = {
                "station_id": self.station_id,
                "timestamp": int(time.time()),
                "severity": "warning",
                "code": "TEMP_HIGH",
                "message": "Enclosure temperature exceeded 45C",
                "details": {
                    "current_temp": 47.5,
                    "threshold": 45.0
                }
            }
            self.client.publish(f"traffic/station/{self.station_id}/alert", json.dumps(payload), qos=1)
            print(f"[{self.station_id}] Sent ALERT")

    def send_watchdog(self):
        if random.random() < 0.02:
            payload = {
                "station_id": self.station_id,
                "timestamp": int(time.time()),
                "event": "soft_reset",
                "details": {
                    "reason": "camera_timeout",
                    "description": "No frames from MIPI for 10s",
                    "uptime_before_reset_s": 86400,
                    "reset_count_since_boot": 1
                }
            }
            self.client.publish(f"traffic/station/{self.station_id}/watchdog", json.dumps(payload), qos=1)
            print(f"[{self.station_id}] Sent WATCHDOG")

    def send_snapshot(self):
        dummy_base64 = base64.b64encode(b"dummy_image_data").decode('utf-8')
        payload = {
            "station_id": self.station_id,
            "timestamp": int(time.time()),
            "format": "jpeg",
            "resolution": "640x480",
            "size_bytes": len(dummy_base64),
            "lighting_condition": "day",
            "image_base64": dummy_base64
        }
        self.client.publish(f"traffic/station/{self.station_id}/snapshot", json.dumps(payload), qos=1)
        print(f"[{self.station_id}] Sent snapshot")

    def telemetry_loop(self):
        while self.running:
            self.send_telemetry()
            time.sleep(self.telemetry_interval)

    def heartbeat_loop(self):
        while self.running:
            self.send_heartbeat()
            time.sleep(self.heartbeat_interval)

    def diagnostics_loop(self):
        while self.running:
            self.send_network_quality()
            self.send_alert()
            self.send_watchdog()
            time.sleep(self.heartbeat_interval * 2) # Every 60s

    def start(self):
        self.client.connect(BROKER, PORT, 60)
        self.client.loop_start()
        self.running = True
        
        threading.Thread(target=self.telemetry_loop, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        threading.Thread(target=self.diagnostics_loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.client.disconnect()
        self.client.loop_stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", type=int, default=1, help="Number of stations to simulate")
    parser.add_argument("--interval", type=int, default=60, help="Telemetry interval in seconds")
    parser.add_argument("--broker", type=str, default="localhost", help="MQTT broker address")
    args = parser.parse_args()

    BROKER = args.broker

    simulators = []
    try:
        for i in range(1, args.stations + 1):
            station_id = f"ST-{i:03d}"
            sim = EdgeSimulator(station_id)
            sim.telemetry_interval = args.interval
            sim.start()
            simulators.append(sim)
        
        print(f"Started {args.stations} simulators. Press Ctrl+C to exit.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping simulators...")
        for sim in simulators:
            sim.stop()
