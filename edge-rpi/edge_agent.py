import os
import sys
import time
import json
import socket
import subprocess
import threading
import yaml
import paho.mqtt.client as mqtt

# Try importing psutil, fallback to dummy values if not installed
try:
    import psutil
except ImportError:
    psutil = None

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    config = yaml.safe_load(f)

STATION_ID = config['station_id']
MQTT_HOST = config['server']['host']
MQTT_PORT = config['server']['mqtt_port']
MQTT_USER = config['mqtt']['username']
MQTT_PASS = config['mqtt']['password']
HEARTBEAT_INTERVAL = config['heartbeat']['interval_s']

ALERTS_CFG = config.get('alerts', {})
CPU_TEMP_WARN_C = ALERTS_CFG.get('cpu_temp_warn_c', 65)
CPU_TEMP_CRIT_C = ALERTS_CFG.get('cpu_temp_crit_c', 80)
DISK_USAGE_WARN_PCT = ALERTS_CFG.get('disk_usage_warn_pct', 90)
DISK_USAGE_CRIT_PCT = ALERTS_CFG.get('disk_usage_crit_pct', 97)

# MQTT Topics
TOPIC_HEARTBEAT = f"traffic/station/{STATION_ID}/heartbeat"
TOPIC_COMMAND = f"traffic/station/{STATION_ID}/command"
TOPIC_ALERT = f"traffic/station/{STATION_ID}/alert"
TOPIC_NETWORK_QUALITY = f"traffic/station/{STATION_ID}/network_quality"

# Global stream process reference
stream_process = None
stream_lock = threading.Lock()

# Tracks MQTT reconnects for the network_quality report (reset each process start)
_has_connected_once = False
mqtt_reconnect_count = 0

# Tracks current level per metric so we only alert on a state CHANGE
# (crossing into warning/critical, or recovering back to normal) instead of
# spamming an alert every single heartbeat while a condition persists.
_alert_levels = {"cpu_temp": "normal", "disk_usage": "normal"}

def get_cpu_temp():
    # Attempt to read Raspberry Pi CPU temperature
    try:
        if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return float(f.read().strip()) / 1000.0
    except Exception:
        pass
    return 45.0  # Dummy fallback for simulation/Windows

def get_hardware_stats(signal_rssi_dbm=None, signal_quality_pct=None):
    stats = {
        "cpu_temp_c": get_cpu_temp(),
        "enclosure_temp_c": None,       # no separate enclosure sensor on this hardware
        "free_memory_kb": 1024 * 1024, # default dummy
        "disk_usage_pct": 10,           # default dummy
        "input_voltage_v": 5.1,
        "signal_rssi_dbm": signal_rssi_dbm,
        "signal_quality_pct": signal_quality_pct,
        "fps": None,                    # populated separately by ai-worker's own telemetry row
        "inference_ms": None
    }

    if psutil:
        try:
            mem = psutil.virtual_memory()
            stats["free_memory_kb"] = mem.available // 1024

            disk = psutil.disk_usage('/')
            stats["disk_usage_pct"] = int(disk.percent)
        except Exception as e:
            print(f"Error reading psutil stats: {e}")

    return stats

def get_network_stats():
    # Simple latency ping to server
    latency = 10
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        start = time.time()
        s.connect((MQTT_HOST, MQTT_PORT))
        latency = int((time.time() - start) * 1000)
        s.close()
    except Exception:
        latency = -1

    bytes_sent_total = 0
    bytes_received_total = 0
    if psutil:
        try:
            counters = psutil.net_io_counters()
            bytes_sent_total = counters.bytes_sent
            bytes_received_total = counters.bytes_recv
        except Exception:
            pass

    return {
        # This station connects over WiFi, not a cellular modem, so the
        # operator/cell-tower fields below don't apply and are left null.
        "operator": "WiFi",
        "technology": "wifi",
        "band": None,
        "rssi_dbm": -65 if latency >= 0 else -100,
        "rsrp_dbm": None,
        "rsrq_db": None,
        "sinr_db": None,
        "latency_ms": latency,
        "packet_loss_percent": 0.0 if latency >= 0 else 100.0,
        "reconnect_count": 0,
        "bytes_sent_total": bytes_sent_total,
        "bytes_received_total": bytes_received_total,
        "mqtt_reconnect_count": mqtt_reconnect_count
    }

def start_video_stream():
    global stream_process
    with stream_lock:
        if stream_process and stream_process.poll() is None:
            print("[INFO] Stream is already running.")
            return True
            
        script_path = os.path.join(os.path.dirname(__file__), 'start_stream.sh')
        
        # Check if start_stream.sh exists, otherwise create it or use fallback command
        if not os.path.exists(script_path):
            # Create a mock video stream script if it doesn't exist
            print("[INFO] start_stream.sh not found. Creating a mock streaming script.")
            # On Windows, we'll run a dummy process or ffmpeg command if present.
            # But we write a generic start_stream.sh for Pi.
            pass
            
        print(f"[INFO] Starting video stream from: {script_path}")
        try:
            if os.name == 'nt':
                # Windows fallback stream command using ffmpeg (fake stream from test source)
                # This will publish a test pattern to RTSP if ffmpeg is installed
                cmd = ["ffmpeg", "-re", "-f", "lavfi", "-i", "testsrc=size=640x480:rate=25", "-vcodec", "libx264", "-pix_fmt", "yuv420p", "-f", "rtsp", config['stream']['url']]
                # If ffmpeg isn't on path, it might fail, so we catch it
                stream_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                stream_process = subprocess.Popen(["bash", script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to start stream process: {e}")
            return False

def stop_video_stream():
    global stream_process
    with stream_lock:
        if stream_process:
            print("[INFO] Stopping stream process...")
            stream_process.terminate()
            try:
                stream_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                stream_process.kill()
            stream_process = None
            print("[INFO] Stream stopped.")
            return True
        return False

def publish_alert(client, severity, code, message, details=None):
    payload = {
        "station_id": STATION_ID,
        "timestamp": int(time.time()),
        "severity": severity,
        "code": code,
        "message": message,
        "details": details or {}
    }
    client.publish(TOPIC_ALERT, json.dumps(payload), qos=1)

def check_threshold_alert(client, metric_key, label, value, warn, crit, unit):
    global _alert_levels
    if value >= crit:
        new_level = "critical"
    elif value >= warn:
        new_level = "warning"
    else:
        new_level = "normal"

    old_level = _alert_levels[metric_key]
    if new_level == old_level:
        return
    _alert_levels[metric_key] = new_level

    if new_level == "normal":
        publish_alert(client, "info", f"{metric_key}_normal",
                      f"{label} da tro lai binh thuong ({value:.1f}{unit}).", {"value": value})
    else:
        publish_alert(client, new_level, f"{metric_key}_{new_level}",
                      f"{label} dang o muc {new_level}: {value:.1f}{unit}.", {"value": value})

def on_connect(client, userdata, flags, rc):
    global _has_connected_once, mqtt_reconnect_count
    if rc == 0:
        if _has_connected_once:
            mqtt_reconnect_count += 1
        _has_connected_once = True
        print("[INFO] Connected to MQTT Broker successfully.")
        client.subscribe(TOPIC_COMMAND, qos=1)
        print(f"[INFO] Subscribed to topic: {TOPIC_COMMAND}")
    else:
        print(f"[ERROR] Failed to connect to MQTT Broker, return code {rc}")

def on_message(client, userdata, msg):
    print(f"[INFO] Received command on topic {msg.topic}: {msg.payload.decode()}")
    try:
        data = json.loads(msg.payload.decode())
        command = data.get("command")
        
        if command == "restart_stream":
            stop_video_stream()
            time.sleep(1)
            started = start_video_stream()
            # Send alert/ack
            ack_msg = {
                "station_id": STATION_ID,
                "timestamp": int(time.time()),
                "severity": "info",
                "code": "stream_restarted",
                "message": "Stream has been successfully restarted via remote command",
                "details": {"success": started}
            }
            client.publish(TOPIC_ALERT, json.dumps(ack_msg), qos=1)
            
        elif command == "reboot_device":
            print("[WARN] Reboot command received! Executing reboot in 3 seconds...")
            # Send alert first
            ack_msg = {
                "station_id": STATION_ID,
                "timestamp": int(time.time()),
                "severity": "warning",
                "code": "device_rebooting",
                "message": "Device is executing a reboot command from server",
                "details": {}
            }
            client.publish(TOPIC_ALERT, json.dumps(ack_msg), qos=1)
            time.sleep(3)
            if os.name != 'nt':
                os.system("sudo reboot")
            else:
                print("[SIMULATION] Rebooting system (ignored on Windows)")
                
    except Exception as e:
        print(f"[ERROR] Error processing command: {e}")

def main():
    client = mqtt.Client(client_id=f"rpi_agent_{STATION_ID}")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_HOST, int(MQTT_PORT), keepalive=60)
    except Exception as e:
        print(f"[ERROR] Could not connect to MQTT Broker at {MQTT_HOST}:{MQTT_PORT}: {e}")
        sys.exit(1)
        
    client.loop_start()
    
    # Auto start stream on boot
    start_video_stream()
    
    print(f"[INFO] Edge Agent running for station {STATION_ID}. Press Ctrl+C to stop.")
    
    try:
        uptime_start = time.time()
        while True:
            # Check stream health. Read-only under the lock - start_video_stream()
            # takes the same (non-reentrant) lock itself, so it must be called
            # AFTER releasing this one, or the thread deadlocks on itself the
            # first time a restart is actually needed.
            stream_ok = "ok"
            needs_restart = False
            with stream_lock:
                if stream_process:
                    status = stream_process.poll()
                    if status is not None:
                        # Process exited
                        stream_ok = "error"
                        needs_restart = True
                else:
                    # Never started, or a previous restart attempt itself
                    # failed - keep retrying instead of staying offline forever.
                    stream_ok = "offline"
                    needs_restart = True

            if needs_restart:
                print(f"[WARN] Stream is not running (status: {stream_ok}). Attempting restart...")
                start_video_stream()
            
            # Network stats are computed once per cycle and reused for both
            # the network_quality report and the signal fields in heartbeat.
            network_stats = get_network_stats()
            hardware_stats = get_hardware_stats(
                signal_rssi_dbm=network_stats["rssi_dbm"],
                signal_quality_pct=100 if network_stats["latency_ms"] >= 0 else 0
            )

            check_threshold_alert(client, "cpu_temp", "Nhiet do CPU", hardware_stats["cpu_temp_c"],
                                  CPU_TEMP_WARN_C, CPU_TEMP_CRIT_C, "C")
            check_threshold_alert(client, "disk_usage", "Dung luong dia", hardware_stats["disk_usage_pct"],
                                  DISK_USAGE_WARN_PCT, DISK_USAGE_CRIT_PCT, "%")

            # Prepare heartbeat payload
            heartbeat = {
                "station_id": STATION_ID,
                "timestamp": int(time.time()),
                "status": "active",
                "uptime_seconds": int(time.time() - uptime_start),
                "stream_url": config['stream']['url'],
                "hardware": hardware_stats,
                # No physical watchdog MCU on this hardware yet - report OK
                # as a placeholder rather than omitting the field, since
                # Node-RED's heartbeat handler requires it to be present.
                "watchdog": {"luckfox_ok": True, "esp32_ok": True},
                "camera_status": "ok",
                "stream_status": stream_ok,
                "last_reboot_reason": "power_on"
            }

            # Publish heartbeat
            client.publish(TOPIC_HEARTBEAT, json.dumps(heartbeat), qos=1)
            print(f"[Heartbeat] Sent status. Stream: {stream_ok}")

            # Publish network quality on its own topic - Node-RED subscribes
            # to traffic/station/+/network_quality separately from heartbeat.
            network_payload = {
                "station_id": STATION_ID,
                "timestamp": int(time.time()),
                "network": network_stats
            }
            client.publish(TOPIC_NETWORK_QUALITY, json.dumps(network_payload), qos=1)

            time.sleep(HEARTBEAT_INTERVAL)
            
    except KeyboardInterrupt:
        print("\nStopping agent...")
    finally:
        stop_video_stream()
        client.loop_stop()
        client.disconnect()
        print("[INFO] Agent stopped cleanly.")

if __name__ == "__main__":
    main()
