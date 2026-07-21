"""Lenh /help - liet ke toan bo lenh dang co, kem phan biet lenh thuong
va lenh nguy hiem (can quyen + xac nhan)."""
from telegram import Update
from telegram.ext import ContextTypes

# Danh sach nay cung duoc bot.py dung de dang ky menu lenh (setMyCommands)
# - sua o day la du, khong can sua 2 noi.
READONLY_COMMANDS = [
    ("help", "Xem menu tro giup nay"),
    ("panel", "Mo bang dieu khien nhanh (nut bam)"),
    ("status", "Xem nhanh trang thai he thong"),
    ("check", "Kiem tra sau tat ca dich vu (Postgres/MQTT/camera/disk)"),
    ("view", "Xem anh camera hien tai"),
    ("snapshot", "Chup va gui anh hien tai (file goc)"),
    ("traffic", "Thong ke luu luong xe 1 gio gan nhat"),
    ("report", "Bao cao luu luong xe hom nay so voi hom qua"),
    ("history", "Xem lich su canh bao/watchdog gan day"),
    ("version", "Xem phien ban bot dang chay"),
]

DANGEROUS_COMMANDS = [
    ("restartyolo", "Restart tien trinh AI-worker (main.py)"),
    ("restartmqtt", "Restart container Mosquitto (MQTT)"),
    ("reboot", "Reboot toan bo Raspberry Pi"),
    ("cleardb", "Xoa sach du lieu xe da detect (traffic_records)"),
]


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["SHTP Traffic Bot - Danh sach lenh", ""]
    for name, desc in READONLY_COMMANDS:
        lines.append(f"/{name} - {desc}")

    lines.append("")
    lines.append("Lenh nguy hiem (can duoc cap quyen + xac nhan Yes/No):")
    for name, desc in DANGEROUS_COMMANDS:
        lines.append(f"/{name} - {desc}")

    await update.effective_message.reply_text("\n".join(lines))
