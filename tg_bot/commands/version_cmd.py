"""Lenh /version - phien ban bot + commit/branch git dang trien khai, de
biet ro dang chay dung ban da deploy khong khi co nhieu thay doi lien tuc."""
import asyncio
import subprocess

from telegram import Update
from telegram.ext import ContextTypes

from tg_bot import config


def _git_info() -> tuple[str, str]:
    def _run(args: list[str]) -> str:
        result = subprocess.run(
            args, cwd=config.REPO_ROOT, capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else "?"

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    commit = _run(["git", "rev-parse", "--short", "HEAD"])
    return branch, commit


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    branch, commit = await asyncio.to_thread(_git_info)
    await update.effective_message.reply_text(
        f"tg_bot v{config.BOT_VERSION}\n"
        f"Branch: {branch}\n"
        f"Commit: {commit}"
    )
