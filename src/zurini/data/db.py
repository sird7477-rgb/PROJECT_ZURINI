from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Iterable

from zurini.data.validation import validate_bar
from zurini.market import Bar
from zurini.research_minute_dataset import (
    ResearchMinuteRow,
    normalize_research_minute_row,
    rolling_two_year_cutoff,
    select_canonical_minute_row,
)

if TYPE_CHECKING:
    from zurini.data.large_dummy import SymbolMetadata

DEFAULT_DATABASE_URL = "postgresql://zurini:zurini@localhost:55432/zurini"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
WORKFLOW_LOCK_ID = 7477001
DEFAULT_WORKFLOW_LOCK_TIMEOUT_SECONDS = 120.0
PRIMARY_DRY_RUN_SCENARIO_ID = "primary-current-seed-1m"


@dataclass(frozen=True)
class ResearchMinuteImportResult:
    inserted_raw_rows: int
    canonical_rows_refreshed: int
    distinct_key_count: int
    duplicate_input_rows: int


@dataclass(frozen=True)
class ResearchMinuteRetentionReport:
    reference_timestamp: datetime
    cutoff_timestamp: datetime
    retention_days: int
    dry_run: bool
    canonical_rows_eligible: int
    raw_rows_eligible: int
    canonical_rows_deleted: int
    raw_rows_deleted: int


@dataclass(frozen=True)
class UniverseDailyRow:
    symbol: str
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None
    value: Decimal | None
    data_origin: str
    source: str
    vendor: str
    source_run_id: str
    import_batch_id: str
    schema_version: str
    quality_flags: tuple[str, ...] = ()
    raw_payload: dict[str, object] | None = None


@dataclass(frozen=True)
class UniverseDailyImportResult:
    inserted_or_updated_raw_rows: int
    canonical_rows_refreshed: int
    distinct_key_count: int
    duplicate_input_rows: int


@dataclass(frozen=True)
class IndexBarRow:
    index_code: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    data_origin: str
    source: str
    vendor: str
    source_run_id: str
    import_batch_id: str
    schema_version: str
    quality_flags: tuple[str, ...] = ()
    raw_payload: dict[str, object] | None = None


@dataclass(frozen=True)
class IndexBarImportResult:
    inserted_or_updated_rows: int
    inserted_rows: int
    updated_rows: int
    distinct_key_count: int
    duplicate_input_rows: int


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def _connect():
    import psycopg

    return psycopg.connect(database_url())


@contextmanager
def workflow_lock(timeout_seconds: float = DEFAULT_WORKFLOW_LOCK_TIMEOUT_SECONDS):
    with _connect() as conn:
        deadline = time.monotonic() + timeout_seconds
        while True:
            acquired = conn.execute("SELECT pg_try_advisory_lock(%s)", (WORKFLOW_LOCK_ID,)).fetchone()[0]
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("another Zurini database workflow is already running")
            time.sleep(0.25)
        try:
            yield
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (WORKFLOW_LOCK_ID,))


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
        conn.execute("DROP TABLE IF EXISTS index_ticks")
        conn.execute("DROP TABLE IF EXISTS index_bars")
        conn.execute("DROP TABLE IF EXISTS symbol_metadata")
    apply_schema()


def reset_dry_run_ledger() -> None:
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS dry_run_ledger_events")
        conn.execute("DROP TABLE IF EXISTS dry_run_sessions")
    apply_schema()


def reset_research_minute_tables() -> None:
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS research_minute_canonical")
        conn.execute("DROP TABLE IF EXISTS research_minute_raw")
    apply_schema()


def reset_universe_daily_tables() -> None:
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS universe_daily_canonical")
        conn.execute("DROP TABLE IF EXISTS universe_daily_raw")
    apply_schema()


def reset_index_tables() -> None:
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS index_bars")
        conn.execute("DROP TABLE IF EXISTS index_ticks")
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
    rows = (
        IndexBarRow(
            index_code=bar.symbol,
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            data_origin="sample",
            source=bar.source,
            vendor="sample",
            source_run_id="sample-run",
            import_batch_id="sample-batch",
            schema_version="bar-v1",
            raw_payload=None,
        )
        for bar in bars
    )
    return insert_index_bar_rows(rows, batch_size=batch_size).inserted_or_updated_rows


def insert_index_bar_rows(rows: Iterable[IndexBarRow], *, batch_size: int = 5_000) -> IndexBarImportResult:
    seen: set[tuple[str, object, str, str, str, str]] = set()
    duplicate_input_rows = 0
    inserted = 0
    updated = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for batch, batch_duplicates in _batched_index_bar_rows(rows, seen=seen, batch_size=batch_size):
                duplicate_input_rows += batch_duplicates
                for row in batch:
                    cur.execute(
                        """
                        INSERT INTO index_bars (
                            index_code, timestamp, open, high, low, close, volume,
                            source, vendor, source_run_id, import_batch_id,
                            schema_version, data_origin, quality_flags, raw_payload
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                        )
                        ON CONFLICT (
                            index_code, timestamp, source, vendor, source_run_id, import_batch_id
                        ) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume,
                            schema_version = EXCLUDED.schema_version,
                            data_origin = EXCLUDED.data_origin,
                            quality_flags = EXCLUDED.quality_flags,
                            raw_payload = EXCLUDED.raw_payload,
                            ingested_at = now()
                        RETURNING xmax = 0
                        """,
                        row,
                    )
                    if cur.fetchone()[0]:
                        inserted += 1
                    else:
                        updated += 1
    return IndexBarImportResult(
        inserted_or_updated_rows=inserted + updated,
        inserted_rows=inserted,
        updated_rows=updated,
        distinct_key_count=len(seen),
        duplicate_input_rows=duplicate_input_rows,
    )


def insert_index_ticks(
    samples: Iterable[object],
    *,
    poll_interval_seconds: int = 10,
    source_run_id: str = "field-run",
    vendor: str = "kis",
    batch_size: int = 5_000,
) -> int:
    rows = []
    seen: set[tuple[str, object, str, str, str]] = set()
    for sample in samples:
        source = str(getattr(sample, "source", "kis-index-poll-10s"))
        key = (
            str(getattr(sample, "index_code")),
            getattr(sample, "timestamp"),
            source,
            vendor,
            source_run_id,
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            (
                key[0],
                key[1],
                getattr(sample, "price"),
                getattr(sample, "open", None),
                getattr(sample, "high", None),
                getattr(sample, "low", None),
                getattr(sample, "volume", 0),
                source,
                vendor,
                source_run_id,
                poll_interval_seconds,
                [],
                json.dumps(getattr(sample, "as_dict", lambda: None)(), sort_keys=True),
            )
        )
    total = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for start in range(0, len(rows), batch_size):
                chunk = rows[start:start + batch_size]
                cur.executemany(
                    """
                    INSERT INTO index_ticks (
                        index_code, timestamp, price, session_open, session_high,
                        session_low, volume, source, vendor, source_run_id,
                        poll_interval_seconds, quality_flags, raw_payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (index_code, timestamp, source, vendor, source_run_id)
                    DO UPDATE SET
                        price = EXCLUDED.price,
                        session_open = EXCLUDED.session_open,
                        session_high = EXCLUDED.session_high,
                        session_low = EXCLUDED.session_low,
                        volume = EXCLUDED.volume,
                        poll_interval_seconds = EXCLUDED.poll_interval_seconds,
                        quality_flags = EXCLUDED.quality_flags,
                        raw_payload = EXCLUDED.raw_payload
                    """,
                    chunk,
                )
                total += len(chunk)
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


def replace_symbol_metadata_source(metadata: Iterable[SymbolMetadata], *, source: str) -> int:
    rows = [
        (
            item.symbol,
            item.name,
            item.market,
            item.section_kind,
            item.status_kind,
            item.control_kind,
            item.supervision_kind,
            source,
        )
        for item in metadata
    ]
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM symbol_metadata WHERE source = %s", (source,))
            symbols = [row[0] for row in rows]
            if symbols:
                cur.execute(
                    """
                    SELECT symbol, source
                    FROM symbol_metadata
                    WHERE symbol = ANY(%s) AND source <> %s
                    ORDER BY symbol
                    """,
                    (symbols, source),
                )
                collisions = cur.fetchall()
                if collisions:
                    preview = ", ".join(f"{symbol}:{existing_source}" for symbol, existing_source in collisions[:5])
                    raise ValueError(
                        f"symbol metadata source collision while replacing {source}: {preview}"
                    )
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


def insert_research_minute_rows(
    rows: Iterable[ResearchMinuteRow],
    *,
    batch_size: int = 5_000,
) -> ResearchMinuteImportResult:
    unique_rows: list[ResearchMinuteRow] = []
    seen: set[tuple[str, datetime, str, str, str, str, str]] = set()
    duplicate_input_rows = 0
    for row in rows:
        key = (
            row.symbol,
            row.timestamp,
            row.interval,
            row.source,
            row.vendor,
            row.source_run_id,
            row.import_batch_id,
        )
        if key in seen:
            duplicate_input_rows += 1
            continue
        seen.add(key)
        unique_rows.append(row)
    distinct_keys = {(row.symbol, row.timestamp, row.interval) for row in unique_rows}

    inserted = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for chunk in _batched_research_minute_rows(unique_rows, batch_size=batch_size):
                cur.executemany(
                    """
                    INSERT INTO research_minute_raw (
                        symbol,
                        timestamp,
                        interval,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        value,
                        bid_ask_ratio,
                        traded_value,
                        action,
                        passed,
                        rank,
                        reason,
                        score,
                        strategy_group,
                        input_flags,
                        data_origin,
                        raw_payload,
                        source,
                        vendor,
                        source_run_id,
                        import_batch_id,
                        schema_version,
                        quality_flags
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (symbol, timestamp, interval, source, vendor, source_run_id, import_batch_id)
                    DO NOTHING
                    """,
                    chunk,
                )
                inserted += max(cur.rowcount, 0)

    refreshed = refresh_research_minute_canonical_for_keys(distinct_keys)
    return ResearchMinuteImportResult(
        inserted_raw_rows=inserted,
        canonical_rows_refreshed=refreshed,
        distinct_key_count=len(distinct_keys),
        duplicate_input_rows=duplicate_input_rows,
    )


def insert_universe_daily_rows(
    rows: Iterable[UniverseDailyRow],
    *,
    batch_size: int = 5_000,
) -> UniverseDailyImportResult:
    unique_rows: list[UniverseDailyRow] = []
    seen: set[tuple[str, date, str, str, str, str]] = set()
    duplicate_input_rows = 0
    for row in rows:
        if row.data_origin != "universe-selection-source":
            raise ValueError("universe_daily rows require data_origin='universe-selection-source'")
        key = (
            row.symbol,
            row.trading_date,
            row.source,
            row.vendor,
            row.source_run_id,
            row.import_batch_id,
        )
        if key in seen:
            duplicate_input_rows += 1
            continue
        seen.add(key)
        unique_rows.append(row)
    distinct_keys = {(row.symbol, row.trading_date) for row in unique_rows}

    changed = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for chunk in _batched_universe_daily_rows(unique_rows, batch_size=batch_size):
                cur.executemany(
                    """
                    INSERT INTO universe_daily_raw (
                        symbol,
                        trading_date,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        value,
                        data_origin,
                        source,
                        vendor,
                        source_run_id,
                        import_batch_id,
                        schema_version,
                        quality_flags,
                        raw_payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (symbol, trading_date, source, vendor, source_run_id, import_batch_id)
                    DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        value = EXCLUDED.value,
                        data_origin = EXCLUDED.data_origin,
                        schema_version = EXCLUDED.schema_version,
                        quality_flags = EXCLUDED.quality_flags,
                        raw_payload = EXCLUDED.raw_payload,
                        ingested_at = now()
                    """,
                    chunk,
                )
                changed += max(cur.rowcount, 0)

    refreshed = refresh_universe_daily_canonical_for_keys(distinct_keys)
    return UniverseDailyImportResult(
        inserted_or_updated_raw_rows=changed,
        canonical_rows_refreshed=refreshed,
        distinct_key_count=len(distinct_keys),
        duplicate_input_rows=duplicate_input_rows,
    )


def refresh_universe_daily_canonical_for_keys(
    keys: Iterable[tuple[str, date]],
) -> int:
    ordered_keys = sorted(set(keys), key=lambda item: (item[0], item[1]))
    if not ordered_keys:
        return 0

    refreshed = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for symbol, trading_date in ordered_keys:
                cur.execute(
                    """
                    SELECT
                        row_id,
                        symbol,
                        trading_date,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        value,
                        data_origin,
                        source,
                        vendor,
                        source_run_id,
                        import_batch_id,
                        schema_version,
                        quality_flags,
                        raw_payload
                    FROM universe_daily_raw
                    WHERE symbol = %s
                      AND trading_date = %s
                    ORDER BY source, vendor, source_run_id, import_batch_id, row_id
                    """,
                    (symbol, trading_date),
                )
                fetched = cur.fetchall()
                if not fetched:
                    cur.execute(
                        """
                        DELETE FROM universe_daily_canonical
                        WHERE symbol = %s
                          AND trading_date = %s
                        """,
                        (symbol, trading_date),
                    )
                    continue
                selected = fetched[0]
                source_count = len(fetched)
                conflict_flags = []
                selected_bar = selected[3:9]
                if any(row[3:9] != selected_bar for row in fetched[1:]):
                    conflict_flags.append("source_overlap_conflict")
                cur.execute(
                    """
                    INSERT INTO universe_daily_canonical (
                        symbol,
                        trading_date,
                        selected_row_id,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        value,
                        data_origin,
                        source,
                        vendor,
                        source_run_id,
                        import_batch_id,
                        schema_version,
                        quality_flags,
                        raw_payload,
                        source_count,
                        conflict_flags,
                        refreshed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, now())
                    ON CONFLICT (symbol, trading_date) DO UPDATE SET
                        selected_row_id = EXCLUDED.selected_row_id,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        value = EXCLUDED.value,
                        data_origin = EXCLUDED.data_origin,
                        source = EXCLUDED.source,
                        vendor = EXCLUDED.vendor,
                        source_run_id = EXCLUDED.source_run_id,
                        import_batch_id = EXCLUDED.import_batch_id,
                        schema_version = EXCLUDED.schema_version,
                        quality_flags = EXCLUDED.quality_flags,
                        raw_payload = EXCLUDED.raw_payload,
                        source_count = EXCLUDED.source_count,
                        conflict_flags = EXCLUDED.conflict_flags,
                        refreshed_at = now()
                    """,
                    (
                        selected[1],
                        selected[2],
                        selected[0],
                        selected[3],
                        selected[4],
                        selected[5],
                        selected[6],
                        selected[7],
                        selected[8],
                        selected[9],
                        selected[10],
                        selected[11],
                        selected[12],
                        selected[13],
                        selected[14],
                        list(selected[15] or ()),
                        json.dumps(_json_safe(selected[16]), sort_keys=True) if selected[16] is not None else None,
                        source_count,
                        conflict_flags,
                    ),
                )
                refreshed += 1
    return refreshed


def refresh_research_minute_canonical_for_batch(import_batch_id: str) -> int:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT symbol, timestamp, interval
                FROM research_minute_raw
                WHERE import_batch_id = %s
                """,
                (import_batch_id,),
            )
            keys = {(row[0], row[1], row[2]) for row in cur.fetchall()}
    return refresh_research_minute_canonical_for_keys(keys)


def refresh_research_minute_canonical_for_keys(
    keys: Iterable[tuple[str, datetime, str]],
) -> int:
    refreshed = 0
    ordered_keys = sorted(set(keys), key=lambda item: (item[0], item[1], item[2]))
    if not ordered_keys:
        return 0

    with _connect() as conn:
        with conn.cursor() as cur:
            for symbol, timestamp, interval in ordered_keys:
                cur.execute(
                    """
                    SELECT
                        row_id,
                        symbol,
                        timestamp,
                        interval,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        value,
                        bid_ask_ratio,
                        traded_value,
                        action,
                        passed,
                        rank,
                        reason,
                        score,
                        strategy_group,
                        input_flags,
                        data_origin,
                        raw_payload,
                        source,
                        vendor,
                        source_run_id,
                        import_batch_id,
                        schema_version,
                        quality_flags
                    FROM research_minute_raw
                    WHERE symbol = %s
                      AND timestamp = %s
                      AND interval = %s
                    """,
                    (symbol, timestamp, interval),
                )
                fetched = cur.fetchall()
                if not fetched:
                    cur.execute(
                        """
                        DELETE FROM research_minute_canonical
                        WHERE symbol = %s
                          AND timestamp = %s
                          AND interval = %s
                        """,
                        (symbol, timestamp, interval),
                    )
                    continue
                rows: list[ResearchMinuteRow] = []
                row_id_by_signature: dict[tuple[str, str, str, str], int] = {}
                for item in fetched:
                    normalized = normalize_research_minute_row(
                        symbol=item[1],
                        timestamp=item[2],
                        interval=item[3],
                        open_price=item[4],
                        high=item[5],
                        low=item[6],
                        close=item[7],
                        volume=item[8],
                        value=item[9],
                        bid_ask_ratio=item[10],
                        traded_value=item[11],
                        action=item[12],
                        passed=item[13],
                        rank=item[14],
                        reason=item[15],
                        score=item[16],
                        strategy_group=item[17],
                        input_flags=tuple(item[18] or ()),
                        data_origin=item[19],
                        raw_payload=item[20],
                        source=item[21],
                        vendor=item[22],
                        source_run_id=item[23],
                        import_batch_id=item[24],
                        schema_version=item[25],
                        quality_flags=tuple(item[26] or ()),
                    )
                    rows.append(normalized)
                    row_id_by_signature[
                        (
                            normalized.source,
                            normalized.vendor,
                            normalized.source_run_id,
                            normalized.import_batch_id,
                        )
                    ] = item[0]
                selected = select_canonical_minute_row(rows)
                selected_signature = (
                    selected.row.source,
                    selected.row.vendor,
                    selected.row.source_run_id,
                    selected.row.import_batch_id,
                )
                selected_row_id = row_id_by_signature[selected_signature]
                cur.execute(
                    """
                    INSERT INTO research_minute_canonical (
                        symbol,
                        timestamp,
                        interval,
                        selected_row_id,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        value,
                        bid_ask_ratio,
                        traded_value,
                        action,
                        passed,
                        rank,
                        reason,
                        score,
                        strategy_group,
                        input_flags,
                        data_origin,
                        raw_payload,
                        source,
                        vendor,
                        source_run_id,
                        import_batch_id,
                        schema_version,
                        quality_flags,
                        source_count,
                        conflict_flags,
                        refreshed_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
                    )
                    ON CONFLICT (symbol, timestamp, interval) DO UPDATE SET
                        selected_row_id = EXCLUDED.selected_row_id,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        value = EXCLUDED.value,
                        bid_ask_ratio = EXCLUDED.bid_ask_ratio,
                        traded_value = EXCLUDED.traded_value,
                        action = EXCLUDED.action,
                        passed = EXCLUDED.passed,
                        rank = EXCLUDED.rank,
                        reason = EXCLUDED.reason,
                        score = EXCLUDED.score,
                        strategy_group = EXCLUDED.strategy_group,
                        input_flags = EXCLUDED.input_flags,
                        data_origin = EXCLUDED.data_origin,
                        raw_payload = EXCLUDED.raw_payload,
                        source = EXCLUDED.source,
                        vendor = EXCLUDED.vendor,
                        source_run_id = EXCLUDED.source_run_id,
                        import_batch_id = EXCLUDED.import_batch_id,
                        schema_version = EXCLUDED.schema_version,
                        quality_flags = EXCLUDED.quality_flags,
                        source_count = EXCLUDED.source_count,
                        conflict_flags = EXCLUDED.conflict_flags,
                        refreshed_at = now()
                    """,
                    (
                        selected.row.symbol,
                        selected.row.timestamp,
                        selected.row.interval,
                        selected_row_id,
                        selected.row.open,
                        selected.row.high,
                        selected.row.low,
                        selected.row.close,
                        selected.row.volume,
                        selected.row.value,
                        selected.row.bid_ask_ratio,
                        selected.row.traded_value,
                        selected.row.action,
                        selected.row.passed,
                        selected.row.rank,
                        selected.row.reason,
                        selected.row.score,
                        selected.row.strategy_group,
                        list(selected.row.input_flags),
                        selected.row.data_origin,
                        json.dumps(_json_safe(selected.row.raw_payload), sort_keys=True) if selected.row.raw_payload is not None else None,
                        selected.row.source,
                        selected.row.vendor,
                        selected.row.source_run_id,
                        selected.row.import_batch_id,
                        selected.row.schema_version,
                        list(selected.row.quality_flags),
                        selected.source_count,
                        list(selected.conflict_flags),
                    ),
                )
                refreshed += 1
    return refreshed


def apply_research_minute_rolling_retention(
    *,
    latest_timestamp: datetime | None = None,
    retention_days: int = 730,
    dry_run: bool = True,
) -> ResearchMinuteRetentionReport:
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    with _connect() as conn:
        with conn.cursor() as cur:
            reference = latest_timestamp
            if reference is None:
                cur.execute("SELECT MAX(timestamp) FROM research_minute_raw")
                reference = cur.fetchone()[0]
            if reference is None:
                raise ValueError("retention requires at least one research minute row")
            cutoff = rolling_two_year_cutoff(reference, days=retention_days)
            cur.execute(
                "SELECT COUNT(*) FROM research_minute_canonical WHERE timestamp < %s",
                (cutoff,),
            )
            canonical_eligible = int(cur.fetchone()[0])
            cur.execute(
                "SELECT COUNT(*) FROM research_minute_raw WHERE timestamp < %s",
                (cutoff,),
            )
            raw_eligible = int(cur.fetchone()[0])
            canonical_deleted = 0
            raw_deleted = 0
            if not dry_run:
                cur.execute(
                    "DELETE FROM research_minute_canonical WHERE timestamp < %s",
                    (cutoff,),
                )
                canonical_deleted = max(cur.rowcount, 0)
                cur.execute(
                    "DELETE FROM research_minute_raw WHERE timestamp < %s",
                    (cutoff,),
                )
                raw_deleted = max(cur.rowcount, 0)

    return ResearchMinuteRetentionReport(
        reference_timestamp=reference,
        cutoff_timestamp=cutoff,
        retention_days=retention_days,
        dry_run=dry_run,
        canonical_rows_eligible=canonical_eligible,
        raw_rows_eligible=raw_eligible,
        canonical_rows_deleted=canonical_deleted,
        raw_rows_deleted=raw_deleted,
    )


def fetch_research_minute_canonical_rows(
    symbol: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    interval: str = "1m",
) -> list[ResearchMinuteRow]:
    params: list[object] = [symbol, interval]
    filters = ["symbol = %s", "interval = %s"]
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
                SELECT
                    symbol,
                    timestamp,
                    interval,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    value,
                    bid_ask_ratio,
                    traded_value,
                    action,
                    passed,
                    rank,
                    reason,
                    score,
                    strategy_group,
                    input_flags,
                    data_origin,
                    raw_payload,
                    source,
                    vendor,
                    source_run_id,
                    import_batch_id,
                    schema_version,
                    quality_flags
                FROM research_minute_canonical
                WHERE {' AND '.join(filters)}
                ORDER BY symbol, timestamp
                """,
                params,
            )
            rows = cur.fetchall()
    return [
        normalize_research_minute_row(
            symbol=row[0],
            timestamp=row[1],
            interval=row[2],
            open_price=row[3],
            high=row[4],
            low=row[5],
            close=row[6],
            volume=row[7],
            value=row[8],
            bid_ask_ratio=row[9],
            traded_value=row[10],
            action=row[11],
            passed=row[12],
            rank=row[13],
            reason=row[14],
            score=row[15],
            strategy_group=row[16],
            input_flags=tuple(row[17] or ()),
            data_origin=row[18],
            raw_payload=row[19],
            source=row[20],
            vendor=row[21],
            source_run_id=row[22],
            import_batch_id=row[23],
            schema_version=row[24],
            quality_flags=tuple(row[25] or ()),
        )
        for row in rows
    ]


def insert_dry_run_ledger(
    *,
    session_id: str,
    trading_date: object,
    package_id: str,
    mode: str,
    order_hard_block: bool,
    summary: dict[str, Any],
    events: Iterable[dict[str, Any]],
) -> int:
    prepared = _prepare_dry_run_ledger(
        session_id=session_id,
        trading_date=trading_date,
        package_id=package_id,
        mode=mode,
        order_hard_block=order_hard_block,
        summary=summary,
        events=events,
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            _insert_prepared_dry_run_ledger(cur, prepared)
    return len(prepared["event_rows"])


def insert_dry_run_ledgers(records: Iterable[dict[str, Any]]) -> int:
    prepared_records = [
        _prepare_dry_run_ledger(
            session_id=str(record["session_id"]),
            trading_date=record["trading_date"],
            package_id=str(record["package_id"]),
            mode=str(record["mode"]),
            order_hard_block=record["order_hard_block"],
            summary=record["summary"],
            events=record["events"],
        )
        for record in records
    ]
    total = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for prepared in prepared_records:
                _insert_prepared_dry_run_ledger(cur, prepared)
                total += len(prepared["event_rows"])
    return total


def _prepare_dry_run_ledger(
    *,
    session_id: str,
    trading_date: object,
    package_id: str,
    mode: str,
    order_hard_block: object,
    summary: dict[str, Any],
    events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    if mode != "no-order":
        raise ValueError("dry-run ledger session mode must be no-order")
    if order_hard_block is not True:
        raise ValueError("dry-run ledger requires order hard-block evidence")
    if summary.get("ready_for_broker_or_order_transmission") is not False:
        raise ValueError("dry-run ledger summary must explicitly block broker/order readiness")

    event_rows = []
    seen_sequences: set[int] = set()
    for event in events:
        sequence = int(event["sequence"])
        if sequence <= 0:
            raise ValueError("dry-run ledger event sequence must be positive")
        if sequence in seen_sequences:
            raise ValueError("duplicate dry-run ledger event sequence")
        seen_sequences.add(sequence)
        event_type = str(event["event_type"])
        payload = event.get("payload", {})
        if event_type == "session-summary" and payload.get("ready_for_broker_or_order_transmission") is not False:
            raise ValueError("dry-run session-summary event must explicitly block broker/order readiness")
        if event_type == "virtual-order" and payload.get("hard_blocked") is not True:
            raise ValueError("dry-run virtual-order event must include hard-block evidence")
        event_rows.append(
            (
                session_id,
                sequence,
                event_type,
                event.get("event_time"),
                str(event.get("symbol", "")),
                str(event.get("strategy_group", "")),
                json.dumps(_json_safe(payload), sort_keys=True),
            )
        )

    return {
        "session_id": session_id,
        "trading_date": trading_date,
        "package_id": package_id,
        "mode": mode,
        "order_hard_block": order_hard_block,
        "summary": summary,
        "event_rows": event_rows,
    }


def _insert_prepared_dry_run_ledger(cur: Any, prepared: dict[str, Any]) -> None:
    cur.execute(
        """
        INSERT INTO dry_run_sessions (
            session_id, trading_date, package_id, mode, order_hard_block, summary
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            prepared["session_id"],
            prepared["trading_date"],
            prepared["package_id"],
            prepared["mode"],
            prepared["order_hard_block"],
            json.dumps(_json_safe(prepared["summary"]), sort_keys=True),
        ),
    )
    if prepared["event_rows"]:
        cur.executemany(
            """
            INSERT INTO dry_run_ledger_events (
                session_id, sequence, event_type, event_time, symbol,
                strategy_group, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            prepared["event_rows"],
        )


def fetch_dry_run_session(session_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id, trading_date, package_id, mode, order_hard_block, summary
                FROM dry_run_sessions
                WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "session_id": row[0],
        "trading_date": row[1].isoformat(),
        "package_id": row[2],
        "mode": row[3],
        "order_hard_block": row[4],
        "summary": row[5],
    }


def fetch_dry_run_ledger_events(session_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sequence, event_type, event_time, symbol, strategy_group, payload
                FROM dry_run_ledger_events
                WHERE session_id = %s
                ORDER BY sequence
                """,
                (session_id,),
            )
            rows = cur.fetchall()
    return [
        {
            "sequence": row[0],
            "event_type": row[1],
            "event_time": row[2].isoformat() if row[2] is not None else None,
            "symbol": row[3],
            "strategy_group": row[4],
            "payload": row[5],
        }
        for row in rows
    ]


def fetch_latest_dry_run_open_positions(*, session_id_prefix: str | None = None) -> list[dict[str, Any]]:
    session = _latest_dry_run_session(session_id_prefix=session_id_prefix)
    if session is None:
        if _dry_run_sessions_exist(session_id_prefix=session_id_prefix):
            raise ValueError(
                f"dry-run open-position recovery requires a {PRIMARY_DRY_RUN_SCENARIO_ID} primary scenario session"
            )
        return []
    events = fetch_dry_run_ledger_events(session["session_id"])
    return [event["payload"] for event in events if event["event_type"] == "open-position"]


def fetch_latest_dry_run_resume_state(
    *,
    session_id_prefix: str | None = None,
    as_of: datetime | None = None,
    target_trading_date: object | None = None,
    max_session_age_minutes: int | None = None,
) -> dict[str, Any] | None:
    if max_session_age_minutes is not None and max_session_age_minutes <= 0:
        raise ValueError("max_session_age_minutes must be positive")
    session = _latest_dry_run_session(session_id_prefix=session_id_prefix)
    if session is None:
        if _dry_run_sessions_exist(session_id_prefix=session_id_prefix):
            raise ValueError(
                f"dry-run resume requires a {PRIMARY_DRY_RUN_SCENARIO_ID} primary scenario session"
            )
        return None
    events = fetch_dry_run_ledger_events(session["session_id"])
    if target_trading_date is not None and session["trading_date"] != target_trading_date.isoformat():
        raise ValueError("dry-run resume latest session trading_date does not match requested target")
    if as_of is not None and max_session_age_minutes is not None:
        evidence_times = [
            datetime.fromisoformat(str(event["event_time"]).replace("Z", "+00:00"))
            for event in events
            if event.get("event_time")
        ]
        latest_evidence = max(evidence_times, default=None)
        if latest_evidence is None:
            raise ValueError("dry-run resume requires event_time freshness evidence")
        if latest_evidence > as_of + timedelta(seconds=60):
            raise ValueError("dry-run resume latest evidence is after as-of")
        if as_of - latest_evidence > timedelta(minutes=max_session_age_minutes):
            raise ValueError("dry-run resume latest evidence is stale")
    open_positions = [event["payload"] for event in events if event["event_type"] == "open-position"]
    cash_rows = [event["payload"] for event in events if event["event_type"] == "cash-reconciliation"]
    portfolio_rows = [event["payload"] for event in events if event["event_type"] == "portfolio-state"]
    checkpoint_rows = [event["payload"] for event in events if event["event_type"] == "checkpoint-event"]
    risk_rows = [event["payload"] for event in events if event["event_type"] == "risk-event"]
    return {
        "status": "ready" if session["order_hard_block"] else "invalid",
        "mode": "no-order-resume-state",
        "session": session,
        "open_positions": open_positions,
        "cash": cash_rows[-1] if cash_rows else None,
        "portfolio_state": portfolio_rows[-1] if portfolio_rows else None,
        "checkpoint_events": checkpoint_rows,
        "risk_events": risk_rows,
        "as_of": as_of.isoformat() if as_of else None,
        "max_session_age_minutes": max_session_age_minutes,
        "ready_for_broker_or_order_transmission": False,
    }


def _latest_dry_run_session(session_id_prefix: str | None = None) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            if session_id_prefix is None:
                cur.execute(
                    """
                    SELECT session_id
                    FROM dry_run_sessions
                    WHERE POSITION(%s IN session_id) > 0
                    ORDER BY
                        trading_date DESC,
                        session_id DESC
                    LIMIT 1
                    """,
                    (PRIMARY_DRY_RUN_SCENARIO_ID,),
                )
            else:
                cur.execute(
                    """
                    SELECT session_id
                    FROM dry_run_sessions
                    WHERE session_id LIKE %s
                      AND POSITION(%s IN session_id) > 0
                    ORDER BY
                        trading_date DESC,
                        session_id DESC
                    LIMIT 1
                    """,
                    (f"{session_id_prefix}%", PRIMARY_DRY_RUN_SCENARIO_ID),
                )
            row = cur.fetchone()
    if row is None:
        return None
    return fetch_dry_run_session(row[0])


def _dry_run_sessions_exist(session_id_prefix: str | None = None) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            if session_id_prefix is None:
                cur.execute("SELECT EXISTS (SELECT 1 FROM dry_run_sessions)")
            else:
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM dry_run_sessions WHERE session_id LIKE %s)",
                    (f"{session_id_prefix}%",),
                )
            return bool(cur.fetchone()[0])


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


def _batched_index_bar_rows(
    rows: Iterable[IndexBarRow],
    *,
    seen: set[tuple[str, object, str, str, str, str]],
    batch_size: int,
):
    batch = []
    duplicate_input_rows = 0
    for row in rows:
        _validate_index_bar_row(row)
        key = (
            row.index_code,
            row.timestamp,
            row.source,
            row.vendor,
            row.source_run_id,
            row.import_batch_id,
        )
        if key in seen:
            duplicate_input_rows += 1
            continue
        seen.add(key)
        batch.append(
            (
                row.index_code,
                row.timestamp,
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
                row.source,
                row.vendor,
                row.source_run_id,
                row.import_batch_id,
                row.schema_version,
                row.data_origin,
                list(row.quality_flags),
                json.dumps(_json_safe(row.raw_payload), sort_keys=True) if row.raw_payload is not None else None,
            )
        )
        if len(batch) >= batch_size:
            yield batch, duplicate_input_rows
            batch = []
            duplicate_input_rows = 0
    if batch or duplicate_input_rows:
        yield batch, duplicate_input_rows


def _batched_research_minute_rows(
    rows: Iterable[ResearchMinuteRow],
    *,
    batch_size: int,
):
    batch = []
    for row in rows:
        batch.append(
            (
                row.symbol,
                row.timestamp,
                row.interval,
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
                row.value,
                row.bid_ask_ratio,
                row.traded_value,
                row.action,
                row.passed,
                row.rank,
                row.reason,
                row.score,
                row.strategy_group,
                list(row.input_flags),
                row.data_origin,
                json.dumps(_json_safe(row.raw_payload), sort_keys=True) if row.raw_payload is not None else None,
                row.source,
                row.vendor,
                row.source_run_id,
                row.import_batch_id,
                row.schema_version,
                list(row.quality_flags),
            )
        )
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _batched_universe_daily_rows(
    rows: Iterable[UniverseDailyRow],
    *,
    batch_size: int,
):
    batch = []
    for row in rows:
        batch.append(
            (
                row.symbol,
                row.trading_date,
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
                row.value,
                row.data_origin,
                row.source,
                row.vendor,
                row.source_run_id,
                row.import_batch_id,
                row.schema_version,
                list(row.quality_flags),
                json.dumps(_json_safe(row.raw_payload), sort_keys=True) if row.raw_payload is not None else None,
            )
        )
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _validate_unique_bar(bar: Bar, seen: set[tuple[str, object]]) -> None:
    validate_bar(bar)
    key = (bar.symbol, bar.timestamp)
    if key in seen:
        from zurini.data.validation import BarValidationError

        raise BarValidationError("duplicate symbol + timestamp")
    seen.add(key)


def _validate_index_bar_row(row: IndexBarRow) -> None:
    validate_bar(
        Bar(
            symbol=row.index_code,
            timestamp=row.timestamp,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            value=Decimal("0"),
            source=row.source,
        )
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
