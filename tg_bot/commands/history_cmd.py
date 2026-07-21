"""Lenh /history - 5 canh bao (device_alerts) va 5 su kien watchdog gan
nhat, giup xem nhanh co su co gi bat thuong khong ma khong can mo Grafana."""
import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from tg_bot import config, db

_ALERTS_QUERY = """
    SELECT alert_at, severity, code, message
    FROM device_alerts
    WHERE station_id = %s
    ORDER BY alert_at DESC
    LIMIT 5;
"""

_WATCHDOG_QUERY = """
    SELECT event_at, event_type, reason
    FROM watchdog_events
    WHERE station_id = %s
    ORDER BY event_at DESC
    LIMIT 5;
"""


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        alerts, watchdog_events = await asyncio.gather(
            asyncio.to_thread(db.fetch_all, _ALERTS_QUERY, (config.DEFAULT_STATION_ID,)),
            asyncio.to_thread(db.fetch_all, _WATCHDOG_QUERY, (config.DEFAULT_STATION_ID,)),
        )
    except Exception as exc:
        await update.effective_message.reply_text(f"Loi truy van Postgres: {exc}")
        return

    lines = [f"Lich su gan day - tram {config.DEFAULT_STATION_ID}:", "", "Canh bao:"]
    if alerts:
        for row in alerts:
            lines.append(f"- [{row['severity']}] {row['alert_at']} {row['code']}: {row['message']}")
    else:
        lines.append("- Khong co canh bao nao.")

    lines.append("")
    lines.append("Watchdog reset:")
    if watchdog_events:
        for row in watchdog_events:
            lines.append(f"- {row['event_at']} {row['event_type']} ({row['reason']})")
    else:
        lines.append("- Khong co su kien reset nao.")

    await update.effective_message.reply_text("\n".join(lines))
