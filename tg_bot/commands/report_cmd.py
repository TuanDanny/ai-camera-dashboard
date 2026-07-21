"""Lenh /report - bao cao tong xe HOM NAY so voi HOM QUA (tinh theo
DATE_TRUNC('day', recorded_at), gio may chay Postgres = TZ trong .env)."""
import asyncio
from datetime import timedelta

from telegram import Update
from telegram.ext import ContextTypes

from tg_bot import config, db

_QUERY = """
    SELECT
        DATE_TRUNC('day', recorded_at) AS day,
        COALESCE(SUM(total_count), 0)  AS total
    FROM traffic_records
    WHERE station_id = %s
      AND recorded_at >= DATE_TRUNC('day', NOW() - INTERVAL '1 day')
    GROUP BY day
    ORDER BY day;
"""


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        rows = await asyncio.to_thread(
            db.fetch_all, _QUERY, (config.DEFAULT_STATION_ID,)
        )
    except Exception as exc:
        await update.effective_message.reply_text(f"Loi truy van Postgres: {exc}")
        return

    totals_by_day = {row["day"].date(): row["total"] for row in rows}
    today = max(totals_by_day.keys(), default=None)

    if today is None:
        await update.effective_message.reply_text(
            f"Chua co du lieu xe nao (tram {config.DEFAULT_STATION_ID})."
        )
        return

    yesterday = today - timedelta(days=1)
    total_today = totals_by_day.get(today, 0)
    total_yesterday = totals_by_day.get(yesterday, 0)

    lines = [
        f"Bao cao luu luong xe - tram {config.DEFAULT_STATION_ID}:",
        "",
        f"- Hom nay ({today}):  {total_today} xe",
        f"- Hom qua ({yesterday}): {total_yesterday} xe",
    ]

    if total_yesterday > 0:
        diff_pct = round((total_today - total_yesterday) / total_yesterday * 100, 1)
        sign = "+" if diff_pct >= 0 else ""
        lines.append(f"- Chenh lech: {sign}{diff_pct}%")

    await update.effective_message.reply_text("\n".join(lines))
