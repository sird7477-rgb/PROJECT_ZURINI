from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import zurini.api_smoke as api_smoke
from zurini import field_monitor
from zurini.cli import (
    _bars_from_watchlist_history,
    _classify_daily_bar_collection_scope,
    _local_free_space_gb,
    _merge_kis_daily_bar_collection_results,
    main,
)
from zurini.blacklist import AsyncBlacklistEntry, AsyncBlacklistSnapshot
from zurini.dry_run import (
    VirtualOrder,
    build_empty_plan_a_dry_run_report,
    build_plan_a_capital_cases,
    build_plan_a_limited_sensitivity_decision,
    dry_run_ledger_events,
    run_plan_a_multi_session_dry_run,
    run_plan_a_historical_dry_run,
    validate_no_order_report,
    write_dry_run_report,
    write_multi_session_dry_run_report,
    write_plan_a_sensitivity_decision,
)
from zurini.market import Bar, SignalIntent


class _TestDryRunStrategy:
    def on_bar(self, bar: Bar) -> SignalIntent:
        if bar.timestamp.hour == 10:
            return SignalIntent(
                action="buy",
                weight=Decimal("1"),
                reason="test-day-entry",
                score=Decimal("10"),
                profit_target=Decimal("0.05"),
                hard_stop=Decimal("-0.02"),
                max_holding_minutes=360,
                day_end_exit=True,
                group="day",
            )
        return SignalIntent(action="hold", reason="test-hold")


class _HoldDryRunStrategy:
    def on_bar(self, bar: Bar) -> SignalIntent:
        return SignalIntent(action="hold", reason="test-no-signal")


class _RiskAwareEntryStrategy:
    def on_bar(self, bar: Bar, risk=None) -> SignalIntent:
        if not risk.allows_entry(bar):
            return SignalIntent(action="hold", reason=risk.block_reason(bar))
        return SignalIntent(action="buy", weight=Decimal("1"), reason="risk-aware-entry", group="day")


def test_strategy_warmup_diagnostics_do_not_flag_universe_filter_only_rows():
    rows = [
        {
            "symbol": "A005930",
            "timestamp": "2026-05-15T10:00:00+09:00",
            "reason": "portfolio-no-entry(day=universe-filter,swing=no-entry)",
            "passed": False,
        }
    ]

    diagnostics = field_monitor._strategy_warmup_diagnostics(rows, date(2026, 5, 15))

    assert diagnostics["status"] == "ready"
    assert diagnostics["flags"] == []
    assert diagnostics["max_prior_sessions"] == 0
    assert diagnostics["universe_filter_latest_count"] == 1


def test_strategy_warmup_diagnostics_flag_warming_up_rows():
    rows = [
        {
            "symbol": "A005930",
            "timestamp": "2026-05-14T15:15:00+09:00",
            "reason": "portfolio-no-entry(day=warming-up,swing=no-entry)",
            "passed": False,
        },
        {
            "symbol": "A005930",
            "timestamp": "2026-05-15T10:00:00+09:00",
            "reason": "portfolio-no-entry(day=warming-up,swing=no-entry)",
            "passed": False,
        },
    ]

    diagnostics = field_monitor._strategy_warmup_diagnostics(rows, date(2026, 5, 15))

    assert diagnostics["status"] == "insufficient"
    assert diagnostics["flags"] == ["strategy_warmup_insufficient"]
    assert diagnostics["max_prior_sessions"] == 1


class _ExpensiveDaySwingStrategy:
    def on_bar(self, bar: Bar) -> SignalIntent:
        if bar.timestamp.hour != 10:
            return SignalIntent(action="hold", reason="test-hold")
        group = "day" if bar.symbol == "A000001" else "swing"
        return SignalIntent(
            action="buy",
            weight=Decimal("1"),
            reason=f"test-expensive-{group}",
            score=Decimal("10"),
            group=group,
        )


class _SwingEntryStrategy:
    def on_bar(self, bar: Bar) -> SignalIntent:
        if bar.timestamp.hour == 10:
            return SignalIntent(
                action="buy",
                weight=Decimal("1"),
                reason="test-swing-entry",
                score=Decimal("10"),
                group="swing",
                profit_target=Decimal("0.03"),
                hard_stop=Decimal("-0.03"),
                max_holding_minutes=10080,
            )
        return SignalIntent(action="hold", reason="test-hold")


class _DayExitStrategy:
    def on_bar(self, bar: Bar) -> SignalIntent:
        if bar.timestamp.hour == 10:
            return SignalIntent(
                action="buy",
                weight=Decimal("1"),
                reason="test-day-entry-exit",
                score=Decimal("10"),
                profit_target=Decimal("0.05"),
                hard_stop=Decimal("-0.03"),
                group="day",
                day_end_exit=True,
            )
        return SignalIntent(action="hold", reason="test-hold")


class _PartialSessionDayExitStrategy:
    def on_bar(self, bar: Bar) -> SignalIntent:
        if bar.timestamp.hour == 10:
            return SignalIntent(
                action="buy",
                weight=Decimal("1"),
                reason="test-partial-session-day-entry",
                score=Decimal("10"),
                group="day",
                day_end_exit=True,
            )
        return SignalIntent(action="hold", reason="test-hold")


class _ShortHoldSwingStrategy:
    def on_bar(self, bar: Bar) -> SignalIntent:
        if bar.timestamp.hour == 10:
            return SignalIntent(
                action="buy",
                weight=Decimal("1"),
                reason="test-short-hold-swing",
                score=Decimal("10"),
                group="swing",
                max_holding_minutes=60,
            )
        return SignalIntent(action="hold", reason="test-hold")


class _WarmupThenDayEntryStrategy:
    def __init__(self) -> None:
        self.seen_trading_days: set[date] = set()
        self.entered = False

    def on_bar(self, bar: Bar) -> SignalIntent:
        self.seen_trading_days.add(bar.timestamp.date())
        if len(self.seen_trading_days) >= 2 and not self.entered:
            self.entered = True
            return SignalIntent(
                action="buy",
                weight=Decimal("1"),
                reason="test-stateful-day-entry",
                score=Decimal("10"),
                group="day",
                max_holding_minutes=60,
                day_end_exit=True,
            )
        return SignalIntent(action="hold", reason="test-warming-up")


class _BuyOnceStatefulStrategy:
    def __init__(self) -> None:
        self.entered = False

    def on_bar(self, bar: Bar) -> SignalIntent:
        if not self.entered and bar.timestamp.hour == 10:
            self.entered = True
            return SignalIntent(
                action="buy",
                weight=Decimal("1"),
                reason="test-scoped-state-entry",
                score=Decimal("10"),
                group="day",
                day_end_exit=True,
            )
        return SignalIntent(action="hold", reason="test-stateful-hold")


def test_plan_a_dry_run_report_declares_no_order_contract(tmp_path):
    report = build_empty_plan_a_dry_run_report(trading_date=date(2026, 5, 11))
    output = tmp_path / "dry-run.json"

    write_dry_run_report(report, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["mode"] == "no-order"
    assert payload["summary"]["order_hard_block"] is True
    assert payload["summary"]["ready_for_broker_or_order_transmission"] is False
    assert payload["report"]["strategy_package"]["day_strategy"] == "C-IDMOM-D3-U1-S1"
    assert payload["report"]["strategy_package"]["swing_strategy"] == "F-SUP-U1-S1"
    assert payload["report"]["strategy_package"]["operating_ceiling"] == "70000000"
    assert payload["report"]["strategy_package"]["fallback_package_id"] == "plan-b-idmom-d3-fsup-u1s1"


def test_plan_a_capital_cases_separate_required_from_sensitivity():
    cases = {case.case_id: case for case in build_plan_a_capital_cases()}

    assert cases["shared-slot-plan-a"].required is True
    assert cases["sleeve-40-60"].required is True
    assert cases["sleeve-30-70"].required is False
    assert cases["sleeve-50-50"].required is False
    assert cases["sleeve-40-60"].day_weight == Decimal("0.40")
    assert cases["sleeve-40-60"].swing_weight == Decimal("0.60")


def test_no_order_validation_rejects_unblocked_virtual_orders():
    report = build_empty_plan_a_dry_run_report(trading_date=date(2026, 5, 11))
    unsafe_report = report.__class__(
        session=report.session,
        strategy_package=report.strategy_package,
        capital_cases=report.capital_cases,
        virtual_orders=(
            VirtualOrder(
                timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                symbol="A000001",
                strategy_group="day",
                side="buy",
                quantity=Decimal("1"),
                intended_price=Decimal("10000"),
                reason_code="test",
                hard_blocked=False,
            ),
        ),
    )

    with pytest.raises(ValueError, match="without hard-block"):
        validate_no_order_report(unsafe_report)


def test_plan_a_dry_run_cli_writes_report(tmp_path):
    output = tmp_path / "plan-a-session.json"

    exit_code = main(
        [
            "plan-a-dry-run",
            "--trading-date",
            "2026-05-11",
            "--session-id",
            "dry-run-test",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report"]["session"]["session_id"] == "dry-run-test"
    assert payload["summary"]["virtual_order_unblocked_count"] == 0


def test_field_dry_run_monitor_fans_out_primary_and_shadow_reports(tmp_path):
    csv_path = tmp_path / "A123456.csv"
    csv_path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20260511,1000,100,101,99,100,1000\n"
        "20260511,1515,100,101,99,100,1000\n"
        "20260512,1000,101,102,100,101,1000\n"
        "20260512,1515,101,102,100,101,1000\n",
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"
    output_dir = tmp_path / "field-monitor"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-test",
            "--path",
            str(csv_path),
            "--max-trading-days",
            "2",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["mode"] == "no-order"
    assert payload["order_hard_block"] is True
    assert payload["ready_for_broker_or_order_transmission"] is False
    assert payload["snapshot_contract"]["provider"] == "local-csv"
    assert payload["snapshot_contract"]["snapshot_count"] == 4
    assert {scenario["scenario_id"] for scenario in payload["scenarios"]} >= {
        "primary-current-seed-1m",
        "shadow-current-seed-2m",
        "shadow-future-seed-50m",
        "shadow-future-seed-70m",
        "shadow-slippage-stress-70m",
    }
    assert {scenario["strategy_package_id"] for scenario in payload["scenarios"]} == {"plan-a-idmom-d3-fsup-u1s1"}
    assert len(payload["scenario_results"]) == 5
    assert all(result["ready_for_broker_or_order_transmission"] is False for result in payload["scenario_results"])
    assert all(Path(result["report_path"]).exists() for result in payload["scenario_results"])
    reports_by_id = {
        result["scenario_id"]: json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
        for result in payload["scenario_results"]
    }
    assert reports_by_id["primary-current-seed-1m"]["report"]["starting_seed"] == "1000000"
    assert reports_by_id["shadow-current-seed-2m"]["report"]["starting_seed"] == "2000000"
    assert reports_by_id["shadow-future-seed-50m"]["report"]["starting_seed"] == "50000000"
    assert reports_by_id["shadow-future-seed-70m"]["report"]["starting_seed"] == "70000000"
    assert (output_dir / "daily-review" / "2026-05-12.md").exists()
    watchlist_full = output_dir / "watchlist" / "watchlist-full-2026-05-12.json"
    watchlist_summary = output_dir / "watchlist" / "watchlist-summary-2026-05-12.md"
    assert watchlist_full.exists()
    assert watchlist_summary.exists()
    watchlist_payload = json.loads(watchlist_full.read_text(encoding="utf-8"))
    assert watchlist_payload["scored_symbol_count"] == 1
    assert watchlist_payload["observation_count"] == 4
    assert watchlist_payload["first_observed_at"] == "2026-05-11T10:00:00+09:00"
    assert watchlist_payload["last_observed_at"] == "2026-05-12T15:15:00+09:00"
    assert len(watchlist_payload["top_cutoffs"]["top30"]) == 1
    assert watchlist_payload["symbol_summaries"][0]["observation_count"] == 4


def test_field_dry_run_monitor_consumes_kis_market_data_report_as_snapshot_stream(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "status": "passed",
                "mode": "network-read-only-prod",
                "universe_id": "kis-readonly-u1",
                "symbol_count": 1,
                "included_symbols": ["005930"],
                "members": [
                    {
                        "symbol": "005930",
                        "price": "70000",
                        "open": "69000",
                        "high": "70500",
                        "low": "68500",
                        "volume": "123456",
                        "traded_value": "8641920000",
                        "ask_volume": "1000",
                        "bid_volume": "2500",
                        "bid_ask_ratio": "2.500000",
                        "observed_at": "2026-05-12T01:00:00+00:00",
                        "price_observed_at": "2026-05-12T01:00:00+00:00",
                        "depth_observed_at": "2026-05-12T01:00:00.250000+00:00",
                        "paired_snapshot_gap_seconds": "0.250000",
                        "included": True,
                        "reason": "read-only quote ok",
                    }
                ],
                "api_flags": [],
                "read_call_count": 2,
                "budget_evidence": {
                    "provider": "KIS",
                    "within_budget": True,
                    "latency_bucket": "le_250ms",
                },
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-kis-snapshot",
            "--market-data-report",
            str(market_report),
            "--now",
            "2026-05-12T10:01:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "session_complete"
    assert payload["snapshot_contract"]["provider"] == "KIS"
    assert payload["snapshot_contract"]["snapshot_count"] == 1
    assert payload["snapshot_contract"]["read_call_count"] == 2
    assert len(payload["scenario_results"]) == 5
    watchlist_payload = json.loads(
        (tmp_path / "monitor" / "watchlist" / "watchlist-full-2026-05-12.json").read_text(encoding="utf-8")
    )
    assert watchlist_payload["rows"][0]["volume"] == 123456
    assert watchlist_payload["rows"][0]["traded_value"] == "8641920000"
    assert watchlist_payload["rows"][0]["open"] == "69000"
    assert watchlist_payload["rows"][0]["high"] == "70500"
    assert watchlist_payload["rows"][0]["low"] == "68500"
    assert watchlist_payload["rows"][0]["bid_ask_ratio"] == "2.500000"
    assert watchlist_payload["input_flag_counts"] == {}


def test_watchlist_history_replay_skips_rows_without_observed_timestamp(tmp_path):
    output_dir = tmp_path / "monitor"
    watchlist_dir = output_dir / "watchlist"
    watchlist_dir.mkdir(parents=True)
    (watchlist_dir / "watchlist-full-2026-05-12.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "symbol": "A005930",
                        "close": "70000",
                        "volume": "1000",
                    },
                    {
                        "symbol": "A000660",
                        "close": "120000",
                        "volume": "1000",
                        "observed_at": "2026-05-12T10:00:00+09:00",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    bars = _bars_from_watchlist_history(output_dir, trading_day=date(2026, 5, 12))

    assert [bar.symbol for bar in bars] == ["A000660"]
    assert bars[0].timestamp.isoformat() == "2026-05-12T10:00:00+09:00"


def test_field_dry_run_monitor_degrades_invalid_kis_snapshot_timestamp(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "status": "degraded",
                "mode": "network-read-only-prod",
                "universe_id": "kis-readonly-u1",
                "symbol_count": 1,
                "included_symbols": ["005930"],
                "members": [
                    {
                        "symbol": "005930",
                        "price": "70000",
                        "included": True,
                        "reason": "read-only quote ok",
                    }
                ],
                "api_flags": [],
                "read_call_count": 1,
                "budget_evidence": {"provider": "KIS", "within_budget": True},
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-invalid-timestamp",
            "--market-data-report",
            str(market_report),
            "--now",
            "2026-05-12T10:01:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert exit_code == 1
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "input_degraded"
    assert payload["snapshot_contract"]["snapshot_count"] == 0
    assert payload["scenario_results"] == []
    assert "invalid_market_timestamp" in payload["flags"]
    assert "input_contract_degraded" in payload["flags"]


def test_field_dry_run_monitor_combines_csv_warmup_with_kis_snapshot(tmp_path):
    csv_path = tmp_path / "A005930.csv"
    csv_path.write_text(
        "\n".join(
            [
                "date,time,open,high,low,close,volume",
                "20260511,1515,68000,69000,67000,68500,100000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "status": "passed",
                "mode": "network-read-only-prod",
                "universe_id": "kis-readonly-u1",
                "symbol_count": 1,
                "included_symbols": ["005930"],
                "members": [
                    {
                        "symbol": "005930",
                        "price": "70000",
                        "open": "69000",
                        "high": "70500",
                        "low": "68500",
                        "volume": "123456",
                        "traded_value": "8641920000",
                        "bid_ask_ratio": "2.500000",
                        "observed_at": "2026-05-12T01:00:00+00:00",
                        "price_observed_at": "2026-05-12T01:00:00+00:00",
                        "depth_observed_at": "2026-05-12T01:00:00.250000+00:00",
                        "paired_snapshot_gap_seconds": "0.250000",
                        "included": True,
                        "reason": "read-only quote ok",
                    }
                ],
                "api_flags": [],
                "read_call_count": 2,
                "budget_evidence": {"provider": "KIS", "within_budget": True},
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-kis-with-warmup",
            "--path",
            str(csv_path),
            "--market-data-report",
            str(market_report),
            "--now",
            "2026-05-12T10:01:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["snapshot_contract"]["provider"] == "KIS"
    assert payload["snapshot_contract"]["snapshot_count"] == 2
    watchlist_payload = json.loads(
        (tmp_path / "monitor" / "watchlist" / "watchlist-full-2026-05-12.json").read_text(encoding="utf-8")
    )
    timestamps = {row["timestamp"] for row in watchlist_payload["rows"]}
    assert "2026-05-11T15:15:00+09:00" in timestamps
    assert "2026-05-12T10:00:00+09:00" in timestamps
    assert watchlist_payload["strategy_warmup_diagnostics"]["status"] == "insufficient"
    assert watchlist_payload["strategy_warmup_diagnostics"]["flags"] == ["strategy_warmup_insufficient"]
    assert watchlist_payload["strategy_warmup_diagnostics"]["max_prior_sessions"] == 1


def test_field_dry_run_monitor_treats_naive_kis_snapshot_timestamp_as_kst(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "status": "passed",
                "mode": "network-read-only-prod",
                "universe_id": "kis-readonly-u1",
                "symbol_count": 1,
                "included_symbols": ["005930"],
                "members": [
                    {
                        "symbol": "005930",
                        "price": "70000",
                        "open": "69000",
                        "high": "70500",
                        "low": "68500",
                        "volume": "123456",
                        "traded_value": "8641920000",
                        "observed_at": "2026-05-12T10:00:00",
                        "price_observed_at": "2026-05-12T10:00:00",
                        "depth_observed_at": "2026-05-12T10:00:00.250000",
                        "paired_snapshot_gap_seconds": "0.250000",
                        "bid_ask_ratio": "2.500000",
                        "included": True,
                        "reason": "read-only quote ok",
                    }
                ],
                "api_flags": [],
                "read_call_count": 2,
                "budget_evidence": {"provider": "KIS", "within_budget": True},
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-naive-kst",
            "--market-data-report",
            str(market_report),
            "--now",
            "2026-05-12T10:01:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert exit_code == 0
    watchlist_payload = json.loads(
        (tmp_path / "monitor" / "watchlist" / "watchlist-full-2026-05-12.json").read_text(encoding="utf-8")
    )
    assert watchlist_payload["rows"][0]["timestamp"] == "2026-05-12T10:00:00+09:00"


def test_field_dry_run_monitor_stop_guard_writes_closed_status_without_scenarios(tmp_path):
    status_output = tmp_path / "current-status.json"
    output_dir = tmp_path / "monitor"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-after-close",
            "--watch",
            "--enforce-market-session-stop",
            "--market-session-date",
            "2026-05-12",
            "--market-session-stop-time",
            "15:35",
            "--now",
            "2026-05-12T16:20:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "session_closed"
    assert payload["flags"] == ["market_session_closed"]
    assert payload["order_hard_block"] is True
    assert payload["ready_for_broker_or_order_transmission"] is False
    assert payload["scenario_results"] == []
    assert (output_dir / "daily-review" / "2026-05-12.md").exists()


def test_field_dry_run_monitor_stop_guard_preserves_existing_evidence(tmp_path):
    status_output = tmp_path / "current-status.json"
    output_dir = tmp_path / "monitor"
    review_path = output_dir / "daily-review" / "2026-05-12.md"
    review_path.parent.mkdir(parents=True)
    review_path.write_text("existing daily review\n", encoding="utf-8")
    status_output.write_text(
        json.dumps(
            {
                "run_id": "monitor-after-close",
                "mode": "no-order",
                "status": "running",
                "generated_at": "2026-05-12T06:10:00+00:00",
                "order_hard_block": True,
                "ready_for_broker_or_order_transmission": False,
                "watch_contract_enabled": True,
                "market_schedule": "Korea regular session: pre-open checks, 09:00-15:15 monitor, post-close review",
                "snapshot_contract": {
                    "source": "field-monitor-local",
                    "provider": "KIS",
                    "snapshot_count": 42,
                    "symbol_count": 3,
                    "read_call_count": 7,
                    "observed_latency_ms": None,
                    "raw_response_persisted": False,
                    "note": "preserve me",
                },
                "scenarios": [],
                "scenario_results": [{"scenario_id": "primary-current-seed-1m", "virtual_order_count": 0}],
                "flags": [],
                "next_operator_review": "post-close daily review; shadow scenarios are not order authority",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-after-close",
            "--watch",
            "--enforce-market-session-stop",
            "--market-session-date",
            "2026-05-12",
            "--market-session-stop-time",
            "15:35",
            "--now",
            "2026-05-12T16:20:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "session_closed"
    assert payload["flags"] == ["market_session_closed"]
    assert payload["scenario_results"] == [{"scenario_id": "primary-current-seed-1m", "virtual_order_count": 0}]
    assert payload["snapshot_contract"]["snapshot_count"] == 42
    assert review_path.read_text(encoding="utf-8") == "existing daily review\n"


def test_field_dry_run_monitor_stop_guard_requires_session_date(tmp_path):
    with pytest.raises(ValueError, match="market-session-date"):
        main(
            [
                "field-dry-run-monitor",
                "--run-id",
                "monitor-missing-date",
                "--enforce-market-session-stop",
                "--now",
                "2026-05-13T00:10:00+09:00",
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )


def test_field_artifact_chain_runs_universe_kis_report_and_monitor_no_order(tmp_path, monkeypatch):
    csv_path = tmp_path / "A111111.csv"
    rows = ["date,time,open,high,low,close,volume"]
    start = date(2026, 4, 10)
    for index in range(20):
        day = start + timedelta(days=index)
        close = 100 + index
        rows.append(f"{day:%Y%m%d},1515,{close},{close + 4},{close - 4},{close},10000")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    universe_report = tmp_path / "field-universe.json"
    kis_symbols = tmp_path / "kis-symbols.txt"
    kis_report = tmp_path / "kis-readonly-universe.json"
    status_output = tmp_path / "current-status.json"

    def fake_build_kis_read_only_universe(**kwargs):
        assert kwargs["symbols"] == ("111111",)
        return api_smoke.KisReadOnlyUniverseResult(
            status="passed",
            mode="network-read-only-paper",
            universe_id="kis-readonly-u1",
            symbol_count=1,
            included_symbols=("111111",),
            excluded_symbols=(),
            members=(
                api_smoke.KisUniverseMember(
                    symbol="111111",
                    price="119",
                    included=True,
                    reason="read-only quote ok",
                    open="118",
                    high="120",
                    low="117",
                    volume="10000",
                    traded_value="1190000",
                    observed_at="2026-05-12T01:00:00+00:00",
                    price_observed_at="2026-05-12T01:00:00+00:00",
                    depth_observed_at="2026-05-12T01:00:00.250000+00:00",
                    paired_snapshot_gap_seconds="0.250000",
                    ask_volume="1000",
                    bid_volume="2500",
                    bid_ask_ratio="2.500000",
                ),
            ),
            api_flags=(),
            read_call_count=2,
            budget_evidence={
                "provider": "KIS",
                "within_budget": True,
                "latency_bucket": "le_250ms",
            },
            safety_boundary="read-only test",
        )

    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)

    assert (
        main(
            [
                "build-field-universe",
                "--target-date",
                "2026-05-12",
                "--path",
                str(csv_path),
                "--min-average-value",
                "1",
                "--min-atr-ratio",
                "0.01",
                "--min-prior-trading-days",
                "20",
                "--kis-symbol-list-output",
                str(kis_symbols),
                "--output",
                str(universe_report),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "kis-readonly-universe",
                "--symbol-list",
                str(kis_symbols),
                "--allow-network",
                "--run-network",
                "--output",
                str(kis_report),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "field-dry-run-monitor",
                "--run-id",
                "artifact-chain",
                "--market-data-report",
                str(kis_report),
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--status-output",
                str(status_output),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "session_complete"
    assert payload["snapshot_contract"]["provider"] == "KIS"
    assert payload["snapshot_contract"]["read_call_count"] == 2
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_field_run_main_entrypoint_runs_one_no_order_cycle_without_sleep(tmp_path, monkeypatch, capsys):
    symbol_list = tmp_path / "symbols.txt"
    symbol_list.write_text("111111\n", encoding="utf-8")
    quote_report = tmp_path / "kis-readonly-universe.json"
    status_output = tmp_path / "current-status.json"
    control_output = tmp_path / "field-run-control.json"
    output_dir = tmp_path / "monitor"
    calls = []
    token_cache = object()

    def fake_prewarm_kis_token_cache(**kwargs):
        calls.append(("auth", kwargs["endpoint_profile"]))
        return token_cache, api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=False,
            safety_boundary="read-only test",
        )

    def fake_build_kis_read_only_universe(**kwargs):
        calls.append(("quote", kwargs["symbols"]))
        assert calls[0] == ("auth", "prod")
        assert kwargs["symbols"] == ("111111",)
        assert kwargs["include_quote_depth"] is True
        assert kwargs["token_cache"] is token_cache
        return api_smoke.KisReadOnlyUniverseResult(
            status="passed",
            mode="network-read-only-prod",
            universe_id="kis-readonly-u1",
            symbol_count=1,
            included_symbols=("111111",),
            excluded_symbols=(),
            members=(
                api_smoke.KisUniverseMember(
                    symbol="111111",
                    price="119",
                    included=True,
                    reason="read-only quote ok",
                    open="118",
                    high="120",
                    low="117",
                    volume="10000",
                    traded_value="1190000",
                    observed_at="2026-05-12T01:00:00+00:00",
                    price_observed_at="2026-05-12T01:00:00+00:00",
                    depth_observed_at="2026-05-12T01:00:00.250000+00:00",
                    paired_snapshot_gap_seconds="0.250000",
                    ask_volume="1000",
                    bid_volume="2500",
                    bid_ask_ratio="2.500000",
                ),
            ),
            api_flags=(),
            read_call_count=2,
            budget_evidence={
                "source": "kis-readonly-universe-prod",
                "within_budget": True,
                "measured_read_calls": 2,
            },
            safety_boundary="read-only test",
        )

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-entry-smoke",
                "--symbol-list",
                str(symbol_list),
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--cycle-limit",
                "1",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(status_output),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    quote_payload = json.loads(quote_report.read_text(encoding="utf-8"))
    status_payload = json.loads(status_output.read_text(encoding="utf-8"))
    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert quote_payload["status"] == "passed"
    assert status_payload["order_hard_block"] is True
    assert control_payload["intraday_monitor_module"]["post_cycle_sleep_seconds"] == 0
    assert control_payload["ai_watch_mode"]["report_interval_seconds"] == 300
    assert control_payload["ai_watch_mode"]["does_not_throttle_intraday_monitor"] is True
    assert control_payload["extra"]["auth_preflight"]["status"] == "passed"
    stdout = capsys.readouterr().out
    assert "field_run_stage=cycle_start" in stdout
    assert "field_run_stage=quote_depth_start" in stdout
    assert "field_run_stage=quote_depth_done" in stdout
    assert "field_run_stage=monitor_start" in stdout
    assert "field_run_stage=monitor_done" in stdout
    assert "field_run_stage=cycle_limit_reached" in stdout


def test_field_run_continues_after_partial_quote_degradation_and_records_symbol(tmp_path, monkeypatch):
    symbol_list = tmp_path / "symbols.txt"
    symbol_list.write_text("111111\n", encoding="utf-8")
    quote_report = tmp_path / "kis-readonly-universe.json"
    status_output = tmp_path / "current-status.json"
    control_output = tmp_path / "field-run-control.json"
    output_dir = tmp_path / "monitor"
    quote_calls = 0
    monitor_calls = 0
    token_cache = object()

    def fake_prewarm_kis_token_cache(**kwargs):
        return token_cache, api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=False,
            safety_boundary="read-only test",
        )

    def fake_build_kis_read_only_universe(**kwargs):
        nonlocal quote_calls
        quote_calls += 1
        field_flags = ("field_data_incomplete:stck_prpr,stck_oprc,stck_hgpr,stck_lwpr,acml_vol,acml_tr_pbmn",)
        if quote_calls == 1:
            return api_smoke.KisReadOnlyUniverseResult(
                status="degraded",
                mode="network-read-only-prod",
                universe_id="kis-readonly-u1",
                symbol_count=1,
                included_symbols=(),
                excluded_symbols=(("111111", "api rate limit"),),
                members=(
                    api_smoke.KisUniverseMember(
                        symbol="111111",
                        price="",
                        included=False,
                        reason="api rate limit",
                        observed_at="2026-05-12T01:00:00+00:00",
                        price_observed_at="2026-05-12T01:00:00+00:00",
                        depth_observed_at="2026-05-12T01:00:00.010000+00:00",
                        paired_snapshot_gap_seconds="0.010000",
                        ask_volume="1000",
                        bid_volume="2500",
                        bid_ask_ratio="2.500000",
                        field_data_flags=field_flags,
                    ),
                ),
                api_flags=("api_rate_limit_risk",),
                read_call_count=2,
                budget_evidence={
                    "source": "kis-readonly-universe-prod",
                    "within_budget": False,
                    "measured_read_calls": 2,
                },
                safety_boundary="read-only test",
            )
        return api_smoke.KisReadOnlyUniverseResult(
            status="passed",
            mode="network-read-only-prod",
            universe_id="kis-readonly-u1",
            symbol_count=1,
            included_symbols=("111111",),
            excluded_symbols=(),
            members=(
                api_smoke.KisUniverseMember(
                    symbol="111111",
                    price="119",
                    included=True,
                    reason="read-only quote ok",
                    open="118",
                    high="120",
                    low="117",
                    volume="10000",
                    traded_value="1190000",
                    observed_at="2026-05-12T01:00:01+00:00",
                    price_observed_at="2026-05-12T01:00:01+00:00",
                    depth_observed_at="2026-05-12T01:00:01.010000+00:00",
                    paired_snapshot_gap_seconds="0.010000",
                    ask_volume="1000",
                    bid_volume="2500",
                    bid_ask_ratio="2.500000",
                ),
            ),
            api_flags=(),
            read_call_count=2,
            budget_evidence={
                "source": "kis-readonly-universe-prod",
                "within_budget": True,
                "measured_read_calls": 2,
            },
            safety_boundary="read-only test",
        )

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)
    def fake_monitor_command(args):
        nonlocal monitor_calls
        monitor_calls += 1
        return 0

    monkeypatch.setattr("zurini.cli.run_field_dry_run_monitor_command", fake_monitor_command)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "partial-degraded-continues",
                "--symbol-list",
                str(symbol_list),
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--cycle-limit",
                "2",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(status_output),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    quote_payload = json.loads(quote_report.read_text(encoding="utf-8"))
    assert quote_calls == 2
    assert monitor_calls == 1
    assert control_payload["status"] == "running"
    assert control_payload["cycle_count"] == 2
    assert control_payload["extra"]["degraded_symbols"] == []
    assert quote_payload["status"] == "passed"


def test_field_run_fails_closed_after_persistent_quote_degradation(tmp_path, monkeypatch):
    symbol_list = tmp_path / "symbols.txt"
    symbol_list.write_text("111111\n", encoding="utf-8")
    quote_report = tmp_path / "kis-readonly-universe.json"
    status_output = tmp_path / "current-status.json"
    control_output = tmp_path / "field-run-control.json"
    output_dir = tmp_path / "monitor"
    quote_calls = 0
    monitor_calls = 0
    token_cache = object()

    def fake_prewarm_kis_token_cache(**kwargs):
        return token_cache, api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=False,
            safety_boundary="read-only test",
        )

    def fake_build_kis_read_only_universe(**kwargs):
        nonlocal quote_calls
        quote_calls += 1
        return api_smoke.KisReadOnlyUniverseResult(
            status="degraded",
            mode="network-read-only-prod",
            universe_id="kis-readonly-u1",
            symbol_count=1,
            included_symbols=(),
            excluded_symbols=(("111111", "api rate limit"),),
            members=(
                api_smoke.KisUniverseMember(
                    symbol="111111",
                    price="",
                    included=False,
                    reason="api rate limit",
                    observed_at="2026-05-12T01:00:00+00:00",
                    price_observed_at="2026-05-12T01:00:00+00:00",
                    depth_observed_at="2026-05-12T01:00:00.010000+00:00",
                    paired_snapshot_gap_seconds="0.010000",
                    field_data_flags=("api_rate_limit_risk",),
                ),
            ),
            api_flags=("api_rate_limit_risk",),
            read_call_count=2,
            budget_evidence={
                "source": "kis-readonly-universe-prod",
                "within_budget": False,
                "measured_read_calls": 2,
            },
            safety_boundary="read-only test",
        )

    def fake_monitor_command(args):
        nonlocal monitor_calls
        monitor_calls += 1
        return 0

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)
    monkeypatch.setattr("zurini.cli.run_field_dry_run_monitor_command", fake_monitor_command)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "persistent-degraded-fails",
                "--symbol-list",
                str(symbol_list),
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--enforce-market-session-stop",
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--quote-degraded-retry-limit",
                "2",
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(status_output),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 1
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert quote_calls == 2
    assert monitor_calls == 0
    assert control_payload["status"] == "failed"
    assert control_payload["monitor_exit_status"] == "skipped"
    assert control_payload["extra"]["consecutive_degraded_quote_cycles"] == 2
    assert control_payload["extra"]["input_contract_action"] == "fail_closed_persistent_degraded_quote"


def test_field_run_marks_degraded_quote_cycle_limit_as_failed(tmp_path, monkeypatch):
    symbol_list = tmp_path / "symbols.txt"
    symbol_list.write_text("111111\n", encoding="utf-8")
    control_output = tmp_path / "field-run-control.json"
    token_cache = object()

    def fake_prewarm_kis_token_cache(**kwargs):
        return token_cache, api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=False,
            safety_boundary="read-only test",
        )

    def fake_build_kis_read_only_universe(**kwargs):
        return api_smoke.KisReadOnlyUniverseResult(
            status="degraded",
            mode="network-read-only-prod",
            universe_id="kis-readonly-u1",
            symbol_count=1,
            included_symbols=(),
            excluded_symbols=(("111111", "api rate limit"),),
            members=(),
            api_flags=("api_rate_limit_risk",),
            read_call_count=2,
            budget_evidence={
                "source": "kis-readonly-universe-prod",
                "within_budget": False,
                "measured_read_calls": 2,
            },
            safety_boundary="read-only test",
        )

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "degraded-cycle-limit-fails",
                "--symbol-list",
                str(symbol_list),
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--cycle-limit",
                "1",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--control-output",
                str(control_output),
                "--quote-report",
                str(tmp_path / "kis-readonly-universe.json"),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 1
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert control_payload["status"] == "failed"
    assert control_payload["monitor_exit_status"] == "skipped"
    assert control_payload["extra"]["input_contract_action"] == "fail_closed_degraded_quote_cycle_limit"


def test_field_run_fails_closed_when_monitor_cycle_fails(tmp_path, monkeypatch):
    symbol_list = tmp_path / "symbols.txt"
    symbol_list.write_text("111111\n", encoding="utf-8")
    quote_report = tmp_path / "kis-readonly-universe.json"
    control_output = tmp_path / "field-run-control.json"
    output_dir = tmp_path / "monitor"
    token_cache = object()

    def fake_prewarm_kis_token_cache(**kwargs):
        return token_cache, api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=False,
            safety_boundary="read-only test",
        )

    def fake_build_kis_read_only_universe(**kwargs):
        return api_smoke.KisReadOnlyUniverseResult(
            status="passed",
            mode="network-read-only-prod",
            universe_id="kis-readonly-u1",
            symbol_count=1,
            included_symbols=("111111",),
            excluded_symbols=(),
            members=(
                api_smoke.KisUniverseMember(
                    symbol="111111",
                    price="119",
                    included=True,
                    reason="read-only quote ok",
                    open="118",
                    high="120",
                    low="117",
                    volume="10000",
                    traded_value="1190000",
                    observed_at="2026-05-12T01:00:00+00:00",
                    price_observed_at="2026-05-12T01:00:00+00:00",
                    depth_observed_at="2026-05-12T01:00:00.010000+00:00",
                    paired_snapshot_gap_seconds="0.010000",
                    ask_volume="1000",
                    bid_volume="2500",
                    bid_ask_ratio="2.500000",
                ),
            ),
            api_flags=(),
            read_call_count=2,
            budget_evidence={
                "source": "kis-readonly-universe-prod",
                "within_budget": True,
                "measured_read_calls": 2,
            },
            safety_boundary="read-only test",
        )

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)
    monkeypatch.setattr("zurini.cli.run_field_dry_run_monitor_command", lambda args: 1)

    exit_code = main(
        [
            "field-run",
            "--run-id",
            "monitor-fail-closed",
            "--symbol-list",
            str(symbol_list),
            "--allow-network",
            "--run-network",
            "--confirm-prod-readonly",
            "--cycle-limit",
            "2",
            "--now",
            "2026-05-12T10:01:00+09:00",
            "--quote-report",
            str(quote_report),
            "--status-output",
            str(tmp_path / "current-status.json"),
            "--control-output",
            str(control_output),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 1
    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert control_payload["status"] == "failed"
    assert control_payload["cycle_count"] == 1
    assert control_payload["monitor_exit_status"] == 1


def _write_field_run_prior_csv(path: Path) -> None:
    path.write_text(
        "date,time,open,high,low,close,volume,value\n"
        "20260511,1000,100,110,90,100,1000000,100000000\n",
        encoding="utf-8",
    )


def _write_field_run_sixty_prior_csv(path: Path, *, target_date: date) -> None:
    trading_days: list[date] = []
    current = target_date - timedelta(days=1)
    while len(trading_days) < 60:
        if current.weekday() < 5:
            trading_days.append(current)
        current -= timedelta(days=1)
    rows = ["date,time,open,high,low,close,volume,value"]
    for index, trading_day in enumerate(reversed(trading_days), start=1):
        close = 1000 + index
        rows.append(
            f"{trading_day:%Y%m%d},1000,{close - 10},{close + 80},{close - 80},{close},100000000,100000000000"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_field_run_main_entrypoint_builds_universe_and_runs_monitor(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    _write_field_run_prior_csv(csv_path)
    universe_output = tmp_path / "field-universe.json"
    quote_report = tmp_path / "kis-readonly-universe.json"
    status_output = tmp_path / "current-status.json"
    control_output = tmp_path / "field-run-control.json"

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-builds-universe",
                "--build-universe",
                "--path",
                str(csv_path),
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
                "--min-prior-trading-days",
                "1",
                "--value-window",
                "1",
                "--sma-window",
                "1",
                "--atr-window",
                "1",
                "--min-average-value",
                "0",
                "--min-atr-ratio",
                "0",
                "--disable-close-above-sma",
                "--universe-output",
                str(universe_output),
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(status_output),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    universe_payload = json.loads(universe_output.read_text(encoding="utf-8"))
    quote_payload = json.loads(quote_report.read_text(encoding="utf-8"))
    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert universe_payload["report"]["kis_symbols"] == ["111111"]
    assert quote_payload["symbols"] == ["111111"]
    assert control_payload["extra"]["universe_report"]["path"] == str(universe_output)
    assert control_payload["extra"]["requested_symbol_count"] == 1


def test_field_run_main_entrypoint_auto_builds_universe_from_stored_data(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    _write_field_run_prior_csv(csv_path)
    path_list = tmp_path / "accepted-prior-warmup-paths-2026-05-12.txt"
    path_list.write_text(str(csv_path) + "\n", encoding="utf-8")
    universe_output = tmp_path / "field-universe.json"
    quote_report = tmp_path / "kis-readonly-universe.json"
    control_output = tmp_path / "field-run-control.json"

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-auto-builds-universe",
                "--path-list",
                str(path_list),
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
                "--min-prior-trading-days",
                "1",
                "--value-window",
                "1",
                "--sma-window",
                "1",
                "--atr-window",
                "1",
                "--min-average-value",
                "0",
                "--min-atr-ratio",
                "0",
                "--disable-close-above-sma",
                "--universe-output",
                str(universe_output),
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    universe_payload = json.loads(universe_output.read_text(encoding="utf-8"))
    quote_payload = json.loads(quote_report.read_text(encoding="utf-8"))
    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert universe_payload["report"]["kis_symbols"] == ["111111"]
    assert quote_payload["symbols"] == ["111111"]
    assert control_payload["extra"]["universe_report"]["selection_mode"] == "auto"
    assert control_payload["extra"]["universe_report"]["action"] == "built"
    assert control_payload["extra"]["universe_report"]["latest_prior_date"] == "2026-05-11"


def test_field_run_main_entrypoint_auto_builds_from_default_stored_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports" / "dry-run"
    csv_path = tmp_path / "data" / "A111111.csv"
    _write_field_run_sixty_prior_csv(csv_path, target_date=date(2026, 5, 12))
    path_list = reports_dir / "accepted-prior-warmup-paths-2026-05-12.txt"
    path_list.parent.mkdir(parents=True, exist_ok=True)
    path_list.write_text(str(csv_path) + "\n", encoding="utf-8")
    captured_monitor_args = {}

    def fake_monitor_pass(args):
        captured_monitor_args["path_list"] = args.path_list
        return 0

    monkeypatch.setattr("zurini.cli.run_field_dry_run_monitor_command", fake_monitor_pass)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-default-auto-builds-universe",
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
            ]
        )
        == 0
    )

    universe_output = reports_dir / "field-universe-2026-05-12.json"
    control_output = reports_dir / "field-run-control.json"
    universe_payload = json.loads(universe_output.read_text(encoding="utf-8"))
    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert universe_payload["report"]["kis_symbols"] == ["111111"]
    assert control_payload["extra"]["universe_report"]["selection_mode"] == "auto"
    assert control_payload["extra"]["universe_report"]["action"] == "built"
    assert control_payload["extra"]["universe_report"]["source_path_list"] == [
        "reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt"
    ]
    assert captured_monitor_args["path_list"] == [
        Path("reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt")
    ]


def test_field_run_main_entrypoint_auto_reuses_valid_universe_without_manual_option(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    universe_output = tmp_path / "field-universe.json"
    _write_field_run_universe_artifact(universe_output)
    csv_path = Path("data/A111111.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_field_run_sixty_prior_csv(csv_path, target_date=date(2026, 5, 12))
    path_list = Path("reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt")
    path_list.parent.mkdir(parents=True, exist_ok=True)
    path_list.write_text("data/A111111.csv\n", encoding="utf-8")
    quote_report = tmp_path / "kis-readonly-universe.json"
    control_output = tmp_path / "field-run-control.json"
    captured_monitor_args = {}

    def fake_monitor_pass(args):
        captured_monitor_args["path_list"] = args.path_list
        return 0

    monkeypatch.setattr("zurini.cli.run_field_dry_run_monitor_command", fake_monitor_pass)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-auto-reuses-universe",
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
                "--universe-output",
                str(universe_output),
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    quote_payload = json.loads(quote_report.read_text(encoding="utf-8"))
    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert quote_payload["symbols"] == ["111111"]
    assert control_payload["extra"]["universe_report"]["selection_mode"] == "auto"
    assert control_payload["extra"]["universe_report"]["action"] == "reused"
    assert control_payload["extra"]["universe_report"]["source_path_list"] == [
        "reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt"
    ]
    assert captured_monitor_args["path_list"] == [
        Path("reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt")
    ]


def test_field_run_main_entrypoint_reused_universe_records_explicit_path_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    universe_output = tmp_path / "field-universe.json"
    csv_path = tmp_path / "A111111.csv"
    _write_field_run_sixty_prior_csv(csv_path, target_date=date(2026, 5, 12))
    _write_field_run_universe_artifact(universe_output)
    control_output = tmp_path / "field-run-control.json"
    captured_monitor_args = {}

    def fake_monitor_pass(args):
        captured_monitor_args["path"] = args.path
        captured_monitor_args["path_list"] = args.path_list
        return 0

    monkeypatch.setattr("zurini.cli.run_field_dry_run_monitor_command", fake_monitor_pass)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-auto-reuses-universe-explicit-path",
                "--path",
                str(csv_path),
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
                "--universe-output",
                str(universe_output),
                "--quote-report",
                str(tmp_path / "kis-readonly-universe.json"),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert control_payload["extra"]["universe_report"]["source_action"] == "explicit"
    assert control_payload["extra"]["universe_report"]["source_path_list"] == [str(csv_path)]
    assert captured_monitor_args["path"] == [csv_path]
    assert captured_monitor_args["path_list"] == []


def test_field_run_auto_universe_custom_output_honors_daily_source_acceptance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "reports" / "dry-run"
    reports_dir.mkdir(parents=True, exist_ok=True)
    universe_output = tmp_path / "custom-field-universe.json"
    _write_field_run_universe_artifact(universe_output)
    (reports_dir / "kis-daily-bars.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "operational_acceptance": "rejected",
                "end_date": "2026-05-11",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-custom-output-rejects-bad-source",
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
                "--universe-output",
                str(universe_output),
                "--quote-report",
                str(tmp_path / "kis-readonly-universe.json"),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(tmp_path / "field-run-control.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 1
    )

    control_payload = json.loads((tmp_path / "field-run-control.json").read_text(encoding="utf-8"))
    assert control_payload["status"] == "failed"
    assert "daily source is not operationally accepted" in control_payload["extra"]["universe_error"]


def test_field_run_main_entrypoint_auto_reuse_fails_closed_without_warmup_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    universe_output = tmp_path / "field-universe.json"
    _write_field_run_universe_artifact(universe_output)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-auto-reuse-missing-warmup",
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
                "--universe-output",
                str(universe_output),
                "--quote-report",
                str(tmp_path / "kis-readonly-universe.json"),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(tmp_path / "field-run-control.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 1
    )

    control_payload = json.loads((tmp_path / "field-run-control.json").read_text(encoding="utf-8"))
    assert control_payload["status"] == "failed"
    assert "requires accepted warm-up path-list" in control_payload["extra"]["universe_error"]
    assert control_payload["extra"]["universe_report"] is None


def test_field_run_main_entrypoint_infers_stop_guard_date_from_now(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    universe_output = tmp_path / "field-universe.json"
    _write_field_run_universe_artifact(universe_output)
    csv_path = Path("data/A111111.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_field_run_sixty_prior_csv(csv_path, target_date=date(2026, 5, 12))
    path_list = Path("reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt")
    path_list.parent.mkdir(parents=True, exist_ok=True)
    path_list.write_text("data/A111111.csv\n", encoding="utf-8")
    control_output = tmp_path / "field-run-control.json"

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-auto-stop-date",
                "--now",
                "2026-05-12T16:00:00+09:00",
                "--enforce-market-session-stop",
                "--universe-output",
                str(universe_output),
                "--quote-report",
                str(tmp_path / "kis-readonly-universe.json"),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert control_payload["status"] == "stopped"
    assert control_payload["extra"]["stop_guard"]["session_date"] == "2026-05-12"
    assert control_payload["extra"]["universe_report"]["action"] == "reused"


def test_field_run_main_entrypoint_auto_fails_closed_without_universe_or_source(tmp_path):
    control_output = tmp_path / "field-run-control.json"

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-auto-universe-missing",
                "--market-session-date",
                "2026-06-30",
                "--now",
                "2026-06-30T10:01:00+09:00",
                "--cycle-limit",
                "1",
                "--universe-output",
                str(tmp_path / "missing-field-universe.json"),
                "--quote-report",
                str(tmp_path / "kis-readonly-universe.json"),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 1
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert control_payload["status"] == "failed"
    assert control_payload["quote_status"] == "skipped"
    assert control_payload["extra"]["universe_selection_mode"] == "auto"
    assert "no valid current universe artifact" in control_payload["extra"]["universe_error"]


def test_field_run_main_entrypoint_stops_after_universe_build_when_market_closed(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    _write_field_run_prior_csv(csv_path)
    universe_output = tmp_path / "field-universe.json"
    quote_report = tmp_path / "kis-readonly-universe.json"
    control_output = tmp_path / "field-run-control.json"

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-closed-market-stop",
                "--build-universe",
                "--path",
                str(csv_path),
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T16:00:00+09:00",
                "--enforce-market-session-stop",
                "--min-prior-trading-days",
                "1",
                "--value-window",
                "1",
                "--sma-window",
                "1",
                "--atr-window",
                "1",
                "--min-average-value",
                "0",
                "--min-atr-ratio",
                "0",
                "--disable-close-above-sma",
                "--universe-output",
                str(universe_output),
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert universe_output.exists()
    assert not quote_report.exists()
    assert control_payload["status"] == "stopped"
    assert control_payload["quote_status"] == "skipped"
    assert control_payload["cycle_count"] == 0
    assert control_payload["order_hard_block"] is True
    assert control_payload["ready_for_broker_or_order_transmission"] is False
    assert control_payload["extra"]["stop_guard"]["stop_time"] == "15:35"
    assert control_payload["extra"]["universe_report"]["path"] == str(universe_output)


def test_field_run_main_entrypoint_stops_after_universe_build_before_market_open(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    _write_field_run_prior_csv(csv_path)
    universe_output = tmp_path / "field-universe.json"
    quote_report = tmp_path / "kis-readonly-universe.json"
    control_output = tmp_path / "field-run-control.json"

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "main-before-market-stop",
                "--build-universe",
                "--path",
                str(csv_path),
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T08:30:00+09:00",
                "--enforce-market-session-stop",
                "--min-prior-trading-days",
                "1",
                "--value-window",
                "1",
                "--sma-window",
                "1",
                "--atr-window",
                "1",
                "--min-average-value",
                "0",
                "--min-atr-ratio",
                "0",
                "--disable-close-above-sma",
                "--universe-output",
                str(universe_output),
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(control_output),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert universe_output.exists()
    assert not quote_report.exists()
    assert control_payload["status"] == "stopped"
    assert control_payload["quote_status"] == "skipped"
    assert control_payload["cycle_count"] == 0
    assert control_payload["extra"]["stop_guard"]["reason"] == "market-session-not-open"
    assert control_payload["extra"]["stop_guard"]["start_time"] == "09:00"
    assert control_payload["extra"]["universe_report"]["path"] == str(universe_output)


def test_field_run_future_session_waits_before_auth_or_universe(tmp_path, monkeypatch):
    control_output = tmp_path / "field-run-control.json"
    auth_calls = 0

    def fake_prewarm_kis_token_cache(**kwargs):
        nonlocal auth_calls
        auth_calls += 1
        raise AssertionError("auth preflight must wait for the target session prewarm window")

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "future-session-wait-before-auth",
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--market-session-date",
                "2026-05-18",
                "--now",
                "2026-05-15T12:14:00+09:00",
                "--enforce-market-session-stop",
                "--control-output",
                str(control_output),
                "--quote-report",
                str(tmp_path / "kis-readonly-universe.json"),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert auth_calls == 0
    assert control_payload["status"] == "waiting"
    assert control_payload["quote_status"] == "skipped"
    assert control_payload["cycle_count"] == 0
    assert control_payload["extra"]["stop_guard"]["reason"] == "token-prewarm-not-open"
    assert control_payload["extra"]["stop_guard"]["session_date"] == "2026-05-18"
    assert control_payload["extra"]["stop_guard"]["prewarm_time"] == "08:30"
    assert control_payload["extra"]["universe_report"] is None


def test_field_run_offline_future_session_does_not_wait_for_token_prewarm(tmp_path, monkeypatch):
    control_output = tmp_path / "field-run-control.json"
    auth_calls = 0

    def fake_prewarm_kis_token_cache(**kwargs):
        nonlocal auth_calls
        auth_calls += 1
        raise AssertionError("offline field-run must not prewarm KIS auth")

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "offline-future-session-no-token-wait",
                "--symbol",
                "005930",
                "--market-session-date",
                "2026-05-18",
                "--now",
                "2026-05-15T12:14:00+09:00",
                "--enforce-market-session-stop",
                "--control-output",
                str(control_output),
                "--quote-report",
                str(tmp_path / "kis-readonly-universe.json"),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert auth_calls == 0
    assert control_payload["status"] == "stopped"
    assert control_payload["extra"]["stop_guard"]["reason"] == "market-session-not-open"
    assert control_payload["extra"]["universe_report"] is None


def test_field_run_network_mode_fails_before_universe_when_auth_preflight_fails(tmp_path, monkeypatch):
    csv_path = tmp_path / "A111111.csv"
    _write_field_run_prior_csv(csv_path)
    universe_output = tmp_path / "field-universe.json"
    control_output = tmp_path / "field-run-control.json"

    def fake_prewarm_kis_token_cache(**kwargs):
        return None, api_smoke.KisAuthPreflightResult(
            status="failed",
            mode="network-read-only-auth-prod",
            api_flags=("api_auth_error",),
            read_call_count=1,
            token_present=False,
            from_cache=False,
            safety_boundary="read-only test",
        )

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "auth-first-fail",
                "--build-universe",
                "--path",
                str(csv_path),
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--cycle-limit",
                "1",
                "--now",
                "2026-05-12T08:30:00+09:00",
                "--universe-output",
                str(universe_output),
                "--control-output",
                str(control_output),
            ]
        )
        == 1
    )

    control_payload = json.loads(control_output.read_text(encoding="utf-8"))
    assert not universe_output.exists()
    assert control_payload["status"] == "failed"
    assert control_payload["extra"]["auth_preflight"]["status"] == "failed"
    assert control_payload["extra"]["requested_symbol_count"] == 0


def test_field_run_rejects_degraded_daily_bar_collection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured_daily_args = {}
    token_cache = object()

    class FakeResult:
        def __init__(self, payload):
            self._payload = payload

        def as_dict(self):
            return self._payload

    def fake_prewarm_kis_token_cache(**kwargs):
        return token_cache, api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=True,
            safety_boundary="read-only test",
        )

    def fake_build_kis_stock_master(*, markets):
        assert markets == ("KOSPI", "KOSDAQ")
        return FakeResult(
            {
                "status": "passed",
                "mode": "network-read-only-stock-master",
                "included_symbols": ["111111"],
                "members": [{"symbol": "111111", "name": "TEST", "market": "KOSPI", "included": True}],
                "api_flags": [],
            }
        )

    def fake_build_kis_daily_bars(**kwargs):
        captured_daily_args.update(kwargs)
        trading_dates = []
        current = date(2026, 5, 11)
        while len(trading_dates) < 60:
            if current.weekday() < 5:
                trading_dates.append(current)
            current -= timedelta(days=1)
        rows = []
        for index, trading_date in enumerate(sorted(trading_dates)):
            close = 1000 + index
            rows.append(
                {
                    "trading_date": trading_date.isoformat(),
                    "open": str(close - 10),
                    "high": str(close + 80),
                    "low": str(close - 80),
                    "close": str(close),
                    "volume": "100000000",
                    "traded_value": "100000000000",
                }
            )
        return FakeResult(
            {
                "status": "degraded",
                "mode": "network-read-only-daily-bars-prod",
                "included_symbols": ["111111"],
                "excluded_symbols": [["222222", "insufficient KIS daily rows: 0 < 60"]],
                "latest_prior_date": "2026-05-11",
                "api_flags": ["api_schema_mismatch"],
                "members": [
                    {"symbol": "111111", "included": True, "reason": "ok", "rows": rows},
                    {"symbol": "222222", "included": False, "reason": "insufficient KIS daily rows: 0 < 60", "rows": []},
                ],
            }
        )

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_stock_master", fake_build_kis_stock_master)
    monkeypatch.setattr("zurini.cli.build_kis_daily_bars", fake_build_kis_daily_bars)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "auto-collects-source",
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--now",
                "2026-05-12T16:00:00+09:00",
                "--enforce-market-session-stop",
            ]
        )
        == 1
    )

    reports_dir = Path("reports/dry-run")
    daily_report = json.loads((reports_dir / "kis-daily-bars.json").read_text(encoding="utf-8"))
    control_payload = json.loads((reports_dir / "field-run-control.json").read_text(encoding="utf-8"))
    assert (reports_dir / "kis-source-symbols.txt").read_text(encoding="utf-8") == "111111\n"
    assert daily_report["status"] == "failed"
    assert daily_report["operational_acceptance"] == "rejected"
    assert daily_report["api_flags"] == ["api_schema_mismatch"]
    assert daily_report["diagnostic_api_flags"] == ["api_schema_mismatch"]
    assert daily_report["included_symbols"] == ["111111"]
    assert daily_report["excluded_symbols"] == [["222222", "insufficient KIS daily rows: 0 < 60"]]
    assert daily_report["csv_file_count"] == 0
    path_list = reports_dir / "accepted-prior-warmup-paths-2026-05-12.txt"
    assert not path_list.exists()
    assert not (reports_dir / "field-universe-2026-05-12.json").exists()
    assert captured_daily_args["symbols"] == ("111111",)
    assert captured_daily_args["end_date"] == date(2026, 5, 11)
    assert captured_daily_args["token_cache"] is token_cache
    assert control_payload["status"] == "failed"
    assert control_payload["quote_status"] == "skipped"
    assert control_payload["extra"]["auth_preflight"]["status"] == "passed"
    assert control_payload["extra"]["requested_symbol_count"] == 0
    assert "KIS daily-bar collection failed" in control_payload["extra"]["universe_error"]


def test_field_run_rejects_partial_incremental_daily_bar_collection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = Path("reports/dry-run")
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "kis-source-symbols.txt").write_text("111111\n222222\n", encoding="utf-8")
    current_csv = Path("data/raw/kis/daily-bars/202605/A111111.csv")
    current_csv.parent.mkdir(parents=True, exist_ok=True)
    _write_field_run_sixty_prior_csv(current_csv, target_date=date(2026, 5, 12))
    captured_daily_args = {}

    class FakeResult:
        def __init__(self, payload):
            self._payload = payload

        def as_dict(self):
            return self._payload

    def fake_prewarm_kis_token_cache(**kwargs):
        return object(), api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=True,
            safety_boundary="read-only test",
        )

    def fake_build_kis_daily_bars(**kwargs):
        captured_daily_args.update(kwargs)
        return FakeResult(
            {
                "status": "failed",
                "mode": "network-read-only-daily-bars-prod",
                "included_symbols": [],
                "excluded_symbols": [["222222", "api timeout"]],
                "latest_prior_date": None,
                "api_flags": ["api_timeout"],
                "members": [{"symbol": "222222", "included": False, "reason": "api timeout", "rows": []}],
                "read_call_count": 1,
            }
        )

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_daily_bars", fake_build_kis_daily_bars)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "auto-rejects-partial-incremental-source",
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--now",
                "2026-05-12T16:00:00+09:00",
                "--enforce-market-session-stop",
            ]
        )
        == 1
    )

    daily_report = json.loads((reports_dir / "kis-daily-bars.json").read_text(encoding="utf-8"))
    control_payload = json.loads((reports_dir / "field-run-control.json").read_text(encoding="utf-8"))
    assert captured_daily_args["symbols"] == ("222222",)
    assert daily_report["status"] == "failed"
    assert daily_report["operational_acceptance"] == "rejected"
    assert daily_report["api_flags"] == ["api_timeout"]
    assert daily_report["included_symbols"] == ["111111"]
    assert ["222222", "api timeout"] in daily_report["excluded_symbols"]
    assert not (reports_dir / "accepted-prior-warmup-paths-2026-05-12.txt").exists()
    assert control_payload["status"] == "failed"
    assert "KIS daily-bar collection failed" in control_payload["extra"]["universe_error"]


def test_field_run_auto_collects_only_missing_prior_gap_when_history_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = Path("reports/dry-run")
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "kis-source-symbols.txt").write_text("111111\n", encoding="utf-8")
    csv_path = Path("data/raw/kis/daily-bars/202605/A111111.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    trading_dates = []
    current = date(2026, 5, 13)
    while len(trading_dates) < 60:
        if current.weekday() < 5:
            trading_dates.append(current)
        current -= timedelta(days=1)
    csv_rows = ["date,time,open,high,low,close,volume,value"]
    for index, trading_date in enumerate(sorted(trading_dates)):
        close = 1000 + index
        csv_rows.append(
            f"{trading_date:%Y%m%d},1515,{close - 10},{close + 80},{close - 80},{close},100000000,100000000000"
        )
    csv_path.write_text("\n".join(csv_rows) + "\n", encoding="utf-8")
    captured_daily_args = {}

    class FakeResult:
        def __init__(self, payload):
            self._payload = payload

        def as_dict(self):
            return self._payload

    def fake_prewarm_kis_token_cache(**kwargs):
        return object(), api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=True,
            safety_boundary="read-only test",
        )

    def fail_if_refreshing_stock_master(*args, **kwargs):
        raise AssertionError("existing symbol list should be reused")

    def fake_build_kis_daily_bars(**kwargs):
        captured_daily_args.update(kwargs)
        return FakeResult(
            {
                "status": "passed",
                "mode": "network-read-only-daily-bars-prod",
                "included_symbols": ["111111"],
                "excluded_symbols": [],
                "latest_prior_date": "2026-05-14",
                "api_flags": [],
                "read_call_count": 2,
                "members": [
                    {
                        "symbol": "111111",
                        "included": True,
                        "reason": "ok",
                        "rows": [
                            {
                                "trading_date": "2026-05-14",
                                "open": "1050",
                                "high": "1150",
                                "low": "950",
                                "close": "1100",
                                "volume": "100000000",
                                "traded_value": "110000000000",
                            }
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_stock_master", fail_if_refreshing_stock_master)
    monkeypatch.setattr("zurini.cli.build_kis_daily_bars", fake_build_kis_daily_bars)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "auto-collects-prior-gap",
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--now",
                "2026-05-15T16:00:00+09:00",
                "--enforce-market-session-stop",
            ]
        )
        == 0
    )

    daily_report = json.loads((reports_dir / "kis-daily-bars.json").read_text(encoding="utf-8"))
    updated_csv = csv_path.read_text(encoding="utf-8")
    assert captured_daily_args["symbols"] == ("111111",)
    assert captured_daily_args["start_date"] == date(2026, 5, 14)
    assert captured_daily_args["end_date"] == date(2026, 5, 14)
    assert captured_daily_args["min_trading_days"] == 1
    assert daily_report["collection_scope"] == "incremental"
    assert daily_report["full_refresh_symbol_count"] == 0
    assert daily_report["incremental_symbol_count"] == 1
    assert "20260513,1515" in updated_csv
    assert "20260514,1515" in updated_csv
    assert (reports_dir / "field-universe-2026-05-15.json").exists()


def test_field_run_auto_collection_scope_starts_after_latest_local_daily_bar(tmp_path):
    csv_path = tmp_path / "data/raw/kis/daily-bars/202605/A111111.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    trading_dates = []
    current = date(2026, 5, 12)
    while len(trading_dates) < 60:
        if current.weekday() < 5:
            trading_dates.append(current)
        current -= timedelta(days=1)
    csv_path.write_text(
        "\n".join(
            ["date,time,open,high,low,close,volume,value"]
            + [f"{trading_date:%Y%m%d},1515,1000,1100,900,1050,100000000,100000000000" for trading_date in trading_dates]
        )
        + "\n",
        encoding="utf-8",
    )

    full_symbols, incremental_groups = _classify_daily_bar_collection_scope(
        ("111111",),
        output_root=tmp_path / "data/raw/kis/daily-bars",
        target_date=date(2026, 5, 15),
        expected_prior_date=date(2026, 5, 14),
        min_prior_trading_days=60,
    )

    assert full_symbols == ()
    assert incremental_groups == {date(2026, 5, 13): ("111111",)}


def test_field_run_auto_collection_scope_starts_at_sparse_missing_trading_day(tmp_path):
    csv_path = tmp_path / "data/raw/kis/daily-bars/202605/A111111.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    trading_dates = []
    current = date(2026, 5, 14)
    while len(trading_dates) < 65:
        if current.weekday() < 5 and current != date(2026, 5, 4):
            trading_dates.append(current)
        current -= timedelta(days=1)
    csv_path.write_text(
        "\n".join(
            ["date,time,open,high,low,close,volume,value"]
            + [f"{trading_date:%Y%m%d},1515,1000,1100,900,1050,100000000,100000000000" for trading_date in trading_dates]
        )
        + "\n",
        encoding="utf-8",
    )

    full_symbols, incremental_groups = _classify_daily_bar_collection_scope(
        ("111111",),
        output_root=tmp_path / "data/raw/kis/daily-bars",
        target_date=date(2026, 5, 15),
        expected_prior_date=date(2026, 5, 14),
        min_prior_trading_days=60,
        expected_trading_dates=(date(2026, 5, 4), date(2026, 5, 8), date(2026, 5, 11), date(2026, 5, 14)),
    )

    assert full_symbols == ()
    assert incremental_groups == {date(2026, 5, 4): ("111111",)}


def _install_field_run_auto_collection_fakes(
    monkeypatch,
    captured_daily_args: dict[str, object],
    *,
    captured_stock_master: dict[str, object] | None = None,
    stock_symbol: str = "111111",
) -> None:
    class FakeResult:
        def __init__(self, payload):
            self._payload = payload

        def as_dict(self):
            return self._payload

    def fake_prewarm_kis_token_cache(**kwargs):
        return object(), api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=True,
            safety_boundary="read-only test",
        )

    def fake_build_kis_stock_master(*, markets):
        if captured_stock_master is not None:
            captured_stock_master["called"] = True
        assert markets == ("KOSPI", "KOSDAQ")
        return FakeResult(
            {
                "status": "passed",
                "mode": "network-read-only-stock-master",
                "included_symbols": [stock_symbol],
                "members": [{"symbol": stock_symbol, "name": "TEST", "market": "KOSPI", "included": True}],
                "api_flags": [],
            }
        )

    def fake_build_kis_daily_bars(**kwargs):
        captured_daily_args.update(kwargs)
        trading_dates = []
        current = date(2026, 5, 11)
        while len(trading_dates) < 60:
            if current.weekday() < 5:
                trading_dates.append(current)
            current -= timedelta(days=1)
        rows = []
        for index, trading_date in enumerate(sorted(trading_dates)):
            close = 1000 + index
            rows.append(
                {
                    "trading_date": trading_date.isoformat(),
                    "open": str(close - 10),
                    "high": str(close + 80),
                    "low": str(close - 80),
                    "close": str(close),
                    "volume": "100000000",
                    "traded_value": "100000000000",
                }
            )
        return FakeResult(
            {
                "status": "passed",
                "mode": "network-read-only-daily-bars-prod",
                "included_symbols": [stock_symbol],
                "excluded_symbols": [],
                "latest_prior_date": "2026-05-11",
                "api_flags": [],
                "members": [{"symbol": stock_symbol, "included": True, "reason": "ok", "rows": rows}],
            }
        )

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_stock_master", fake_build_kis_stock_master)
    monkeypatch.setattr("zurini.cli.build_kis_daily_bars", fake_build_kis_daily_bars)


def test_field_run_auto_reuses_valid_universe_before_network_source_collection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    universe_output = Path("reports/dry-run/field-universe-2026-05-12.json")
    universe_output.parent.mkdir(parents=True, exist_ok=True)
    _write_field_run_universe_artifact(universe_output)
    csv_path = Path("data/A111111.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_field_run_sixty_prior_csv(csv_path, target_date=date(2026, 5, 12))
    path_list = Path("reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt")
    path_list.write_text("data/A111111.csv\n", encoding="utf-8")

    def fake_prewarm_kis_token_cache(**kwargs):
        return object(), api_smoke.KisAuthPreflightResult(
            status="passed",
            mode="network-read-only-auth-prod",
            api_flags=(),
            read_call_count=1,
            token_present=True,
            from_cache=True,
            safety_boundary="read-only test",
        )

    def fail_if_collecting_source(*args, **kwargs):
        raise AssertionError("valid universe artifact must be checked before network source collection")

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_stock_master", fail_if_collecting_source)
    monkeypatch.setattr("zurini.cli.build_kis_daily_bars", fail_if_collecting_source)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "auto-reuses-before-collect",
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--now",
                "2026-05-12T16:00:00+09:00",
                "--enforce-market-session-stop",
            ]
        )
        == 0
    )

    control_payload = json.loads(Path("reports/dry-run/field-run-control.json").read_text(encoding="utf-8"))
    assert control_payload["status"] == "stopped"
    assert control_payload["extra"]["universe_report"]["action"] == "reused"
    assert control_payload["extra"]["universe_report"]["source_path_list"] == [
        "reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt"
    ]
    assert not Path("reports/dry-run/kis-daily-bars.json").exists()


def test_field_run_rebuilds_from_stored_source_when_reused_universe_warmup_symbols_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    universe_output = Path("reports/dry-run/field-universe-2026-05-12.json")
    universe_output.parent.mkdir(parents=True, exist_ok=True)
    _write_field_run_universe_artifact(universe_output, kis_symbols=("111111",))
    csv_path = Path("data/A222222.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_field_run_sixty_prior_csv(csv_path, target_date=date(2026, 5, 12))
    path_list = Path("reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt")
    path_list.write_text("data/A222222.csv\n", encoding="utf-8")

    def fail_if_collecting_source(*args, **kwargs):
        raise AssertionError("stored warm-up source rebuild must not collect network source")

    monkeypatch.setattr("zurini.cli.build_kis_stock_master", fail_if_collecting_source)
    monkeypatch.setattr("zurini.cli.build_kis_daily_bars", fail_if_collecting_source)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                    "auto-rebuilds-wrong-symbol-warmup",
                "--now",
                "2026-05-12T16:00:00+09:00",
                "--enforce-market-session-stop",
            ]
        )
        == 0
    )

    control_payload = json.loads(Path("reports/dry-run/field-run-control.json").read_text(encoding="utf-8"))
    assert control_payload["status"] == "stopped"
    assert control_payload["extra"]["universe_report"]["action"] == "built"
    assert control_payload["extra"]["universe_report"]["source_path_list"] == [
        "reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt"
    ]
    assert control_payload["extra"]["universe_report"]["kis_symbols"] == ["222222"]
    assert not Path("reports/dry-run/kis-daily-bars.json").exists()


def test_field_run_auto_collects_when_stored_source_is_invalid_in_network_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = Path("reports/dry-run")
    reports_dir.mkdir(parents=True, exist_ok=True)
    bad_path_list = reports_dir / "accepted-prior-warmup-paths-2026-05-12.txt"
    bad_path_list.write_text("missing/A111111.csv\n", encoding="utf-8")
    captured_daily_args: dict[str, object] = {}
    _install_field_run_auto_collection_fakes(monkeypatch, captured_daily_args)

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "auto-collects-after-invalid-source",
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--now",
                "2026-05-12T16:00:00+09:00",
                "--enforce-market-session-stop",
            ]
        )
        == 0
    )

    control_payload = json.loads((reports_dir / "field-run-control.json").read_text(encoding="utf-8"))
    assert captured_daily_args["symbols"] == ("111111",)
    assert control_payload["status"] == "stopped"
    assert control_payload["extra"]["universe_report"]["action"] == "built"
    assert control_payload["extra"]["universe_report"]["source_action"] == "collected"
    assert "rejected_stored_source_error" in control_payload["extra"]["universe_report"]
    assert "missing/A111111.csv" in control_payload["extra"]["universe_report"]["rejected_stored_source_error"]


def test_field_run_auto_refreshes_stock_master_when_recovering_invalid_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports_dir = Path("reports/dry-run")
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "accepted-prior-warmup-paths-2026-05-12.txt").write_text(
        "missing/A222222.csv\n",
        encoding="utf-8",
    )
    (reports_dir / "kis-source-symbols.txt").write_text("222222\n", encoding="utf-8")
    captured_daily_args: dict[str, object] = {}
    captured_stock_master: dict[str, object] = {}
    _install_field_run_auto_collection_fakes(
        monkeypatch,
        captured_daily_args,
        captured_stock_master=captured_stock_master,
        stock_symbol="111111",
    )

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "auto-refreshes-master-after-invalid-source",
                "--allow-network",
                "--run-network",
                "--confirm-prod-readonly",
                "--now",
                "2026-05-12T16:00:00+09:00",
                "--enforce-market-session-stop",
            ]
        )
        == 0
    )

    control_payload = json.loads((reports_dir / "field-run-control.json").read_text(encoding="utf-8"))
    assert captured_stock_master["called"] is True
    assert (reports_dir / "kis-source-symbols.txt").read_text(encoding="utf-8") == "111111\n"
    assert captured_daily_args["symbols"] == ("111111",)
    assert control_payload["extra"]["requested_symbol_count"] == 1
    assert control_payload["extra"]["universe_report"]["source_action"] == "collected"


def test_field_run_requires_stop_guard_for_unbounded_continuous_loop():
    with pytest.raises(ValueError, match="continuous field-run"):
        main(
            [
                "field-run",
                "--run-id",
                "unsafe-loop",
                "--symbol",
                "111111",
            ]
        )


def _write_field_run_universe_artifact(
    path: Path,
    *,
    target_date: str = "2026-05-12",
    latest_prior_date: str = "2026-05-11",
    kis_symbols: tuple[str, ...] = ("111111",),
) -> None:
    lag_days = (date.fromisoformat(target_date) - date.fromisoformat(latest_prior_date)).days
    path.write_text(
        json.dumps(
            {
                "summary": {
                    "universe_id": "field-u1-prior-only",
                    "target_date": target_date,
                    "mode": "prior-only-read-only",
                    "included_count": len(kis_symbols),
                    "excluded_count": 0,
                    "ready_for_broker_or_order_transmission": False,
                    "latest_prior_date": latest_prior_date,
                    "latest_prior_lag_days": lag_days,
                    "source_date_lag_days": lag_days,
                    "source_fresh": True,
                },
                "report": {
                    "universe_id": "field-u1-prior-only",
                    "target_date": target_date,
                    "generated_at": "2026-05-12T09:59:00+09:00",
                    "mode": "prior-only-read-only",
                    "construction_rule": "U1",
                    "prior_only_cutoff": target_date,
                    "included_symbols": [f"A{symbol}" for symbol in kis_symbols],
                    "kis_symbols": list(kis_symbols),
                    "excluded_symbols": [],
                    "members": [],
                    "parameters": {"max_symbols": len(kis_symbols)},
                    "safety_boundary": "read-only prior-data universe; no broker order, account, balance, credential, or real-fill calls",
                    "latest_prior_date": latest_prior_date,
                    "latest_prior_lag_days": lag_days,
                    "source_date_lag_days": lag_days,
                    "source_fresh": True,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_field_run_rejects_universe_report_wrong_target_date(tmp_path):
    universe_report = tmp_path / "field-universe.json"
    _write_field_run_universe_artifact(universe_report, target_date="2026-05-11", latest_prior_date="2026-05-08")

    with pytest.raises(ValueError, match="target_date"):
        main(
            [
                "field-run",
                "--run-id",
                "wrong-universe-target",
                "--symbol",
                "111111",
                "--universe-report",
                str(universe_report),
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
            ]
        )


def test_field_run_rejects_universe_report_wrong_latest_prior_date(tmp_path):
    universe_report = tmp_path / "field-universe.json"
    _write_field_run_universe_artifact(universe_report, target_date="2026-05-12", latest_prior_date="2026-05-08")

    with pytest.raises(ValueError, match="latest_prior_date"):
        main(
            [
                "field-run",
                "--run-id",
                "wrong-universe-prior",
                "--symbol",
                "111111",
                "--universe-report",
                str(universe_report),
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
            ]
        )


def test_field_run_does_not_allow_disabling_expected_prior_date(tmp_path):
    with pytest.raises(SystemExit):
        main(
            [
                "field-run",
                "--run-id",
                "no-disable-prior",
                "--symbol",
                "111111",
                "--disable-expected-prior-date",
                "--cycle-limit",
                "1",
            ]
        )


def test_field_run_rejects_universe_report_symbol_mismatch(tmp_path):
    universe_report = tmp_path / "field-universe.json"
    _write_field_run_universe_artifact(universe_report, kis_symbols=("222222",))

    with pytest.raises(ValueError, match="kis_symbols"):
        main(
            [
                "field-run",
                "--run-id",
                "wrong-universe-symbols",
                "--symbol",
                "111111",
                "--universe-report",
                str(universe_report),
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
            ]
        )


def test_field_run_derives_symbols_from_universe_report_without_manual_symbol_list(tmp_path):
    universe_report = tmp_path / "field-universe.json"
    _write_field_run_universe_artifact(universe_report)
    quote_report = tmp_path / "kis-readonly-universe.json"

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "universe-derived-symbols",
                "--universe-report",
                str(universe_report),
                "--market-session-date",
                "2026-05-12",
                "--now",
                "2026-05-12T10:01:00+09:00",
                "--cycle-limit",
                "1",
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(tmp_path / "field-run-control.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )
        == 0
    )

    quote_payload = json.loads(quote_report.read_text(encoding="utf-8"))
    assert quote_payload["symbols"] == ["111111"]


def test_field_run_uses_positive_intraday_watchlist_for_1510_swing_focus(tmp_path):
    symbol_list = tmp_path / "symbols.txt"
    symbol_list.write_text("111111\n222222\n333333\n", encoding="utf-8")
    output_dir = tmp_path / "monitor"
    watchlist_dir = output_dir / "watchlist"
    watchlist_dir.mkdir(parents=True)
    (watchlist_dir / "watchlist-full-2026-05-12.json").write_text(
        json.dumps(
            {
                "symbol_summaries": [
                    {"symbol": "A111111", "intraday_change_pct": "9", "passed_count": 0},
                    {"symbol": "A222222", "intraday_change_pct": "5", "passed_count": 99},
                    {"symbol": "A333333", "intraday_change_pct": "-10", "passed_count": 100},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    quote_report = tmp_path / "kis-readonly-universe.json"

    assert (
        main(
            [
                "field-run",
                "--run-id",
                "swing-focus-smoke",
                "--symbol-list",
                str(symbol_list),
                "--cycle-limit",
                "1",
                "--max-swing-focus-symbols",
                "1",
                "--now",
                "2026-05-12T15:11:00+09:00",
                "--quote-report",
                str(quote_report),
                "--status-output",
                str(tmp_path / "current-status.json"),
                "--control-output",
                str(tmp_path / "field-run-control.json"),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    quote_payload = json.loads(quote_report.read_text(encoding="utf-8"))
    assert quote_payload["symbols"] == ["111111"]


def test_dry_run_without_blacklist_artifact_does_not_fail_closed_risk_state():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
    ]

    report = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_RiskAwareEntryStrategy,
    )

    assert [order.reason_code for order in report.virtual_orders] == ["risk-aware-entry"]


def test_field_dry_run_monitor_uses_report_budget_evidence_for_many_kis_symbols(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "status": "passed",
                "mode": "network-read-only-prod",
                "universe_id": "kis-readonly-u1",
                "symbol_count": 20,
                "included_symbols": [f"{index:06d}" for index in range(1, 21)],
                "members": [
                    {
                        "symbol": f"{index:06d}",
                        "price": "70000",
                        "open": "69000",
                        "high": "70500",
                        "low": "68500",
                        "volume": "123456",
                        "traded_value": "8641920000",
                        "observed_at": f"2026-05-12T01:00:{index % 60:02d}+00:00",
                        "price_observed_at": f"2026-05-12T01:00:{index % 60:02d}+00:00",
                        "depth_observed_at": f"2026-05-12T01:00:{index % 60:02d}.250000+00:00",
                        "paired_snapshot_gap_seconds": "0.250000",
                        "ask_volume": "1000",
                        "bid_volume": "2500",
                        "bid_ask_ratio": "2.500000",
                        "included": True,
                        "reason": "read-only quote ok",
                    }
                    for index in range(1, 21)
                ],
                "api_flags": [],
                "read_call_count": 21,
                "budget_evidence": {
                    "provider": "KIS",
                    "within_budget": True,
                    "latency_bucket": "le_250ms",
                },
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-kis-many-snapshot",
            "--market-data-report",
            str(market_report),
            "--now",
            "2026-05-12T10:02:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["snapshot_contract"]["symbol_count"] == 20
    assert payload["snapshot_contract"]["read_call_count"] == 21
    assert "rate_limit_risk" not in payload["flags"]


def test_local_free_space_defaults_to_output_filesystem(tmp_path):
    measured = _local_free_space_gb(None, tmp_path / "nested" / "report.json")

    assert measured > Decimal("0")


def test_local_free_space_allows_operator_override(tmp_path):
    measured = _local_free_space_gb("12.5", tmp_path / "report.json")

    assert measured == Decimal("12.5")


def test_field_dry_run_monitor_promotes_api_report_flags(tmp_path):
    api_report = tmp_path / "api-report.json"
    api_report.write_text(
        json.dumps(
            {
                "api_flags": ["api_schema_mismatch"],
                "read_call_count": 3,
                "budget_evidence": {
                    "provider": "KIS",
                    "within_budget": False,
                    "latency_bucket": "le_1000ms",
                },
                "probes": [
                    {
                        "name": "kis-paper-market-data",
                        "diagnostics": {"flags": ["api_command_error"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-api-flags",
            "--api-report",
            str(api_report),
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "field-monitor"),
        ]
    )

    assert exit_code == 1
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "api_degraded"
    assert payload["flags"] == ["api_schema_mismatch", "rate_limit_risk", "api_command_error"]
    assert payload["scenario_results"] == []
    assert payload["snapshot_contract"]["provider"] == "KIS"
    assert payload["snapshot_contract"]["read_call_count"] == 3
    assert payload["snapshot_contract"]["observed_latency_ms"] == 1000
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_field_dry_run_monitor_degrades_stale_market_data_report(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "api_flags": [],
                "members": [
                    {
                        "symbol": "005930",
                        "included": True,
                        "price": "80000",
                        "open": "79000",
                        "high": "80500",
                        "low": "78800",
                        "volume": "1000",
                        "traded_value": "80000000",
                        "bid_ask_ratio": "1.2",
                        "observed_at": "2026-05-13T10:00:00+09:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-stale-market-data",
            "--market-data-report",
            str(market_report),
            "--market-data-max-age-seconds",
            "120",
            "--now",
            "2026-05-13T10:05:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "field-monitor"),
        ]
    )

    assert exit_code == 1
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "input_degraded"
    assert "market_data_stale" in payload["flags"]
    assert "input_contract_degraded" in payload["flags"]
    assert payload["scenario_results"] == []
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_field_dry_run_monitor_blocks_contract_invalid_market_report_before_warmup_scenarios(tmp_path):
    csv_path = tmp_path / "A005930.csv"
    csv_path.write_text(
        "\n".join(
            [
                "date,time,open,high,low,close,volume",
                "20260511,1515,68000,69000,67000,68500,100000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "status": "failed",
                "api_flags": ["api_schema_mismatch"],
                "members": [],
                "budget_evidence": {"provider": "KIS", "within_budget": True},
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-contract-invalid-market-data",
            "--path",
            str(csv_path),
            "--market-data-report",
            str(market_report),
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "field-monitor"),
        ]
    )

    assert exit_code == 1
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "api_degraded"
    assert payload["scenario_results"] == []
    assert "api_schema_mismatch" in payload["flags"]
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_field_dry_run_monitor_accepts_fresh_market_data_report(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "api_flags": [],
                "members": [
                    {
                        "symbol": "005930",
                        "included": True,
                        "price": "80000",
                        "open": "79000",
                        "high": "80500",
                        "low": "78800",
                        "volume": "1000",
                        "traded_value": "80000000",
                        "bid_ask_ratio": "1.2",
                        "observed_at": "2026-05-13T10:04:10+09:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-fresh-market-data",
            "--market-data-report",
            str(market_report),
            "--market-data-max-age-seconds",
            "120",
            "--now",
            "2026-05-13T10:05:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "field-monitor"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert "market_data_stale" not in payload["flags"]
    assert "input_contract_degraded" not in payload["flags"]


def test_field_dry_run_monitor_checks_market_data_freshness_per_included_symbol(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "api_flags": [],
                "members": [
                    {
                        "symbol": "005930",
                        "included": True,
                        "price": "80000",
                        "open": "79000",
                        "high": "80500",
                        "low": "78800",
                        "volume": "1000",
                        "traded_value": "80000000",
                        "bid_ask_ratio": "1.2",
                        "observed_at": "2026-05-13T10:04:30+09:00",
                    },
                    {
                        "symbol": "000660",
                        "included": True,
                        "price": "150000",
                        "open": "149000",
                        "high": "151000",
                        "low": "148000",
                        "volume": "1000",
                        "traded_value": "150000000",
                        "bid_ask_ratio": "1.2",
                        "observed_at": "2026-05-13T10:00:00+09:00",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-mixed-stale-market-data",
            "--market-data-report",
            str(market_report),
            "--market-data-max-age-seconds",
            "120",
            "--now",
            "2026-05-13T10:05:00+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "field-monitor"),
        ]
    )

    assert exit_code == 1
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "input_degraded"
    assert "market_data_stale" in payload["flags"]
    assert "market_data_stale:000660" in payload["flags"]
    assert "input_contract_degraded" in payload["flags"]
    assert payload["scenario_results"] == []


def test_field_dry_run_monitor_promotes_budget_degradation_without_api_flags(tmp_path):
    api_report = tmp_path / "api-report.json"
    api_report.write_text(
        json.dumps(
            {
                "api_flags": [],
                "read_call_count": 3,
                "budget_evidence": {
                    "provider": "KIS",
                    "within_budget": False,
                    "latency_bucket": "le_250ms",
                },
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-budget-only",
            "--api-report",
            str(api_report),
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "field-monitor"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "api_degraded"
    assert payload["flags"] == ["rate_limit_risk"]
    assert payload["snapshot_contract"]["note"] == "read-only API budget evidence is degraded or over budget"


def test_field_dry_run_monitor_counts_generic_api_smoke_kis_probes(tmp_path):
    api_report = tmp_path / "api-smoke.json"
    api_report.write_text(
        json.dumps(
            {
                "status": "failed",
                "probes": [
                    {"name": "telegram", "status": "passed"},
                    {"name": "kis-prod-auth", "status": "passed", "diagnostics": {"flags": []}},
                    {
                        "name": "kis-prod-market-data",
                        "status": "failed",
                        "diagnostics": {"flags": ["api_rate_limit_risk"]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-api-smoke",
            "--api-report",
            str(api_report),
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "field-monitor"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["snapshot_contract"]["provider"] == "KIS"
    assert payload["snapshot_contract"]["read_call_count"] == 2
    assert payload["snapshot_contract"]["note"] == "read-only API budget evidence is degraded or over budget"
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_field_dry_run_monitor_promotes_blacklist_stale_flag(tmp_path):
    blacklist = tmp_path / "blacklist.json"
    blacklist.write_text(
        json.dumps(
            {
                "heartbeat_at": "2026-05-11T09:00:00+09:00",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-blacklist",
            "--blacklist",
            str(blacklist),
            "--status-output",
            str(output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "risk_feed_degraded"
    assert payload["flags"] == ["blacklist_stale"]
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_field_dry_run_monitor_requires_news_feed_when_requested(tmp_path):
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-news-required",
            "--require-news-feed",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "risk_feed_degraded"
    assert payload["flags"] == ["news_feed_missing"]
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_field_dry_run_monitor_keeps_api_and_risk_degradation_visible(tmp_path):
    api_report = tmp_path / "api-report.json"
    api_report.write_text(json.dumps({"api_flags": ["api_schema_mismatch"]}), encoding="utf-8")
    blacklist = tmp_path / "blacklist.json"
    blacklist.write_text(
        json.dumps(
            {
                "heartbeat_at": "2026-05-11T09:00:00+09:00",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-combined-degraded",
            "--api-report",
            str(api_report),
            "--blacklist",
            str(blacklist),
            "--status-output",
            str(output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "api_and_risk_degraded"
    assert payload["flags"] == ["api_schema_mismatch", "blacklist_stale"]
    assert payload["scenario_results"] == []


def test_field_dry_run_monitor_rejects_separate_live_quote_depth_report(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(json.dumps({"members": [], "api_flags": []}), encoding="utf-8")
    quote_depth_report = tmp_path / "kis-readonly-depth.json"
    quote_depth_report.write_text(json.dumps({"members": [], "api_flags": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="diagnostic-only"):
        main(
            [
                "field-dry-run-monitor",
                "--run-id",
                "monitor-reject-depth",
                "--market-data-report",
                str(market_report),
                "--quote-depth-report",
                str(quote_depth_report),
                "--status-output",
                str(tmp_path / "status.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )


def test_field_dry_run_monitor_rejects_duplicate_live_report_inputs(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(json.dumps({"members": [], "api_flags": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="same KIS artifact"):
        main(
            [
                "field-dry-run-monitor",
                "--run-id",
                "monitor-reject-duplicate",
                "--market-data-report",
                str(market_report),
                "--api-report",
                str(market_report),
                "--status-output",
                str(tmp_path / "status.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )


def test_field_dry_run_monitor_rejects_multiple_live_market_data_reports(tmp_path):
    first_report = tmp_path / "kis-readonly-universe-1.json"
    second_report = tmp_path / "kis-readonly-universe-2.json"
    first_report.write_text(json.dumps({"members": [], "api_flags": []}), encoding="utf-8")
    second_report.write_text(json.dumps({"members": [], "api_flags": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one live"):
        main(
            [
                "field-dry-run-monitor",
                "--run-id",
                "monitor-reject-multiple",
                "--market-data-report",
                str(first_report),
                "--market-data-report",
                str(second_report),
                "--status-output",
                str(tmp_path / "status.json"),
                "--output-dir",
                str(tmp_path / "monitor"),
            ]
        )


def test_field_dry_run_monitor_rejects_live_market_data_without_paired_timestamps(tmp_path):
    market_report = tmp_path / "kis-readonly-universe.json"
    market_report.write_text(
        json.dumps(
            {
                "universe_id": "kis-readonly-u1",
                "api_flags": [],
                "budget_evidence": {"source": "kis-readonly-universe-prod", "within_budget": True},
                "members": [
                    {
                        "symbol": "005930",
                        "included": True,
                        "price": "80000",
                        "open": "79000",
                        "high": "80500",
                        "low": "78800",
                        "volume": "1000",
                        "traded_value": "80000000",
                        "bid_ask_ratio": "1.2",
                        "observed_at": "2026-05-13T10:04:10+09:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    status_output = tmp_path / "current-status.json"

    exit_code = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "monitor-reject-missing-pair",
            "--market-data-report",
            str(market_report),
            "--now",
            "2026-05-13T10:04:30+09:00",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert exit_code == 1
    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert payload["status"] == "input_degraded"
    assert "paired_snapshot_missing" in payload["flags"]
    assert "input_contract_degraded" in payload["flags"]


def test_plan_a_sensitivity_cli_writes_bounded_decision_record(tmp_path):
    output = tmp_path / "plan-a-sensitivity.json"

    exit_code = main(["plan-a-sensitivity", "--output", str(output)])

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["decision_id"] == "plan-a-limited-sensitivity-v1"
    assert payload["status"] == "baseline-kept"
    assert payload["baseline_package_id"] == "plan-a-idmom-d3-fsup-u1s1"
    assert {case["case_id"] for case in payload["cases"]} >= {
        "day-profit-target",
        "swing-support-band",
        "portfolio-group-caps",
    }
    assert "candidate B" in payload["candidate_b_action"]


def test_plan_a_sensitivity_writer_preserves_baseline_policy(tmp_path):
    decision = build_plan_a_limited_sensitivity_decision()
    output = tmp_path / "decision.json"

    write_plan_a_sensitivity_decision(decision, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["default_action"].startswith("Keep Plan A defaults")
    assert all(case["decision"] == "keep-default" for case in payload["cases"])


def test_plan_a_dry_run_cli_loads_csv_paths_and_date_filters(tmp_path):
    csv_path = tmp_path / "A123456.csv"
    csv_path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20260508,901,100,100,100,100,10\n"
        "20260511,901,100,100,100,100,10\n"
        "20260511,1515,100,100,100,100,10\n",
        encoding="utf-8",
    )
    output = tmp_path / "plan-a-session.json"

    exit_code = main(
        [
            "plan-a-dry-run",
            "--trading-date",
            "2026-05-11",
            "--path",
            str(csv_path),
            "--start-date",
            "2026-05-11",
            "--end-date",
            "2026-05-11",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["universe_snapshot_count"] == 1
    assert payload["summary"]["capital_feasibility_count"] == 8
    assert payload["summary"]["risk_event_count"] == 1
    assert payload["summary"]["api_rate_limit_check_count"] == 1
    assert payload["report"]["universe_snapshots"][0]["included_symbols"] == ["A123456"]


def test_plan_a_dry_run_cli_rejects_csv_inputs_with_no_matching_bars(tmp_path):
    csv_path = tmp_path / "A123456.csv"
    csv_path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20260508,901,100,100,100,100,10\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no dry-run bars matched"):
        main(
            [
                "plan-a-dry-run",
                "--trading-date",
                "2026-05-11",
                "--path",
                str(csv_path),
                "--start-date",
                "2026-05-11",
                "--end-date",
                "2026-05-11",
                "--output",
                str(tmp_path / "plan-a-session.json"),
            ]
        )


def test_plan_a_dry_run_cli_rejects_non_positive_limit_files_for_csv_mode(tmp_path):
    csv_path = tmp_path / "A123456.csv"
    csv_path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20260511,901,100,100,100,100,10\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="limit-files must be positive"):
        main(
            [
                "plan-a-dry-run",
                "--trading-date",
                "2026-05-11",
                "--path",
                str(csv_path),
                "--limit-files",
                "0",
                "--output",
                str(tmp_path / "plan-a-session.json"),
            ]
        )


def test_historical_dry_run_counts_no_signal_trading_day():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 9, 1, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
    ]

    report = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_HoldDryRunStrategy,
    )

    assert report.summary()["trading_day_count"] == 1
    assert report.summary()["scouter_candidate_count"] == 0


def test_historical_dry_run_generates_no_order_decisions_and_feasibility():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
            bid_ask_ratio=Decimal("2.0"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("104"),
            low=Decimal("100"),
            close=Decimal("104"),
            volume=20_000_000,
            value=Decimal("2000000000"),
            bid_ask_ratio=Decimal("2.0"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("104"),
            high=Decimal("104"),
            low=Decimal("104"),
            close=Decimal("104"),
            volume=1,
            value=Decimal("104"),
            bid_ask_ratio=Decimal("2.0"),
        ),
    ]

    report = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_TestDryRunStrategy,
    )

    assert report.summary()["mode"] == "no-order"
    assert report.summary()["order_hard_block"] is True
    assert report.summary()["virtual_order_unblocked_count"] == 0
    assert report.summary()["capital_feasibility_count"] == 8
    assert report.summary()["daily_reconciliation_count"] == 1
    assert report.summary()["opening_survival_check_count"] == 1
    assert report.summary()["portfolio_state_count"] == 0
    assert report.portfolio_states == ()
    assert report.plan_b_fallback is not None
    assert report.plan_b_fallback.active is False
    assert report.scouter_candidates[0].rank == 1
    assert any(order.strategy_group == "day" for order in report.virtual_orders)
    assert all(order.affordability_status == "not_cash_reconciled" for order in report.virtual_orders)
    assert all(position.affordability_status == "not_cash_reconciled" for position in report.virtual_positions)
    assert "not an executable intended position" in report.virtual_orders[0].affordability_note
    order_payload = report.virtual_orders[0]
    position_payload = report.virtual_positions[0]
    close_payload = report.virtual_position_closes[0]
    assert order_payload.strategy_id == "C-IDMOM-D3-U1-S1"
    assert order_payload.entry_rule == "test-day-entry"
    assert order_payload.exit_policy == "target=0.05;stop=-0.02;max_minutes=360;day_end_exit"
    assert order_payload.cost_model == "fee_rate=0.00030;slippage_rate=0.00100"
    assert order_payload.applied_profit_target == Decimal("0.05")
    assert order_payload.applied_hard_stop == Decimal("-0.02")
    assert order_payload.applied_max_holding_minutes == 360
    assert order_payload.applied_day_end_exit is True
    assert position_payload.strategy_id == order_payload.strategy_id
    assert position_payload.entry_rule == order_payload.entry_rule
    assert close_payload.strategy_id == order_payload.strategy_id
    assert close_payload.entry_rule == order_payload.entry_rule
    assert close_payload.exit_policy == order_payload.exit_policy
    assert close_payload.slot_id == position_payload.slot_id
    ledger_events = dry_run_ledger_events(report)
    ledger_order = next(event for event in ledger_events if event["event_type"] == "virtual-order")
    ledger_close = next(event for event in ledger_events if event["event_type"] == "virtual-position-close")
    assert ledger_order["payload"]["strategy_id"] == "C-IDMOM-D3-U1-S1"
    assert ledger_order["payload"]["applied_profit_target"] == Decimal("0.05")
    assert ledger_close["payload"]["exit_policy"] == order_payload.exit_policy


def test_historical_dry_run_scopes_shared_strategy_state_by_scenario():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=20_000_000,
            value=Decimal("2000000000"),
            bid_ask_ratio=Decimal("2.0"),
        )
    ]
    shared_strategies = {}

    primary = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_BuyOnceStatefulStrategy,
        strategies_by_symbol=shared_strategies,
        strategy_scope="primary",
    )
    shadow = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_BuyOnceStatefulStrategy,
        strategies_by_symbol=shared_strategies,
        strategy_scope="shadow",
    )

    assert [order.reason_code for order in primary.virtual_orders] == ["test-scoped-state-entry"]
    assert [order.reason_code for order in shadow.virtual_orders] == ["test-scoped-state-entry"]
    assert sorted(shared_strategies) == [("primary", "A000001"), ("shadow", "A000001")]


def test_historical_dry_run_blocks_new_entries_when_blacklist_stale():
    bars = [
        Bar(
            symbol="A123456",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            value=Decimal("100000"),
        )
    ]
    snapshot = AsyncBlacklistSnapshot(heartbeat_at=bars[0].timestamp - timedelta(minutes=6), entries=())

    report = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_TestDryRunStrategy,
        blacklist_snapshot=snapshot,
    )

    assert report.virtual_orders == ()
    assert report.scouter_decision_snapshots[0].reason == "blacklist-stale-fail-closed"
    assert report.risk_events[0].event_type == "async-blacklist"


def test_historical_dry_run_blocks_blacklisted_symbol_only():
    timestamp = datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar(
            symbol="A123456",
            timestamp=timestamp,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            value=Decimal("100000"),
        ),
        Bar(
            symbol="A654321",
            timestamp=timestamp,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            value=Decimal("100000"),
        ),
    ]
    snapshot = AsyncBlacklistSnapshot(
        heartbeat_at=timestamp,
        entries=(
            AsyncBlacklistEntry(
                symbol="123456",
                reason="negative-news",
                severity="block",
                source="manual",
                observed_at=timestamp,
            ),
        ),
    )

    report = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_TestDryRunStrategy,
        blacklist_snapshot=snapshot,
    )

    assert [order.symbol for order in report.virtual_orders] == ["A654321"]
    reasons = {snapshot.symbol: snapshot.reason for snapshot in report.scouter_decision_snapshots}
    assert reasons["A123456"] == "blacklist-symbol-blocked"


def test_capital_feasibility_does_not_overstate_unbuyable_day_swing_orders():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("900000"),
            high=Decimal("900000"),
            low=Decimal("900000"),
            close=Decimal("900000"),
            volume=10,
            value=Decimal("9000000"),
        ),
        Bar(
            symbol="A000002",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("900000"),
            high=Decimal("900000"),
            low=Decimal("900000"),
            close=Decimal("900000"),
            volume=10,
            value=Decimal("9000000"),
        ),
    ]

    report = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_ExpensiveDaySwingStrategy,
    )
    shared_small_seed = next(
        item
        for item in report.capital_feasibility
        if item.case_id == "shared-slot-plan-a" and item.starting_seed == Decimal("1000000")
    )

    assert shared_small_seed.whole_share_reject_count == 2
    assert shared_small_seed.simultaneous_day_swing_feasible is False


def test_dry_run_ledger_events_are_ordered_and_no_order_auditable():
    report = build_empty_plan_a_dry_run_report(trading_date=date(2026, 5, 11), session_id="ledger-test")

    events = dry_run_ledger_events(report)

    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[0]["event_type"] == "session-summary"
    assert events[0]["payload"]["mode"] == "no-order"
    assert events[0]["payload"]["order_hard_block"] is True
    assert events[-1]["event_type"] == "plan-b-fallback-state"


def test_multi_session_dry_run_carries_swing_state_into_opening_check(tmp_path):
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("101"),
            high=Decimal("101"),
            low=Decimal("101"),
            close=Decimal("101"),
            volume=100,
            value=Decimal("10100"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="multi-test",
        starting_seed=Decimal("1000000"),
        strategy_factory=_SwingEntryStrategy,
    )
    output = tmp_path / "multi.json"
    write_multi_session_dry_run_report(report, output)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["summary"]["mode"] == "no-order"
    assert payload["summary"]["session_count"] == 2
    assert payload["summary"]["api_rate_limit_breach_count"] == 0
    assert report.sessions[1].opening_survival_checks[0].checked_positions == 1
    assert any(event.event_type == "held-symbol-skip" for event in report.sessions[1].interlock_events)
    assert report.cash_reconciliation[0].virtual_buy_notional == Decimal("100.130030")
    assert report.cash_reconciliation[0].reserved_cash == Decimal("100.100000")
    assert report.cash_reconciliation[0].idle_cash == Decimal("999899.869970")
    assert report.cash_reconciliation[1].reserved_cash == Decimal("100.100000")
    assert report.cash_reconciliation[1].idle_cash == Decimal("999899.869970")
    assert report.checkpoint_events[0].trigger_id.startswith("order-hard-block")


def test_multi_session_dry_run_does_not_duplicate_carried_swing_positions():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("101"),
            high=Decimal("101"),
            low=Decimal("101"),
            close=Decimal("101"),
            volume=100,
            value=Decimal("10100"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="carried-no-duplicate-test",
        starting_seed=Decimal("1000000"),
        strategy_factory=_SwingEntryStrategy,
    )

    assert len(report.sessions[0].virtual_positions) == 1
    assert report.sessions[1].virtual_positions == ()
    assert report.summary()["virtual_order_hard_blocked_count"] == 1


def test_multi_session_dry_run_keeps_carried_swing_cash_stable_without_new_orders():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("101"),
            high=Decimal("101"),
            low=Decimal("101"),
            close=Decimal("101"),
            volume=100,
            value=Decimal("10100"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 13, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("102"),
            high=Decimal("102"),
            low=Decimal("102"),
            close=Decimal("102"),
            volume=100,
            value=Decimal("10200"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="carried-cash-stable-test",
        starting_seed=Decimal("1000000"),
        strategy_factory=_SwingEntryStrategy,
    )

    assert [row.virtual_buy_notional for row in report.cash_reconciliation] == [
        Decimal("100.130030"),
        Decimal("0"),
        Decimal("0"),
    ]
    assert [row.ending_cash for row in report.cash_reconciliation] == [
        Decimal("999899.869970"),
        Decimal("999899.869970"),
        Decimal("999899.869970"),
    ]
    assert [row.reserved_cash for row in report.cash_reconciliation] == [
        Decimal("100.100000"),
        Decimal("100.100000"),
        Decimal("100.100000"),
    ]
    assert [row.idle_cash for row in report.cash_reconciliation] == [
        Decimal("999899.869970"),
        Decimal("999899.869970"),
        Decimal("999899.869970"),
    ]


def test_multi_session_dry_run_blocks_same_bar_reentry_after_close():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("104"),
            high=Decimal("104"),
            low=Decimal("104"),
            close=Decimal("104"),
            volume=100,
            value=Decimal("10400"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="same-bar-reentry-test",
        starting_seed=Decimal("1000000"),
        strategy_factory=_SwingEntryStrategy,
    )

    assert report.sessions[1].virtual_orders == ()
    assert report.sessions[1].virtual_position_closes[0].reason == "profit-target"
    assert report.sessions[1].scouter_decision_snapshots[0].reason == "closed-position-same-bar-cooldown"
    assert report.sessions[1].interlock_events[0].event_type == "closed-symbol-skip"


def test_multi_session_dry_run_allows_later_reentry_after_carried_swing_close():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("104"),
            high=Decimal("104"),
            low=Decimal("104"),
            close=Decimal("104"),
            volume=100,
            value=Decimal("10400"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 13, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="later-reentry-test",
        starting_seed=Decimal("1000000"),
        strategy_factory=_SwingEntryStrategy,
    )

    assert report.sessions[1].virtual_orders == ()
    assert [order.symbol for order in report.sessions[2].virtual_orders] == ["A000001"]


def test_multi_session_dry_run_preserves_strategy_history_across_sessions():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("101"),
            high=Decimal("101"),
            low=Decimal("101"),
            close=Decimal("101"),
            volume=100,
            value=Decimal("10100"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="stateful-strategy-test",
        starting_seed=Decimal("1000000"),
        strategy_factory=_WarmupThenDayEntryStrategy,
    )

    assert report.sessions[0].virtual_orders == ()
    assert [order.symbol for order in report.sessions[1].virtual_orders] == ["A000001"]
    assert report.sessions[1].virtual_orders[0].reason_code == "test-stateful-day-entry"


def test_multi_session_dry_run_records_cash_starvation_checkpoint():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("900000"),
            high=Decimal("900000"),
            low=Decimal("900000"),
            close=Decimal("900000"),
            volume=100,
            value=Decimal("90000000"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="cash-starvation-test",
        starting_seed=Decimal("100000"),
        strategy_factory=_SwingEntryStrategy,
    )

    assert any(event.trigger_id.startswith("cash-starvation") for event in report.checkpoint_events)
    assert report.summary()["ready_for_broker_or_order_transmission"] is False


def test_multi_session_dry_run_cli_writes_local_no_order_report(tmp_path):
    csv_path = tmp_path / "A123456.csv"
    csv_path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20260511,1000,100,100,100,100,10\n"
        "20260512,1000,101,101,101,101,10\n",
        encoding="utf-8",
    )
    output = tmp_path / "multi-session.json"

    exit_code = main(
        [
            "plan-a-dry-run-multi",
            "--run-id",
            "cli-multi-test",
            "--path",
            str(csv_path),
            "--api-rate-limit-per-second",
            "5",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["mode"] == "no-order"
    assert payload["summary"]["session_count"] == 2
    assert payload["summary"]["api_rate_limit_check_count"] == 2
    assert payload["report"]["api_rate_limit_checks"][0]["estimated_calls"] == 0
    assert payload["report"]["api_rate_limit_checks"][0]["estimated_peak_per_second"] == 1
    assert "configured planned field polling budget" in payload["report"]["api_rate_limit_checks"][0]["note"]
    assert payload["summary"]["ready_for_broker_or_order_transmission"] is False


def test_multi_session_dry_run_records_kis_snapshot_api_pressure():
    bars = [
        Bar(
            symbol="A005930",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("70000"),
            high=Decimal("70000"),
            low=Decimal("70000"),
            close=Decimal("70000"),
            volume=100,
            value=Decimal("7000000"),
            source="kis-readonly-report:kis-readonly-universe.json",
        ),
        Bar(
            symbol="A000660",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100000"),
            high=Decimal("100000"),
            low=Decimal("100000"),
            close=Decimal("100000"),
            volume=100,
            value=Decimal("10000000"),
            source="kis-readonly-report:kis-readonly-universe.json",
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="kis-api-pressure-test",
        strategy_factory=_HoldDryRunStrategy,
    )

    check = report.api_rate_limit_checks[0]
    assert check.data_source == "kis-readonly-report"
    assert check.estimated_calls == 2
    assert check.estimated_peak_per_second == 2
    assert "read-only field API pressure" in check.note


def test_multi_session_dry_run_does_not_treat_partial_session_final_bar_as_day_end_exit():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 1, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="partial-session-day-exit-test",
        starting_seed=Decimal("1000000"),
        strategy_factory=_PartialSessionDayExitStrategy,
    )

    assert report.sessions[0].virtual_position_closes == ()
    assert len(report.sessions[0].open_positions) == 1
    assert report.cash_reconciliation[0].reserved_cash == Decimal("100.100000")
    assert report.cash_reconciliation[0].cash_after_virtual_trades == Decimal("999899.869970")
    assert report.cash_reconciliation[0].available_cash_after_reserved_exposure == Decimal("999899.869970")


def test_multi_session_dry_run_records_twenty_day_checkpoint_and_decision_snapshots():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, day, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        )
        for day in range(1, 21)
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="twenty-day-test",
        starting_seed=Decimal("1000000"),
        strategy_factory=_HoldDryRunStrategy,
    )

    assert report.summary()["session_count"] == 20
    assert report.summary()["scouter_decision_snapshot_count"] == 20
    assert report.summary()["pnl_snapshot_count"] == 20
    assert report.summary()["portfolio_state_count"] == 20
    assert report.summary()["storage_guardrail_check_count"] == 20
    assert any(event.trigger_id == "dry-run-day-10" for event in report.checkpoint_events)
    assert any(event.trigger_id == "dry-run-day-20" for event in report.checkpoint_events)


def test_dry_run_records_virtual_pnl_close_and_api_budget_breach():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 1, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("106"),
            high=Decimal("106"),
            low=Decimal("106"),
            close=Decimal("106"),
            volume=100,
            value=Decimal("10600"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="pnl-api-test",
        starting_seed=Decimal("1000000"),
        api_rate_limit_per_second=1,
        strategy_factory=_DayExitStrategy,
    )

    assert report.sessions[0].virtual_position_closes[0].realized_pnl == Decimal("5.732202")
    assert report.pnl_snapshots[0].realized_pnl == Decimal("5.732202")
    assert report.cash_reconciliation[0].virtual_sell_notional == Decimal("105.862232")
    assert report.cash_reconciliation[0].reserved_cash == Decimal("0")
    assert report.portfolio_states[0].total_slots_used == 0
    assert report.portfolio_states[0].day_exposure == Decimal("0")
    assert report.summary()["api_rate_limit_breach_count"] == 0


def test_multi_session_dry_run_closes_carried_swing_with_original_exit_policy():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("104"),
            high=Decimal("104"),
            low=Decimal("104"),
            close=Decimal("104"),
            volume=100,
            value=Decimal("10400"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="carried-swing-close",
        starting_seed=Decimal("1000000"),
        strategy_factory=_SwingEntryStrategy,
    )

    assert report.sessions[1].virtual_position_closes[0].reason == "profit-target"
    assert report.sessions[1].virtual_position_closes[0].realized_pnl == Decimal("3.734801")
    assert [row.virtual_buy_notional for row in report.cash_reconciliation] == [Decimal("100.130030"), Decimal("0")]
    assert [row.virtual_sell_notional for row in report.cash_reconciliation] == [Decimal("0"), Decimal("103.864831")]
    assert [row.ending_cash for row in report.cash_reconciliation] == [Decimal("999899.869970"), Decimal("1000003.734801")]
    assert report.portfolio_states[1].total_slots_used == 0
    assert report.portfolio_states[1].swing_exposure == Decimal("0")


def test_multi_session_dry_run_preserves_carried_swing_entry_time_for_max_hold():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 12, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
    ]

    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id="carried-swing-max-hold",
        starting_seed=Decimal("1000000"),
        strategy_factory=_ShortHoldSwingStrategy,
    )

    assert report.sessions[1].virtual_position_closes[0].reason == "max-holding-minutes"
    assert report.portfolio_states[1].total_slots_used == 0
    assert report.cash_reconciliation[1].reserved_cash == Decimal("0")


def test_multi_session_dry_run_logs_1510_lock_step_without_day_end_exit():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 15, 10, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
    ]

    report = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_DayExitStrategy,
    )

    assert report.virtual_position_closes == ()
    assert any(event.event_type == "lock-step-window" for event in report.risk_events)


def test_multi_session_dry_run_closes_day_position_at_first_1515_snapshot():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 15, 15, 20, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
    ]

    report = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 11),
        strategy_factory=_DayExitStrategy,
    )

    assert report.virtual_position_closes[0].reason == "day-end-exit"
    assert any(event.event_type == "lock-step-window" for event in report.risk_events)


def test_dry_run_storage_guardrail_disables_raw_burst_and_blocks_protective_mode():
    bars = [
        Bar(
            symbol="A000001",
            timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=100,
            value=Decimal("10000"),
        ),
    ]

    raw_disabled = run_plan_a_multi_session_dry_run(
        bars,
        run_id="storage-raw-disabled",
        local_free_space_gb=Decimal("9"),
        raw_burst_enabled=True,
        strategy_factory=_HoldDryRunStrategy,
    )
    protective = run_plan_a_multi_session_dry_run(
        bars,
        run_id="storage-protective",
        local_free_space_gb=Decimal("4"),
        strategy_factory=_HoldDryRunStrategy,
    )

    assert raw_disabled.storage_guardrail_checks[0].action == "raw-burst-disabled"
    assert raw_disabled.storage_guardrail_checks[0].raw_burst_enabled is False
    assert any(event.category == "storage" for event in raw_disabled.checkpoint_events)
    assert protective.storage_guardrail_checks[0].action == "protective-mode"
    assert protective.summary()["storage_guardrail_breach_count"] == 1
