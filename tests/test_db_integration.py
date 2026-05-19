from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from zurini.data import db
from zurini.data.dummy import generate_dummy_bars
from zurini.data.large_dummy import (
    SymbolMetadata,
    generate_symbol_metadata,
    get_large_dummy_profile,
    iter_large_dummy_index_bars,
    iter_large_dummy_market_bars,
)
from zurini.dry_run import build_empty_plan_a_dry_run_report, dry_run_ledger_events, persist_dry_run_report
from zurini.kis_index_feed import KisIndexSample

pytestmark = pytest.mark.integration


def test_schema_loader_and_ordered_date_range_fetch_roundtrip():
    db.reset_market_bars()
    bars = generate_dummy_bars(seed=7477)

    assert db.insert_bars(bars) == len(bars)
    fetched = db.fetch_bars("ZRN001", start=bars[3].timestamp, end=bars[7].timestamp)

    assert len(fetched) == 5
    assert fetched == sorted(fetched, key=lambda bar: (bar.symbol, bar.timestamp))
    assert fetched[0].symbol == bars[3].symbol
    assert fetched[0].timestamp == bars[3].timestamp
    assert fetched[-1].timestamp == bars[7].timestamp


def test_index_ticks_store_ten_second_poll_samples_separately_from_minute_bars():
    db.reset_index_tables()
    sample = KisIndexSample(
        "KOSPI",
        datetime(2026, 5, 15, 9, 0, 3, tzinfo=ZoneInfo("Asia/Seoul")),
        price=100,
        open=99,
        high=101,
        low=98,
        volume=10,
    )

    assert db.insert_index_ticks([sample], poll_interval_seconds=10, source_run_id="run-1") == 1

    with db._connect() as conn:
        row = conn.execute(
            """
            SELECT index_code, price, session_open, session_high, session_low,
                   poll_interval_seconds, raw_payload ->> 'source'
            FROM index_ticks
            WHERE index_code = 'KOSPI'
            """
        ).fetchone()
    assert row == ("KOSPI", 100, 99, 101, 98, 10, "kis-index-poll-10s")


def test_multi_symbol_schema_load_and_fetch_roundtrip():
    db.reset_market_bars()
    bars = generate_dummy_bars(symbol="ZRN001") + generate_dummy_bars(symbol="ZRN002")

    assert db.insert_bars(bars) == len(bars)
    first = db.fetch_bars("ZRN001")
    second = db.fetch_bars("ZRN002")

    assert len(first) == 30
    assert len(second) == 30
    assert {bar.symbol for bar in first + second} == {"ZRN001", "ZRN002"}


def test_schema_rejects_duplicate_symbol_timestamp():
    db.reset_market_bars()
    bars = generate_dummy_bars(seed=7477)
    db.insert_bars(bars)

    with pytest.raises(Exception):
        db.insert_bars([bars[0]])


def test_workflow_lock_releases_after_exception():
    with pytest.raises(RuntimeError, match="sentinel"):
        with db.workflow_lock(timeout_seconds=0):
            raise RuntimeError("sentinel")

    with db.workflow_lock(timeout_seconds=0):
        pass


def test_workflow_lock_times_out_when_already_held():
    with db.workflow_lock(timeout_seconds=0):
        with pytest.raises(RuntimeError, match="already running"):
            with db.workflow_lock(timeout_seconds=0):
                pass


def test_phase_two_staging_tables_exist_for_indices_and_symbol_metadata():
    db.reset_rehearsal_tables()

    with db._connect() as conn:
        index_count = conn.execute("SELECT count(*) FROM index_bars").fetchone()[0]
        metadata_count = conn.execute("SELECT count(*) FROM symbol_metadata").fetchone()[0]

    assert index_count == 0
    assert metadata_count == 0


def test_synthetic_rehearsal_loads_market_index_and_metadata_tables():
    profile = get_large_dummy_profile("smoke")
    market_bars = list(iter_large_dummy_market_bars(profile))
    index_bars = list(iter_large_dummy_index_bars(profile))
    metadata = generate_symbol_metadata(profile)
    db.reset_rehearsal_tables()

    assert db.insert_symbol_metadata(metadata) == profile.symbol_count
    assert db.insert_bars(market_bars) == profile.market_bar_count
    assert db.insert_index_bars(index_bars) == profile.index_bar_count

    with db._connect() as conn:
        market_count = conn.execute("SELECT count(*) FROM market_bars").fetchone()[0]
        index_count = conn.execute("SELECT count(*) FROM index_bars").fetchone()[0]
        metadata_count = conn.execute("SELECT count(*) FROM symbol_metadata").fetchone()[0]
        index_codes = {
            row[0]
            for row in conn.execute("SELECT DISTINCT index_code FROM index_bars ORDER BY index_code").fetchall()
        }

    assert market_count == profile.market_bar_count
    assert index_count == profile.index_bar_count
    assert metadata_count == profile.symbol_count
    assert index_codes == set(profile.index_codes)


def test_replace_symbol_metadata_source_rejects_cross_source_collision():
    db.reset_rehearsal_tables()
    existing = [
        SymbolMetadata(
            symbol="005930",
            name="Manual Samsung",
            market="KOSPI",
            source="manual-source",
        )
    ]
    replacement = [
        SymbolMetadata(
            symbol="005930",
            name="KIS Samsung",
            market="KOSPI",
            source="kis-stock-master",
        )
    ]

    assert db.insert_symbol_metadata(existing) == 1
    with pytest.raises(ValueError, match="005930:manual-source"):
        db.replace_symbol_metadata_source(replacement, source="kis-stock-master")

    with db._connect() as conn:
        row = conn.execute("SELECT name, source FROM symbol_metadata WHERE symbol = '005930'").fetchone()

    assert row == ("Manual Samsung", "manual-source")


def test_dry_run_ledger_roundtrip_persists_no_order_session_and_events():
    db.reset_dry_run_ledger()
    report = build_empty_plan_a_dry_run_report(
        trading_date=date(2026, 5, 11),
        session_id="integration-dry-run-ledger",
    )

    inserted = persist_dry_run_report(report)
    session = db.fetch_dry_run_session("integration-dry-run-ledger")
    events = db.fetch_dry_run_ledger_events("integration-dry-run-ledger")

    assert inserted == len(dry_run_ledger_events(report))
    assert session is not None
    assert session["mode"] == "no-order"
    assert session["order_hard_block"] is True
    assert session["summary"]["ready_for_broker_or_order_transmission"] is False
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[0]["event_type"] == "session-summary"
    assert events[-1]["event_type"] == "plan-b-fallback-state"


def test_multi_dry_run_ledger_insert_rolls_back_all_sessions_on_failure():
    db.reset_dry_run_ledger()
    summary = {"ready_for_broker_or_order_transmission": False}
    records = [
        {
            "session_id": "atomic-ledger",
            "trading_date": date(2026, 5, 11),
            "package_id": "plan-a",
            "mode": "no-order",
            "order_hard_block": True,
            "summary": summary,
            "events": [{"sequence": 1, "event_type": "session-summary", "payload": summary}],
        },
        {
            "session_id": "atomic-ledger",
            "trading_date": date(2026, 5, 12),
            "package_id": "plan-a",
            "mode": "no-order",
            "order_hard_block": True,
            "summary": summary,
            "events": [{"sequence": 1, "event_type": "session-summary", "payload": summary}],
        },
    ]

    with pytest.raises(Exception):
        db.insert_dry_run_ledgers(records)

    assert db.fetch_dry_run_session("atomic-ledger") is None


def test_dry_run_ledger_rejects_duplicate_event_sequences():
    db.reset_dry_run_ledger()

    with pytest.raises(ValueError, match="duplicate"):
        db.insert_dry_run_ledger(
            session_id="duplicate-event-ledger",
            trading_date=date(2026, 5, 11),
            package_id="plan-a-idmom-d3-fsup-u1s1",
            mode="no-order",
            order_hard_block=True,
            summary={"ready_for_broker_or_order_transmission": False},
            events=[
                {"sequence": 1, "event_type": "daily-reconciliation", "payload": {}},
                {"sequence": 1, "event_type": "daily-reconciliation", "payload": {}},
            ],
        )


def test_dry_run_ledger_rejects_broker_ready_summary():
    db.reset_dry_run_ledger()

    with pytest.raises(ValueError, match="broker/order readiness"):
        db.insert_dry_run_ledger(
            session_id="broker-ready-ledger",
            trading_date=date(2026, 5, 11),
            package_id="plan-a-idmom-d3-fsup-u1s1",
            mode="no-order",
            order_hard_block=True,
            summary={"ready_for_broker_or_order_transmission": True},
            events=[],
        )


def test_dry_run_ledger_rejects_string_order_hard_block():
    db.reset_dry_run_ledger()

    with pytest.raises(ValueError, match="hard-block"):
        db.insert_dry_run_ledger(
            session_id="string-hard-block-ledger",
            trading_date=date(2026, 5, 11),
            package_id="plan-a-idmom-d3-fsup-u1s1",
            mode="no-order",
            order_hard_block="true",
            summary={"ready_for_broker_or_order_transmission": False},
            events=[],
        )


def test_dry_run_ledger_rejects_unblocked_virtual_order_payload():
    db.reset_dry_run_ledger()

    with pytest.raises(ValueError, match="hard-block"):
        db.insert_dry_run_ledger(
            session_id="unblocked-order-ledger",
            trading_date=date(2026, 5, 11),
            package_id="plan-a-idmom-d3-fsup-u1s1",
            mode="no-order",
            order_hard_block=True,
            summary={"ready_for_broker_or_order_transmission": False},
            events=[
                {
                    "sequence": 1,
                    "event_type": "virtual-order",
                    "payload": {"hard_blocked": False},
                },
            ],
        )


def test_dry_run_session_schema_rejects_missing_broker_readiness_key():
    db.reset_dry_run_ledger()

    with pytest.raises(Exception):
        with db._connect() as conn:
            conn.execute(
                """
                INSERT INTO dry_run_sessions (
                    session_id, trading_date, package_id, mode, order_hard_block, summary
                )
                VALUES (
                    'missing-readiness-key', '2026-05-11', 'plan-a-idmom-d3-fsup-u1s1',
                    'no-order', true, '{}'::jsonb
                )
                """
            )


def test_dry_run_session_schema_rejects_string_broker_readiness_false():
    db.reset_dry_run_ledger()

    with pytest.raises(Exception):
        with db._connect() as conn:
            conn.execute(
                """
                INSERT INTO dry_run_sessions (
                    session_id, trading_date, package_id, mode, order_hard_block, summary
                )
                VALUES (
                    'string-readiness-false', '2026-05-11', 'plan-a-idmom-d3-fsup-u1s1',
                    'no-order', true, '{"ready_for_broker_or_order_transmission":"false"}'::jsonb
                )
                """
            )


def test_dry_run_session_summary_event_schema_rejects_missing_broker_readiness_key():
    db.reset_dry_run_ledger()
    db.insert_dry_run_ledger(
        session_id="valid-session-for-invalid-summary-event",
        trading_date=date(2026, 5, 11),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary={"ready_for_broker_or_order_transmission": False},
        events=[],
    )

    with pytest.raises(Exception):
        with db._connect() as conn:
            conn.execute(
                """
                INSERT INTO dry_run_ledger_events (
                    session_id, sequence, event_type, payload
                )
                VALUES (
                    'valid-session-for-invalid-summary-event', 1, 'session-summary',
                    '{}'::jsonb
                )
                """
            )


def test_dry_run_session_summary_event_schema_rejects_string_broker_readiness_false():
    db.reset_dry_run_ledger()
    db.insert_dry_run_ledger(
        session_id="valid-session-for-string-summary-event",
        trading_date=date(2026, 5, 11),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary={"ready_for_broker_or_order_transmission": False},
        events=[],
    )

    with pytest.raises(Exception):
        with db._connect() as conn:
            conn.execute(
                """
                INSERT INTO dry_run_ledger_events (
                    session_id, sequence, event_type, payload
                )
                VALUES (
                    'valid-session-for-string-summary-event', 1, 'session-summary',
                    '{"ready_for_broker_or_order_transmission":"false"}'::jsonb
                )
                """
            )


def test_dry_run_virtual_order_schema_rejects_missing_hard_block_key():
    db.reset_dry_run_ledger()
    db.insert_dry_run_ledger(
        session_id="valid-session-for-invalid-order-event",
        trading_date=date(2026, 5, 11),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary={"ready_for_broker_or_order_transmission": False},
        events=[],
    )

    with pytest.raises(Exception):
        with db._connect() as conn:
            conn.execute(
                """
                INSERT INTO dry_run_ledger_events (
                    session_id, sequence, event_type, payload
                )
                VALUES (
                    'valid-session-for-invalid-order-event', 1, 'virtual-order',
                    '{}'::jsonb
                )
                """
            )


def test_dry_run_virtual_order_schema_rejects_string_hard_block_true():
    db.reset_dry_run_ledger()
    db.insert_dry_run_ledger(
        session_id="valid-session-for-string-order-event",
        trading_date=date(2026, 5, 11),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary={"ready_for_broker_or_order_transmission": False},
        events=[],
    )

    with pytest.raises(Exception):
        with db._connect() as conn:
            conn.execute(
                """
                INSERT INTO dry_run_ledger_events (
                    session_id, sequence, event_type, payload
                )
                VALUES (
                    'valid-session-for-string-order-event', 1, 'virtual-order',
                    '{"hard_blocked":"true"}'::jsonb
                )
                """
            )


def test_dry_run_ledger_fetches_latest_open_positions_for_state_recovery():
    db.reset_dry_run_ledger()
    db.insert_dry_run_ledger(
        session_id="recover-run-primary-current-seed-1m",
        trading_date=date(2026, 5, 12),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary={"ready_for_broker_or_order_transmission": False},
        events=[
            {
                "sequence": 1,
                "event_type": "open-position",
                "payload": {
                    "position_id": "A000001-2026-05-11T10:00:00+09:00",
                    "symbol": "A000001",
                    "strategy_group": "swing",
                    "quantity": "1",
                    "entry_price": "100",
                    "slot_id": "swing-1",
                    "sleeve_id": "swing",
                    "exit_policy": "default",
                },
            }
        ],
    )
    db.insert_dry_run_ledger(
        session_id="recover-run-shadow-future-seed-70m",
        trading_date=date(2026, 5, 11),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary={"ready_for_broker_or_order_transmission": False},
        events=[
            {
                "sequence": 1,
                "event_type": "open-position",
                "payload": {
                    "position_id": "A999999-2026-05-11T10:00:00+09:00",
                    "symbol": "A999999",
                    "strategy_group": "swing",
                    "quantity": "1",
                    "entry_price": "100",
                    "slot_id": "swing-1",
                    "sleeve_id": "swing",
                    "exit_policy": "default",
                },
            }
        ],
    )

    positions = db.fetch_latest_dry_run_open_positions(session_id_prefix="recover-run")

    assert positions == [
        {
            "position_id": "A000001-2026-05-11T10:00:00+09:00",
            "symbol": "A000001",
            "strategy_group": "swing",
            "quantity": "1",
            "entry_price": "100",
            "slot_id": "swing-1",
            "sleeve_id": "swing",
            "exit_policy": "default",
        }
    ]


def test_dry_run_resume_state_reconstructs_cash_portfolio_and_checkpoints():
    db.reset_dry_run_ledger()
    db.insert_dry_run_ledger(
        session_id="resume-run-primary-current-seed-1m",
        trading_date=date(2026, 5, 12),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary={"ready_for_broker_or_order_transmission": False},
        events=[
            {"sequence": 1, "event_type": "session-summary", "payload": {"ready_for_broker_or_order_transmission": False}},
            {
                "sequence": 2,
                "event_type": "open-position",
                "payload": {"symbol": "A000001", "strategy_group": "swing", "quantity": "1"},
            },
            {
                "sequence": 3,
                "event_type": "cash-reconciliation",
                "payload": {"ending_cash": "900000", "reserved_cash": "100000"},
            },
            {
                "sequence": 4,
                "event_type": "portfolio-state",
                "payload": {"cash": "900000", "swing_slots_used": 1},
            },
            {
                "sequence": 5,
                "event_type": "checkpoint-event",
                "payload": {"trigger_id": "dry-run-day-10", "deployment_blocked": True},
            },
        ],
    )

    state = db.fetch_latest_dry_run_resume_state(session_id_prefix="resume-run")

    assert state is not None
    assert state["status"] == "ready"
    assert state["mode"] == "no-order-resume-state"
    assert state["open_positions"][0]["symbol"] == "A000001"
    assert state["cash"]["ending_cash"] == "900000"
    assert state["portfolio_state"]["swing_slots_used"] == 1
    assert state["checkpoint_events"][0]["trigger_id"] == "dry-run-day-10"
    assert state["ready_for_broker_or_order_transmission"] is False


def test_dry_run_resume_state_requires_fresh_as_of_evidence():
    db.reset_dry_run_ledger()
    summary = {"ready_for_broker_or_order_transmission": False}
    db.insert_dry_run_ledger(
        session_id="resume-stale-primary-current-seed-1m",
        trading_date=date(2026, 5, 12),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary=summary,
        events=[
            {
                "sequence": 1,
                "event_type": "session-summary",
                "event_time": datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                "payload": summary,
            }
        ],
    )

    with pytest.raises(ValueError, match="stale"):
        db.fetch_latest_dry_run_resume_state(
            session_id_prefix="resume-stale",
            as_of=datetime(2026, 5, 12, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            target_trading_date=date(2026, 5, 12),
            max_session_age_minutes=30,
        )


def test_dry_run_ledger_roundtrips_final_applied_parameter_fields():
    db.reset_dry_run_ledger()
    summary = {"ready_for_broker_or_order_transmission": False}
    payload = {
        "symbol": "A005930",
        "hard_blocked": True,
        "strategy_id": "C-IDMOM-D3-U1-S1",
        "strategy_group": "day",
        "entry_rule": "custom-entry",
        "exit_rule": "profit-target",
        "cost_model": "fee_rate=0.00030;slippage_rate=0.00100",
        "applied_profit_target": "0.08",
        "applied_hard_stop": "-0.018",
        "applied_max_holding_minutes": 180,
        "applied_day_end_exit": True,
    }
    db.insert_dry_run_ledger(
        session_id="ledger-applied-fields-primary-current-seed-1m",
        trading_date=date(2026, 5, 12),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary=summary,
        events=[
            {"sequence": 1, "event_type": "session-summary", "payload": summary},
            {"sequence": 2, "event_type": "virtual-order", "payload": payload},
        ],
    )

    events = db.fetch_dry_run_ledger_events("ledger-applied-fields-primary-current-seed-1m")

    order = next(event for event in events if event["event_type"] == "virtual-order")
    assert order["payload"]["strategy_id"] == "C-IDMOM-D3-U1-S1"
    assert order["payload"]["applied_profit_target"] == "0.08"
    assert order["payload"]["applied_day_end_exit"] is True
    assert order["payload"]["cost_model"] == "fee_rate=0.00030;slippage_rate=0.00100"


def test_dry_run_resume_state_prefers_primary_scenario_over_shadow():
    db.reset_dry_run_ledger()
    summary = {"ready_for_broker_or_order_transmission": False}
    db.insert_dry_run_ledgers(
        [
            {
                "session_id": "field-runner-shadow-future-seed-70m",
                "trading_date": date(2026, 5, 13),
                "package_id": "plan-a-idmom-d3-fsup-u1s1",
                "mode": "no-order",
                "order_hard_block": True,
                "summary": summary,
                "events": [
                    {"sequence": 1, "event_type": "session-summary", "payload": summary},
                    {
                        "sequence": 2,
                        "event_type": "cash-reconciliation",
                        "payload": {"ending_cash": "70000000"},
                    },
                ],
            },
            {
                "session_id": "field-runner-primary-current-seed-1m",
                "trading_date": date(2026, 5, 12),
                "package_id": "plan-a-idmom-d3-fsup-u1s1",
                "mode": "no-order",
                "order_hard_block": True,
                "summary": summary,
                "events": [
                    {"sequence": 1, "event_type": "session-summary", "payload": summary},
                    {
                        "sequence": 2,
                        "event_type": "cash-reconciliation",
                        "payload": {"ending_cash": "1000000"},
                    },
                ],
            },
        ]
    )

    state = db.fetch_latest_dry_run_resume_state(session_id_prefix="field-runner")

    assert state is not None
    assert state["session"]["session_id"] == "field-runner-primary-current-seed-1m"
    assert state["cash"]["ending_cash"] == "1000000"


def test_dry_run_resume_state_rejects_shadow_only_prefix():
    db.reset_dry_run_ledger()
    summary = {"ready_for_broker_or_order_transmission": False}
    db.insert_dry_run_ledger(
        session_id="shadow-only-run-shadow-future-seed-70m",
        trading_date=date(2026, 5, 12),
        package_id="plan-a-idmom-d3-fsup-u1s1",
        mode="no-order",
        order_hard_block=True,
        summary=summary,
        events=[
            {"sequence": 1, "event_type": "session-summary", "payload": summary},
        ],
    )

    with pytest.raises(ValueError, match="primary-current-seed-1m"):
        db.fetch_latest_dry_run_resume_state(session_id_prefix="shadow-only-run")


def test_multi_dry_run_ledger_rejects_string_order_hard_block():
    db.reset_dry_run_ledger()

    with pytest.raises(ValueError, match="hard-block"):
        db.insert_dry_run_ledgers(
            [
                {
                    "session_id": "multi-string-hard-block-ledger",
                    "trading_date": date(2026, 5, 11),
                    "package_id": "plan-a-idmom-d3-fsup-u1s1",
                    "mode": "no-order",
                    "order_hard_block": "false",
                    "summary": {"ready_for_broker_or_order_transmission": False},
                    "events": [],
                }
            ]
        )
