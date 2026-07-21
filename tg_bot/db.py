"""Ket noi Postgres cho tg_bot (chay tren host, khong phai container) - dung
cho cac lenh doc du lieu: status/traffic/report/history.

Cac ham o day la SYNC (psycopg2 khong ho tro async). Command handler (async)
phai goi qua asyncio.to_thread(...) de khong block event loop cua bot khi
cho Postgres tra ket qua.
"""
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from tg_bot import config


@contextmanager
def get_connection():
    conn = psycopg2.connect(
        host=config.POSTGRES_HOST,
        port=config.POSTGRES_PORT,
        dbname=config.POSTGRES_DB,
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD,
    )
    try:
        yield conn
    finally:
        conn.close()


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def fetch_one(query: str, params: tuple = ()) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None
