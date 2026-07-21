"""Lenh /check - kiem tra SAU hon /status: khong chi container 'running'
ma con thu KET NOI THAT (Postgres tra loi duoc query, MQTT mo dc socket,
main.py co frame camera that qua /snapshot), them dung luong dia con
trong."""
import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from tg_bot import system


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    postgres_ok, mqtt_ok, camera_ok, disk_pct = await asyncio.gather(
        asyncio.to_thread(system.check_postgres),
        asyncio.to_thread(system.check_mqtt_port),
        asyncio.to_thread(system.check_mjpeg_snapshot),
        asyncio.to_thread(system.disk_usage_pct),
    )

    def mark(ok: bool) -> str:
        return "OK" if ok else "LOI"

    lines = [
        "Kiem tra sau tat ca dich vu:",
        "",
        f"- Postgres (query that): {mark(postgres_ok)}",
        f"- MQTT broker (port {system.config.MQTT_PORT}): {mark(mqtt_ok)}",
        f"- Camera/YOLO (frame that qua /snapshot): {mark(camera_ok)}",
        f"- Dung luong dia da dung: {disk_pct}%",
    ]

    await update.effective_message.reply_text("\n".join(lines))
