"""Lenh /snapshot - giong /view nhung gui duoi dang FILE GOC (khong bi
Telegram nen anh nhu reply_photo), dat ten file kem timestamp - dung khi
can luu lai bang chung/anh chat luong day."""
import asyncio
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from tg_bot.commands.view_cmd import _fetch_jpeg


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        jpeg_bytes = await asyncio.to_thread(_fetch_jpeg)
    except Exception as exc:
        await update.effective_message.reply_text(
            f"Khong lay duoc anh camera hien tai (main.py co dang chay khong?): {exc}"
        )
        return

    filename = f"snapshot_{datetime.now():%Y%m%d_%H%M%S}.jpg"
    await update.effective_message.reply_document(
        document=jpeg_bytes, filename=filename, caption=filename
    )
