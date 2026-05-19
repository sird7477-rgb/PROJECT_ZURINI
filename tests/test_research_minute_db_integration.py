from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from zurini.data import db
from zurini.research_minute_dataset import normalize_research_minute_row


pytestmark = pytest.mark.integration
KST = ZoneInfo("Asia/Seoul")


def test_research_minute_import_refreshes_canonical_with_kis_priority() -> None:
    db.reset_research_minute_tables()
    timestamp = datetime(2026, 5, 15, 10, 0, tzinfo=KST)
    legacy = normalize_research_minute_row(
        symbol="A005930",
        timestamp=timestamp,
        open_price=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=1000,
        value=Decimal("100000"),
        source="legacy-daishin",
        vendor="daishin",
        source_run_id="run-legacy",
        import_batch_id="batch-a",
    )
    kis = normalize_research_minute_row(
        symbol="A005930",
        timestamp=timestamp,
        open_price=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=1000,
        value=Decimal("101000"),
        source="kis-minute-poll",
        vendor="kis",
        source_run_id="run-kis",
        import_batch_id="batch-a",
    )

    result = db.insert_research_minute_rows([legacy, kis])

    assert result.inserted_raw_rows == 2
    assert result.canonical_rows_refreshed == 1
    canonical = db.fetch_research_minute_canonical_rows("A005930")
    assert len(canonical) == 1
    assert canonical[0].source == "kis-minute-poll"
    assert canonical[0].close == Decimal("101")
    with db._connect() as conn:
        row = conn.execute(
            """
            SELECT source_count, conflict_flags
            FROM research_minute_canonical
            WHERE symbol = 'A005930'
            """
        ).fetchone()
    assert row[0] == 2
    assert row[1] == ["source_overlap_conflict"]


def test_research_minute_import_roundtrips_operating_fields() -> None:
    db.reset_research_minute_tables()
    timestamp = datetime(2026, 5, 15, 10, 0, tzinfo=KST)
    row = normalize_research_minute_row(
        symbol="A005930",
        timestamp=timestamp,
        open_price=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=1000,
        value=Decimal("100000"),
        bid_ask_ratio=Decimal("2.5"),
        traded_value=Decimal("100000"),
        action="buy",
        passed=True,
        rank=1,
        reason="entry",
        score=Decimal("0.8"),
        strategy_group="day",
        input_flags=("fresh_quote",),
        data_origin="field-observation",
        raw_payload={"source_row": "5/15"},
        source="field-monitor-local",
        vendor="kis",
        source_run_id="run-kis",
        import_batch_id="batch-operating",
    )

    db.insert_research_minute_rows([row])

    with db._connect() as conn:
        fetched = conn.execute(
            """
            SELECT bid_ask_ratio, action, passed, rank, reason, score,
                   strategy_group, input_flags, data_origin, raw_payload
            FROM research_minute_canonical
            WHERE symbol = 'A005930'
            """
        ).fetchone()
    assert fetched[0] == Decimal("2.500000")
    assert fetched[1] == "buy"
    assert fetched[2] is True
    assert fetched[3] == 1
    assert fetched[4] == "entry"
    assert fetched[5] == Decimal("0.800000")
    assert fetched[6] == "day"
    assert fetched[7] == ["fresh_quote"]
    assert fetched[8] == "field-observation"
    assert fetched[9] == {"source_row": "5/15"}


def test_research_minute_schema_rejects_daily_universe_origin() -> None:
    db.reset_research_minute_tables()
    timestamp = datetime(2026, 5, 14, 15, 15, tzinfo=KST)

    with db._connect() as conn:
        with pytest.raises(Exception):
            conn.execute(
                """
                INSERT INTO research_minute_raw (
                    symbol, timestamp, interval, open, high, low, close,
                    data_origin, source, vendor, source_run_id, import_batch_id, schema_version
                )
                VALUES (
                    'A000660', %s, '1m', 100, 101, 99, 100,
                    'universe-selection-source', 'kis-daily-bars', 'kis',
                    'run-kis-daily', 'batch-universe', 'research-minute-v1'
                )
                """,
                (timestamp,),
            )
        conn.rollback()


def test_universe_daily_and_trade_history_tables_enforce_separate_contracts() -> None:
    db.apply_schema()
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO universe_daily_raw (
                symbol, trading_date, open, high, low, close, volume, value,
                source, vendor, source_run_id, import_batch_id, schema_version
            )
            VALUES (
                'A005930', '2026-05-14', 100, 101, 99, 100, 1000, 100000,
                'kis-daily-bars', 'kis', 'run-kis-daily', 'batch-universe', 'universe-daily-v1'
            )
            ON CONFLICT DO NOTHING
            """
        )
        daily = conn.execute(
            """
            SELECT data_origin, trading_date
            FROM universe_daily_raw
            WHERE symbol = 'A005930'
            """
        ).fetchone()
        assert daily == ("universe-selection-source", datetime(2026, 5, 14).date())

        with pytest.raises(Exception):
            conn.execute(
                """
                INSERT INTO universe_daily_raw (
                    symbol, trading_date, open, high, low, close,
                    data_origin, source, vendor, source_run_id, import_batch_id, schema_version
                )
                VALUES (
                    'A000660', '2026-05-14', 100, 101, 99, 100,
                    'field-observation', 'kis-daily-bars', 'kis',
                    'run-kis-daily', 'batch-universe', 'universe-daily-v1'
                )
                """
            )
        conn.rollback()

    db.apply_schema()
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_runs (run_id, trade_mode, started_at)
            VALUES ('run-trades-1', 'dry_run', %s)
            ON CONFLICT DO NOTHING
            """,
            (datetime(2026, 5, 15, 9, 0, tzinfo=KST),),
        )
        conn.execute(
            """
            INSERT INTO trade_signals (
                signal_id, run_id, trade_mode, strategy_group, strategy_id,
                strategy_version, symbol, signal_time, signal_price, decision,
                signal_payload
            )
            VALUES (
                'sig-1', 'run-trades-1', 'dry_run', 'day', 'day-vwap',
                '2026-05-16-a', 'A005930', %s, 100, 'triggered',
                '{"reason":"test"}'::jsonb
            )
            ON CONFLICT DO NOTHING
            """,
            (datetime(2026, 5, 15, 10, 0, tzinfo=KST),),
        )
        with pytest.raises(Exception):
            conn.execute(
                """
                INSERT INTO trade_signals (
                    signal_id, run_id, trade_mode, strategy_group, strategy_id,
                    strategy_version, symbol, signal_time, signal_price, decision,
                    signal_payload
                )
                VALUES (
                    'sig-mode-bad', 'run-trades-1', 'live', 'day', 'bad-mode',
                    '2026-05-16-a', 'A005930', %s, 100, 'triggered',
                    '{}'::jsonb
                )
                """,
                (datetime(2026, 5, 15, 10, 1, tzinfo=KST),),
            )
        conn.rollback()

    db.apply_schema()
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_runs (run_id, trade_mode, started_at)
            VALUES ('run-trades-2', 'dry_run', %s)
            ON CONFLICT DO NOTHING
            """,
            (datetime(2026, 5, 15, 9, 0, tzinfo=KST),),
        )
        conn.execute(
            """
            INSERT INTO trade_signals (
                signal_id, run_id, trade_mode, strategy_group, strategy_id,
                strategy_version, symbol, signal_time, signal_price, decision,
                signal_payload
            )
            VALUES (
                'sig-2', 'run-trades-2', 'dry_run', 'swing', 'swing-v1',
                '2026-05-16-a', 'A005930', %s, 100, 'triggered',
                '{}'::jsonb
            )
            ON CONFLICT DO NOTHING
            """,
            (datetime(2026, 5, 15, 10, 0, tzinfo=KST),),
        )
        with pytest.raises(Exception):
            conn.execute(
                """
                INSERT INTO trade_orders (
                    order_id, signal_id, run_id, trade_mode, strategy_group,
                    symbol, order_time, side, order_status
                )
                VALUES (
                    'order-context-bad', 'sig-2', 'run-trades-2', 'dry_run', 'day',
                    'A005930', %s, 'buy', 'virtual'
                )
                """,
                (datetime(2026, 5, 15, 10, 2, tzinfo=KST),),
            )
        conn.rollback()

    db.apply_schema()
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_runs (run_id, trade_mode, started_at)
            VALUES ('run-trades-3', 'dry_run', %s)
            ON CONFLICT DO NOTHING
            """,
            (datetime(2026, 5, 15, 9, 0, tzinfo=KST),),
        )
        with pytest.raises(Exception):
            conn.execute(
                """
                INSERT INTO trade_signals (
                    signal_id, run_id, trade_mode, strategy_group, strategy_id,
                    strategy_version, symbol, signal_time, signal_price, decision,
                    signal_payload
                )
                VALUES (
                    'sig-bad', 'run-trades-3', 'dry_run', 'longterm', 'bad',
                    '2026-05-16-a', 'A005930', %s, 100, 'triggered',
                    '{}'::jsonb
                )
                """,
                (datetime(2026, 5, 15, 10, 1, tzinfo=KST),),
            )
        conn.rollback()


def test_research_minute_retention_deletes_rows_older_than_cutoff() -> None:
    db.reset_research_minute_tables()
    latest = datetime(2026, 5, 15, 10, 0, tzinfo=KST)
    old_timestamp = latest - timedelta(days=731)
    recent_timestamp = latest - timedelta(days=10)
    rows = [
        normalize_research_minute_row(
            symbol="A005930",
            timestamp=old_timestamp,
            open_price=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            value=Decimal("100000"),
            source="legacy-daishin",
            vendor="daishin",
            source_run_id="run-old",
            import_batch_id="batch-old",
        ),
        normalize_research_minute_row(
            symbol="A005930",
            timestamp=recent_timestamp,
            open_price=Decimal("110"),
            high=Decimal("111"),
            low=Decimal("109"),
            close=Decimal("110"),
            volume=1200,
            value=Decimal("132000"),
            source="kis-minute-poll",
            vendor="kis",
            source_run_id="run-new",
            import_batch_id="batch-new",
        ),
    ]
    db.insert_research_minute_rows(rows)

    dry_run = db.apply_research_minute_rolling_retention(
        latest_timestamp=latest,
        retention_days=730,
        dry_run=True,
    )
    assert dry_run.raw_rows_eligible == 1
    assert dry_run.canonical_rows_eligible == 1
    assert dry_run.raw_rows_deleted == 0

    applied = db.apply_research_minute_rolling_retention(
        latest_timestamp=latest,
        retention_days=730,
        dry_run=False,
    )
    assert applied.raw_rows_deleted == 1
    assert applied.canonical_rows_deleted == 1
    with db._connect() as conn:
        raw_count = conn.execute("SELECT COUNT(*) FROM research_minute_raw").fetchone()[0]
        canonical_count = conn.execute("SELECT COUNT(*) FROM research_minute_canonical").fetchone()[0]
    assert raw_count == 1
    assert canonical_count == 1
