from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Iterable

from zurini.data.validation import validate_bar
from zurini.market import Bar

if TYPE_CHECKING:
    from zurini.data.large_dummy import SymbolMetadata

DEFAULT_DATABASE_URL = "postgresql://zurini:zurini@localhost:55432/zurini"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
WORKFLOW_LOCK_ID = 7477001
DEFAULT_WORKFLOW_LOCK_TIMEOUT_SECONDS = 120.0
PRIMARY_DRY_RUN_SCENARIO_ID = "primary-current-seed-1m"


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
        conn.execute("DROP TABLE IF EXISTS index_bars")
        conn.execute("DROP TABLE IF EXISTS symbol_metadata")
    apply_schema()


def reset_dry_run_ledger() -> None:
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS dry_run_ledger_events")
        conn.execute("DROP TABLE IF EXISTS dry_run_sessions")
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


def _validate_unique_bar(bar: Bar, seen: set[tuple[str, object]]) -> None:
    validate_bar(bar)
    key = (bar.symbol, bar.timestamp)
    if key in seen:
        from zurini.data.validation import BarValidationError

        raise BarValidationError("duplicate symbol + timestamp")
    seen.add(key)


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
