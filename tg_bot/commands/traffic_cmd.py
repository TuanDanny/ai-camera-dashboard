"""Lenh /traffic - tong luu luong xe theo tung loai trong 1 GIO gan nhat
(khac /report la bao cao ca ngay hom nay so voi hom qua)."""
import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from tg_bot import config, db

_QUERY = """
    SELECT
        COALESCE(SUM(motorbike_count), 0) AS motorbike,
        COALESCE(SUM(car_count), 0)       AS car,
        COALESCE(SUM(truck_count), 0)     AS truck,
        COALESCE(SUM(bus_count), 0)       AS bus,
        COALESCE(SUM(bicycle_count), 0)   AS bicycle,
        COALESCE(SUM(total_count), 0)     AS total,
        COUNT(*)                          AS num_intervals
    FROM traffic_records
    WHERE station_id = %s AND recorded_at >= NOW() - INTERVAL '1 hour';
"""


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        row = await asyncio.to_thread(
            db.fetch_one, _QUERY, (config.DEFAULT_STATION_ID,)
        )
    except Exception as exc:
        await update.effective_message.reply_text(f"Loi truy van Postgres: {exc}")
        return

    if not row or row["num_intervals"] == 0:
        await update.effective_message.reply_text(
            f"Khong co du lieu xe nao trong 1 gio gan nhat (tram {config.DEFAULT_STATION_ID})."
        )
        return

    lines = [
        f"Luu luong xe - tram {config.DEFAULT_STATION_ID} (1 gio gan nhat):",
        "",
        f"- Xe may:  {row['motorbike']}",
        f"- O to:    {row['car']}",
        f"- Xe tai:  {row['truck']}",
        f"- Xe buyt: {row['bus']}",
        f"- Xe dap:  {row['bicycle']}",
        f"- Tong:    {row['total']}",
        "",
        f"(tinh tu {row['num_intervals']} ban ghi)",
    ]
    await update.effective_message.reply_text("\n".join(lines))
