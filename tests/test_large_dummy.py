from dataclasses import replace
from decimal import Decimal

import pytest

from zurini.backtest.engine import BacktestConfig, run_backtest
from zurini.data.large_dummy import (
    LargeDummyProfile,
    build_quality_anomaly_fixtures,
    generate_symbol_metadata,
    get_large_dummy_profile,
    iter_large_dummy_index_bars,
    iter_large_dummy_market_bars,
)
from zurini.market import SignalIntent


class NoSignalStrategy:
    def on_bar(self, bar, risk=None):
        return SignalIntent("hold", Decimal("0"), "resource smoke")


def test_smoke_profile_generates_deterministic_kst_minute_bars():
    profile = get_large_dummy_profile("smoke")
    first = list(iter_large_dummy_market_bars(profile))
    second = list(iter_large_dummy_market_bars(profile))

    assert first == second
    assert len(first) == profile.market_bar_count
    assert {bar.timestamp.tzinfo.key for bar in first} == {"Asia/Seoul"}
    first_symbol = [bar for bar in first if bar.symbol == "ZRN0001"][: profile.minutes_per_day]
    assert [bar.timestamp.minute for bar in first_symbol[:4]] == [0, 1, 2, 3]


def test_profiles_model_logical_24_months_with_bounded_materialized_counts():
    smoke = get_large_dummy_profile("smoke")
    scale = get_large_dummy_profile("scale")

    assert smoke.logical_months == 24
    assert smoke.market_bar_count == 8 * 24 * 1 * 12
    assert smoke.market_bar_count < 10_000
    assert scale.logical_months == 24
    assert scale.market_bar_count > smoke.market_bar_count
    assert scale.market_bar_count < 2_000_000
    assert "logical months" in smoke.as_dict()["time_acceleration"]


def test_many_symbol_profile_has_unique_symbol_timestamp_pairs_and_metadata():
    profile = get_large_dummy_profile("smoke")
    bars = list(iter_large_dummy_market_bars(profile))
    metadata = generate_symbol_metadata(profile)

    keys = {(bar.symbol, bar.timestamp) for bar in bars}
    assert len(keys) == len(bars)
    assert [item.symbol for item in metadata] == [f"ZRN{index:04d}" for index in range(1, 9)]
    assert {item.source for item in metadata} == {"phase15-dummy"}
    assert {bar.symbol for bar in bars} == {item.symbol for item in metadata}


def test_dummy_index_series_uses_same_kst_minute_grid_as_market_bars():
    profile = get_large_dummy_profile("smoke")
    market_grid = {bar.timestamp for bar in iter_large_dummy_market_bars(profile) if bar.symbol == "ZRN0001"}
    index_bars = list(iter_large_dummy_index_bars(profile))

    assert len(index_bars) == profile.index_bar_count
    assert {bar.symbol for bar in index_bars} == set(profile.index_codes)
    for index_code in profile.index_codes:
        assert {bar.timestamp for bar in index_bars if bar.symbol == index_code} == market_grid


def test_optional_quality_anomaly_fixtures_are_explicit_and_validator_covered():
    findings = build_quality_anomaly_fixtures(get_large_dummy_profile("smoke"))

    assert findings["gap_fixture_minutes_missing"] == 1
    assert findings["gap_fixture_row_count"] == 287
    assert findings["zero_volume_fixture_is_schema_valid"] is True
    assert "duplicate" in findings["duplicate_timestamp_error"]
    assert "high" in findings["invalid_ohlc_error"]


def test_quality_anomaly_fixtures_still_trigger_with_short_minute_profiles():
    profile = replace(get_large_dummy_profile("smoke"), minutes_per_day=4)
    bars = list(iter_large_dummy_market_bars(profile, include_quality_anomalies=True))
    first_day_first_symbol = [
        bar
        for bar in bars
        if bar.symbol == "ZRN0001" and bar.timestamp.date().isoformat() == profile.start_date
    ]

    assert len(bars) == profile.market_bar_count - 1
    assert len(first_day_first_symbol) == 3
    assert any(bar.volume == 0 for bar in first_day_first_symbol)


def test_quality_anomaly_fixtures_require_enough_intraday_minutes():
    too_short = LargeDummyProfile(
        name="too-short",
        symbol_count=1,
        logical_months=1,
        trading_days_per_month=1,
        minutes_per_day=1,
    )

    with pytest.raises(ValueError, match="at least 2"):
        list(iter_large_dummy_market_bars(too_short, include_quality_anomalies=True))


def test_backtest_accepts_synthetic_many_symbol_smoke_profile_deterministically():
    bars = list(iter_large_dummy_market_bars(get_large_dummy_profile("smoke")))
    config = BacktestConfig(start_equity=Decimal("1000000"))

    report_a, trades_a = run_backtest(bars, strategy_factory=NoSignalStrategy, config=config)
    report_b, trades_b = run_backtest(bars, strategy_factory=NoSignalStrategy, config=config)

    assert report_a == report_b
    assert trades_a == trades_b == []
    assert report_a.trade_count == 0
    assert report_a.end_equity == report_a.start_equity + report_a.net_pnl
