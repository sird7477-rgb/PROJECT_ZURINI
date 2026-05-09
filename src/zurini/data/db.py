from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Iterable

from zurini.data.validation import validate_bar
from zurini.market import Bar

if TYPE_CHECKING:
    from zurini.data.large_dummy import SymbolMetadata

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


def reset_rehearsal_tables() -> None:
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS market_bars")
        conn.execute("DROP TABLE IF EXISTS index_bars")
        conn.execute("DROP TABLE IF EXISTS symbol_metadata")
    apply_schema()


def insert_bars(bars: Iterable[Bar], *, batch_size: int = 5_000) -> int:
    seen: set[tuple[str, object]] = set()
    total = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for rows in _batched_market_rows(bars, seen=seen, batch_size=batch_size):
                cur.executemany(
                    """
                    INSERT INTO market_bars (
                        symbol, timestamp, open, high, low, close, volume, value, source
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
                total += len(rows)
    return total


def insert_index_bars(bars: Iterable[Bar], *, batch_size: int = 5_000) -> int:
    seen: set[tuple[str, object]] = set()
    total = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for rows in _batched_index_rows(bars, seen=seen, batch_size=batch_size):
                cur.executemany(
                    """
                    INSERT INTO index_bars (
                        index_code, timestamp, open, high, low, close, volume, source
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
                total += len(rows)
    return total


def insert_symbol_metadata(metadata: Iterable[SymbolMetadata]) -> int:
    rows = [
        (
            item.symbol,
            item.name,
            item.market,
            item.section_kind,
            item.status_kind,
            item.control_kind,
            item.supervision_kind,
            item.source,
        )
        for item in metadata
    ]
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO symbol_metadata (
                    symbol, name, market, section_kind, status_kind,
                    control_kind, supervision_kind, source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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


def _batched_market_rows(
    bars: Iterable[Bar],
    *,
    seen: set[tuple[str, object]],
    batch_size: int,
):
    rows = []
    for bar in bars:
        _validate_unique_bar(bar, seen)
        rows.append(
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
        )
        if len(rows) >= batch_size:
            yield rows
            rows = []
    if rows:
        yield rows


def _batched_index_rows(
    bars: Iterable[Bar],
    *,
    seen: set[tuple[str, object]],
    batch_size: int,
):
    rows = []
    for bar in bars:
        _validate_unique_bar(bar, seen)
        rows.append(
            (
                bar.symbol,
                bar.timestamp,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.source,
            )
        )
        if len(rows) >= batch_size:
            yield rows
            rows = []
    if rows:
        yield rows


def _validate_unique_bar(bar: Bar, seen: set[tuple[str, object]]) -> None:
    validate_bar(bar)
    key = (bar.symbol, bar.timestamp)
    if key in seen:
        from zurini.data.validation import BarValidationError

        raise BarValidationError("duplicate symbol + timestamp")
    seen.add(key)
