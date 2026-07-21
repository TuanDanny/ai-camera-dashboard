"""Helper dung chung, thao tac truc tiep len he thong that (process host-
level, Docker, he dieu hanh) - dung boi ca lenh doc-trang-thai (status/
check) lan lenh nguy hiem (restartyolo/restartmqtt/reboot/cleardb).

Tat ca ham o day la SYNC (goi subprocess/psycopg2 chan luong) - command
handler (async) phai goi qua asyncio.to_thread(...).
"""
import shutil
import socket
import subprocess
import urllib.request

from tg_bot import config, db

AI_WORKER_VENV = f"{config.REPO_ROOT}/ai-worker/.venv/bin/python3"

# Pattern nhan dien tien trinh host-level, dung chung logic voi run.sh
# (anchor "$" o cuoi de chi khop dong lenh THAT SU ket thuc bang ten file
# nay, tranh nham voi process khac chi tinh co chua chuoi do giua dong).
_PROC_PATTERNS = {
    "edge_agent": r"\.venv/bin/python3 -u edge_agent\.py$",
    "yolo": r"\.venv/bin/python3 -u main\.py$",
}

# Cac container Docker (docker-compose.yml) - dung cho lenh status/check.
DOCKER_CONTAINERS = [
    "shtp-mosquitto",
    "shtp-postgres",
    "shtp-nodered",
    "shtp-grafana",
    "shtp-mediamtx",
    "shtp-mqttx-web",
]


def _pgrep(pattern: str) -> list[int]:
    result = subprocess.run(
        ["pgrep", "-f", pattern], capture_output=True, text=True
    )
    return [int(pid) for pid in result.stdout.split()]


def is_process_alive(name: str) -> bool:
    return len(_pgrep(_PROC_PATTERNS[name])) > 0


def docker_container_status(name: str) -> str:
    """Tra ve 'running'/'exited'/'not found' - dung 'docker inspect' thay vi
    parse chuoi tu 'docker ps' cho chac chan."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}}", name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "not found"
    return result.stdout.strip()


def restart_yolo() -> str:
    """Restart main.py (tien trinh AI-worker/YOLO). Kill tien trinh cu (neu
    co) roi mo lai bang dung lenh nohup nhu run.sh dang lam, ghi log vao
    cung file ai_worker.log."""
    pids = _pgrep(_PROC_PATTERNS["yolo"])
    for pid in pids:
        subprocess.run(["kill", "-9", str(pid)])

    log_path = f"{config.REPO_ROOT}/ai-worker/ai_worker.log"
    subprocess.Popen(
        f"cd '{config.REPO_ROOT}/ai-worker' && "
        f"nohup '{AI_WORKER_VENV}' -u main.py > '{log_path}' 2>&1 &",
        shell=True,
    )
    return f"Da restart main.py (kill {len(pids)} tien trinh cu, mo lai moi)."


def restart_mqtt() -> str:
    """Restart container Mosquitto qua docker compose (giu nguyen volume/
    config, chi restart tien trinh ben trong container)."""
    result = subprocess.run(
        ["docker", "compose", "restart", "mosquitto"],
        cwd=config.REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"Loi restart mosquitto:\n{result.stderr}"
    return "Da restart container mosquitto."


def reboot_system() -> str:
    """Reboot toan bo may that (Raspberry Pi). Yeu cau user chay tg_bot da
    duoc cau hinh sudo reboot khong can nhap password (visudo: NOPASSWD)."""
    subprocess.Popen(["sudo", "reboot"])
    return "Da gui lenh reboot - may se tat trong vai giay."


def check_postgres() -> bool:
    """Kiem tra Postgres THAT SU tra loi duoc query, khong chi container
    'running' (container co the len nhung DB ben trong dang treo)."""
    try:
        db.fetch_one("SELECT 1;")
        return True
    except Exception:
        return False


def check_mqtt_port() -> bool:
    try:
        with socket.create_connection(
            (config.MQTT_HOST, config.MQTT_PORT), timeout=3
        ):
            return True
    except OSError:
        return False


def check_mjpeg_snapshot() -> bool:
    """Goi thu endpoint /snapshot cua ai-worker - neu tra ve duoc nghia la
    main.py con song VA dang co frame camera that (khong chi tien trinh
    con chay nhung camera bi treo/mat tin hieu)."""
    try:
        with urllib.request.urlopen(config.MJPEG_SNAPSHOT_URL, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def disk_usage_pct() -> float:
    total, used, _free = shutil.disk_usage(config.REPO_ROOT)
    return round(used / total * 100, 1)


def clear_traffic_data() -> str:
    """Xoa sach du lieu xe da detect (bang traffic_records) - GIU NGUYEN
    stations/hardware_metrics/... Cung logic voi scripts/reset_traffic.sh,
    dung ham dung chung trong db.py de tranh trung 2 noi."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE traffic_records RESTART IDENTITY;")
        conn.commit()
    return "Da xoa sach traffic_records (giu nguyen danh sach station)."
