import os
import socket
import time

# Try importing psutil, fallback to dummy values if not installed
try:
    import psutil
    # psutil.cpu_percent() so sanh voi lan goi truoc do - lan goi DAU TIEN
    # trong doi tien trinh se so sanh voi luc tien trinh khoi dong (vo nghia,
    # thuong ra 0.0 hoac so bat thuong). Moi luc import mot lan de "vut bo"
    # ket qua vo nghia nay, cac lan goi sau trong vong lap heartbeat se tra
    # ve % thuc te tinh tu lan goi truoc.
    psutil.cpu_percent(percpu=True)
except ImportError:
    psutil = None


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
        "inference_ms": None,
        "cpu_count": 4,                 # Raspberry Pi 4 core - dummy fallback khi khong co psutil
        "cpu_core0_pct": None,
        "cpu_core1_pct": None,
        "cpu_core2_pct": None,
        "cpu_core3_pct": None,
    }

    if psutil:
        try:
            mem = psutil.virtual_memory()
            stats["free_memory_kb"] = mem.available // 1024

            disk = psutil.disk_usage('/')
            stats["disk_usage_pct"] = int(disk.percent)

            per_core = psutil.cpu_percent(percpu=True)
            stats["cpu_count"] = len(per_core)
            for i in range(4):
                stats[f"cpu_core{i}_pct"] = per_core[i] if i < len(per_core) else None
        except Exception as e:
            print(f"Error reading psutil stats: {e}")

    return stats


def get_network_stats(mqtt_host, mqtt_port, mqtt_reconnect_count):
    # Simple latency ping to server
    latency = 10
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        start = time.time()
        s.connect((mqtt_host, mqtt_port))
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
