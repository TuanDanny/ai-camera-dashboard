"""Entry point cua tg_bot - dang ky toan bo CommandHandler + 1
CallbackQueryHandler dung chung cho nut bam trong /panel, roi chay
polling. Chay bang: python3 -m tg_bot.bot (tu thu muc goc repo).

Lenh nguy hiem (restartyolo/restartmqtt/reboot/cleardb) CHUA duoc dang ky
o day (Task #10 dang hoan) - neu bam nut tuong ung trong /panel se duoc
bao "chua trien khai" thay vi loi im lang hoac crash.
"""
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from tg_bot import config
from tg_bot.commands import (
    check_cmd,
    help_cmd,
    history_cmd,
    panel_cmd,
    report_cmd,
    snapshot_cmd,
    status_cmd,
    traffic_cmd,
    version_cmd,
    view_cmd,
)

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
)
logger = logging.getLogger("tg_bot")

# Lenh doc (Task #9). Task #10 se them 4 lenh nguy hiem vao day sau, kem
# require_auth + xac nhan Yes/No - khong phai sua gi khac trong file nay.
COMMAND_REGISTRY = {
    "help": help_cmd.run,
    "panel": panel_cmd.run,
    "status": status_cmd.run,
    "check": check_cmd.run,
    "view": view_cmd.run,
    "snapshot": snapshot_cmd.run,
    "traffic": traffic_cmd.run,
    "report": report_cmd.run,
    "history": history_cmd.run,
    "version": version_cmd.run,
}


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    cmd_name = query.data.split(":", 1)[1] if ":" in query.data else ""
    handler = COMMAND_REGISTRY.get(cmd_name)

    if handler is None:
        await query.message.reply_text(
            f"Lenh '{cmd_name}' chua duoc trien khai (dang cho Task #10)."
        )
        return

    await handler(update, context)


def main() -> None:
    app = Application.builder().token(config.BOT_TOKEN).build()

    for name, handler in COMMAND_REGISTRY.items():
        app.add_handler(CommandHandler(name, handler))

    app.add_handler(CallbackQueryHandler(panel_callback, pattern=r"^panel:"))

    logger.info("tg_bot dang chay (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
