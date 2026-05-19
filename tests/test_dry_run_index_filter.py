from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

import zurini.api_smoke as api_smoke
from zurini.cli import _index_payload_with_accumulated_bars, _index_trend_report_flags, main
from zurini.dry_run import run_plan_a_historical_dry_run
from zurini.index_trend import IndexTrendDecision
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


class _AlwaysSwingEntryStrategy:
    def on_bar(self, bar: Bar) -> SignalIntent:
        return SignalIntent(action="buy", weight=Decimal("1"), reason="test-swing-entry", group="swing")


def _bar(symbol: str, timestamp: datetime, price: Decimal = Decimal("100")) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1000,
        value=price * Decimal("1000"),
    )


def _index_bar_row(symbol: str, timestamp: datetime, price: Decimal = Decimal("100")) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp.isoformat(),
        "open": str(price),
        "high": str(price),
        "low": str(price),
        "close": str(price),
        "volume": 1000,
        "value": "0",
        "source": "kis-index-poll-10s",
    }


def test_index_trend_filter_blocks_day_entry_only_when_enabled() -> None:
    bars = [_bar("A005930", datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))]

    blocked = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 15),
        strategy_factory=_TestDryRunStrategy,
        index_trend_filter_enabled=True,
        index_trend_provider=lambda timestamp, symbol: IndexTrendDecision(
            allowed=False,
            reason="index-trend-slope-block",
        ),
    )
    allowed = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 15),
        strategy_factory=_TestDryRunStrategy,
        index_trend_filter_enabled=False,
        index_trend_provider=lambda timestamp, symbol: IndexTrendDecision(
            allowed=False,
            reason="index-trend-slope-block",
        ),
    )

    assert len(blocked.virtual_orders) == 0
    assert blocked.scouter_decision_snapshots[0].reason == "risk-block:index-trend-slope-block"
    assert len(allowed.virtual_orders) == 1


def test_index_trend_filter_does_not_block_swing_entry_candidates() -> None:
    bars = [_bar("A005930", datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))]

    report = run_plan_a_historical_dry_run(
        bars,
        trading_date=date(2026, 5, 15),
        strategy_factory=_AlwaysSwingEntryStrategy,
        index_trend_filter_enabled=True,
        index_trend_provider=lambda timestamp, symbol: IndexTrendDecision(
            allowed=False,
            reason="index-trend-slope-block",
        ),
    )

    assert len(report.virtual_orders) == 1
    assert report.virtual_orders[0].strategy_group == "swing"


def test_field_monitor_index_filter_fails_closed_when_enabled_without_index_report(tmp_path) -> None:
    status_output = tmp_path / "status.json"
    result = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "index-filter-missing",
            "--enable-index-trend-filter",
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert result == 1
    assert "index_trend_missing" in payload["flags"]
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_field_monitor_index_filter_missing_report_path_writes_fail_closed_status(tmp_path) -> None:
    status_output = tmp_path / "status.json"
    result = main(
        [
            "field-dry-run-monitor",
            "--run-id",
            "index-filter-missing-path",
            "--enable-index-trend-filter",
            "--index-trend-report",
            str(tmp_path / "missing-index.json"),
            "--status-output",
            str(status_output),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    payload = json.loads(status_output.read_text(encoding="utf-8"))
    assert result == 1
    assert "index_trend_missing" in payload["flags"]
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_index_trend_report_flags_require_each_main_index(tmp_path) -> None:
    report_path = tmp_path / "kospi-only.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "bars": [
                    _index_bar_row("KOSPI", datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))
                ],
            }
        ),
        encoding="utf-8",
    )

    flags = _index_trend_report_flags(
        [report_path],
        enabled=True,
        max_age_seconds=120,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert "index_trend_missing:KOSDAQ" in flags


def test_index_trend_report_flags_reject_missing_status(tmp_path) -> None:
    report_path = tmp_path / "no-status.json"
    report_path.write_text(
        json.dumps(
            {
                "bars": [
                    _index_bar_row("KOSPI", datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))),
                    _index_bar_row("KOSDAQ", datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))),
                ],
            }
        ),
        encoding="utf-8",
    )

    flags = _index_trend_report_flags(
        [report_path],
        enabled=True,
        max_age_seconds=120,
        now=datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert "index_trend_failed" in flags


def test_plan_a_dry_run_index_filter_rejects_missing_simulation_report(tmp_path) -> None:
    input_path = tmp_path / "bars.csv"
    input_path.write_text(
        "date,time,open,high,low,close,volume,value\n"
        "20260515,1000,100,100,100,100,1000,100000\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="index trend report contract invalid"):
        main(
            [
                "plan-a-dry-run",
                "--trading-date",
                "2026-05-15",
                "--path",
                str(input_path),
                "--enable-index-trend-filter",
                "--index-trend-report",
                str(tmp_path / "missing-index.json"),
                "--output",
                str(tmp_path / "report.json"),
            ]
        )


def test_field_run_skips_index_poll_when_quote_report_is_degraded(tmp_path, monkeypatch) -> None:
    symbol_list = tmp_path / "symbols.txt"
    symbol_list.write_text("111111\n", encoding="utf-8")
    index_calls = []

    def fake_prewarm_kis_token_cache(**kwargs):
        return object(), api_smoke.KisAuthPreflightResult(
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
            included_symbols=("111111",),
            excluded_symbols=(),
            members=(
                api_smoke.KisUniverseMember(
                    symbol="111111",
                    price="119",
                    included=True,
                    reason="read-only quote degraded",
                    field_data_flags=("api_rate_limit_risk",),
                ),
            ),
            api_flags=("api_rate_limit_risk",),
            read_call_count=2,
            budget_evidence={"source": "kis-readonly-universe-prod", "within_budget": False},
            safety_boundary="read-only test",
        )

    def fake_build_kis_index_poll_snapshot(**kwargs):
        index_calls.append(kwargs)
        raise AssertionError("index poll must not run after a degraded quote report")

    monkeypatch.setattr("zurini.cli.prewarm_kis_token_cache", fake_prewarm_kis_token_cache)
    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)
    monkeypatch.setattr("zurini.cli.build_kis_index_poll_snapshot", fake_build_kis_index_poll_snapshot)

    result = main(
        [
            "field-run",
            "--run-id",
            "skip-index-after-degraded-quote",
            "--symbol-list",
            str(symbol_list),
            "--allow-network",
            "--run-network",
            "--confirm-prod-readonly",
            "--enable-index-trend-filter",
            "--cycle-limit",
            "1",
            "--now",
            "2026-05-15T10:01:00+09:00",
            "--quote-report",
            str(tmp_path / "quote.json"),
            "--index-report",
            str(tmp_path / "index.json"),
            "--status-output",
            str(tmp_path / "status.json"),
            "--control-output",
            str(tmp_path / "control.json"),
            "--output-dir",
            str(tmp_path / "monitor"),
        ]
    )

    assert result == 1
    assert index_calls == []
    assert not (tmp_path / "index.json").exists()


def test_index_report_accumulation_keeps_prior_lookback_bars(tmp_path) -> None:
    existing = tmp_path / "index.json"
    existing.write_text(
        json.dumps(
            {
                "status": "passed",
                "bars": [
                    _index_bar_row("KOSPI", datetime(2026, 5, 15, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))),
                    _index_bar_row("KOSDAQ", datetime(2026, 5, 15, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))),
                ],
            }
        ),
        encoding="utf-8",
    )
    current = {
        "status": "passed",
        "bars": [
            _index_bar_row("KOSPI", datetime(2026, 5, 15, 9, 31, tzinfo=ZoneInfo("Asia/Seoul"))),
            _index_bar_row("KOSDAQ", datetime(2026, 5, 15, 9, 31, tzinfo=ZoneInfo("Asia/Seoul"))),
        ],
    }

    payload = _index_payload_with_accumulated_bars([existing], current)

    assert len(payload["bars"]) == 4
