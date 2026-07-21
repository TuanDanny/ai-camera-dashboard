"""Lenh /view - lay 1 anh camera hien tai (da ve box/vach do) qua endpoint
/snapshot cua ai-worker (frame_broadcast.py) va gui vao chat duoi dang
anh (nen/thu nho tu dong boi Telegram) - xem nhanh, khong luu file goc.
Muon file goc dung lenh /snapshot."""
import asyncio
import urllib.request

from telegram import Update
from telegram.ext import ContextTypes

from tg_bot import config


def _fetch_jpeg() -> bytes:
    with urllib.request.urlopen(config.MJPEG_SNAPSHOT_URL, timeout=10) as resp:
        return resp.read()


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        jpeg_bytes = await asyncio.to_thread(_fetch_jpeg)
    except Exception as exc:
        await update.effective_message.reply_text(
            f"Khong lay duoc anh camera hien tai (main.py co dang chay khong?): {exc}"
        )
        return

    await update.effective_message.reply_photo(photo=jpeg_bytes, caption="Camera hien tai")
