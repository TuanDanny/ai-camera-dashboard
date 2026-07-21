"""Kiem tra quyen goi lenh nguy hiem (restartyolo/restartmqtt/reboot/cleardb).

An toan mac dinh: neu TELEGRAM_ALLOWED_USER_IDS trong .env de trong thi
ALLOWED_USER_IDS la set() rong -> KHONG ai duoc phep, kho ca chinh admin
nho dien user_id vao .env truoc.
"""
from telegram import Update
from telegram.ext import ContextTypes

from tg_bot import config


def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id in config.ALLOWED_USER_IDS


async def require_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Goi dau moi lenh nguy hiem. Tra ve True neu duoc phep, nguoc lai tu
    tra loi tin nhan tu choi va tra ve False (handler goi ham nay chi viec
    return ngay khi ket qua la False)."""
    if is_allowed(update):
        return True

    await update.message.reply_text(
        "Ban khong co quyen goi lenh nay.\n"
        f"User ID cua ban: {update.effective_user.id}\n"
        "Lien he admin de duoc them vao TELEGRAM_ALLOWED_USER_IDS trong .env."
    )
    return False
