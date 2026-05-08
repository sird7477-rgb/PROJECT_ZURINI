from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from typing import Iterable

from zurini.data.validation import validate_bars
from zurini.market import Bar

DEFAULT_DATABASE_URL = "postgresql://zurini:zurini@localhost:55432/zurini"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def _connect():
    import psycopg

    return psycopg.connect(database_url())


def apply_schema() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def reset_market_bars() -> None:
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS market_bars")
    apply_schema()


def insert_bars(bars: Iterable[Bar]) -> int:
    valid = validate_bars(bars)
    rows = [
        (
            bar.symbol,
            bar.timestamp,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.value,
            bar.source,
        )
        for bar in valid
    ]
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO market_bars (
                    symbol, timestamp, open, high, low, close, volume, value, source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
    return len(rows)


def fetch_bars(
    symbol: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Bar]:
    params: list[object] = [symbol]
    filters = ["symbol = %s"]
    if start is not None:
        filters.append("timestamp >= %s")
        params.append(start)
    if end is not None:
        filters.append("timestamp <= %s")
        params.append(end)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT symbol, timestamp, open, high, low, close, volume, value, source
                FROM market_bars
                WHERE {' AND '.join(filters)}
                ORDER BY symbol, timestamp
                """,
                params,
            )
            return [
                Bar(
                    symbol=row[0],
                    timestamp=row[1],
                    open=row[2],
                    high=row[3],
                    low=row[4],
                    close=row[5],
                    volume=row[6],
                    value=row[7],
                    source=row[8],
                )
                for row in cur.fetchall()
            ]
