"""Lenh /status - kiem tra NHANH: container Docker co dang 'running' khong,
tien trinh host (edge_agent.py/main.py) co dang song khong. Khong test
ket noi that su ben trong (xem lenh /check cho kiem tra sau hon)."""
import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from tg_bot import system


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    containers = await asyncio.to_thread(
        lambda: {
            name: system.docker_container_status(name)
            for name in system.DOCKER_CONTAINERS
        }
    )
    edge_alive = await asyncio.to_thread(system.is_process_alive, "edge_agent")
    yolo_alive = await asyncio.to_thread(system.is_process_alive, "yolo")

    lines = ["Trang thai he thong:", ""]
    for name, status in containers.items():
        mark = "OK" if status == "running" else f"LOI ({status})"
        lines.append(f"- {name}: {mark}")

    lines.append("")
    lines.append(f"- edge_agent.py: {'OK' if edge_alive else 'KHONG CHAY'}")
    lines.append(f"- main.py (YOLO): {'OK' if yolo_alive else 'KHONG CHAY'}")

    await update.effective_message.reply_text("\n".join(lines))
