"""Lenh /panel - bang dieu khien nhanh bang nut bam, thay vi phai go tay
tung lenh. Chi nut bam o day, LOGIC XU LY khi bam nam trong bot.py (Task
#11, qua CallbackQueryHandler) - file nay chi dung ban phim.

Quy uoc callback_data: "panel:<ten_lenh>" (vd "panel:status"). Voi 4 lenh
nguy hiem, callback_data van la "panel:reboot"/"panel:cleardb"/... nhung
bot.py se dua qua cung 1 luong auth + xac nhan Yes/No nhu khi go lenh
truc tiep, KHONG bo qua buoc nao ca.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

_KEYBOARD_LAYOUT = [
    [("Status", "status"), ("Check", "check")],
    [("Xem camera", "view"), ("Chup anh", "snapshot")],
    [("Luu luong", "traffic"), ("Bao cao", "report")],
    [("Lich su", "history"), ("Phien ban", "version")],
    [("Restart YOLO", "restartyolo"), ("Restart MQTT", "restartmqtt")],
    [("Reboot Pi", "reboot"), ("Xoa du lieu xe", "cleardb")],
]


def build_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(label, callback_data=f"panel:{cmd}")
            for label, cmd in row
        ]
        for row in _KEYBOARD_LAYOUT
    ]
    return InlineKeyboardMarkup(rows)


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Bang dieu khien SHTP Traffic:", reply_markup=build_keyboard()
    )
