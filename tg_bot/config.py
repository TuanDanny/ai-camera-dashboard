"""Doc cau hinh tu file .env o goc repo (dung chung voi docker-compose,
ai-worker, edge-rpi) - tg_bot chay truc tiep tren host (khong qua Docker,
vi lenh reboot/restartyolo/restartmqtt can dieu khien he thong that/
docker tu BEN NGOAI container), nen tu doc .env bang python-dotenv thay vi
duoc docker-compose truyen bien moi truong san."""
import os

from dotenv import load_dotenv

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Danh sach user_id (int) duoc phep goi lenh nguy hiem - de trong trong
# .env = KHONG ai duoc phep (an toan mac dinh, khong ngam dinh "cho phep
# het" khi thieu cau hinh).
_raw_allowed = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = {
    int(uid.strip()) for uid in _raw_allowed.split(",") if uid.strip()
}

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ["POSTGRES_DB"]
POSTGRES_USER = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

# URL MJPEG snapshot cua ai-worker (frame_broadcast.py) - dung cho lenh
# view/snapshot. Chi 1 station duy nhat dang duoc broadcast (xem
# ai-worker/main.py), khop dung gioi han hien tai cua frame_broadcast.py.
MJPEG_SNAPSHOT_URL = os.environ.get(
    "TG_BOT_MJPEG_SNAPSHOT_URL", "http://localhost:8090/snapshot"
)

# Chi 1 station duy nhat dang trien khai thuc te (xem ai-worker/config.yaml
# streams[0].station_id) - dung cho cac lenh traffic/report/history de khoi
# phai bat nguoi dung go them station_id moi lan goi lenh.
DEFAULT_STATION_ID = os.environ.get("TG_BOT_DEFAULT_STATION_ID", "ST-001")

REPO_ROOT = _ROOT_DIR

# Dung cho lenh /version - tang tay moi khi doi logic cac lenh dang ke.
BOT_VERSION = "1.0.0"
