from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from zurini.index_trend import (
    IndexTrendGateConfig,
    build_index_trend_state,
    decide_day_entry_with_index_trend,
)
from zurini.kis_index_feed import (
    KisIndexSample,
    aggregate_index_samples_to_minute_bars,
    build_kis_index_poll_plan,
    index_bars_from_report,
    index_samples_from_report,
)


KST = ZoneInfo("Asia/Seoul")


def test_kis_index_poll_plan_is_fixed_to_ten_second_contract():
    plan = build_kis_index_poll_plan(poll_interval_seconds=10)

    assert plan["status"] == "ready"
    assert plan["estimated_read_calls_per_minute"] == 12
    with pytest.raises(ValueError, match="10-second"):
        build_kis_index_poll_plan(poll_interval_seconds=5)


def test_aggregate_index_samples_to_minute_bars_preserves_index_codes_and_price_ohlc():
    base = datetime(2026, 5, 15, 9, 0, 3, tzinfo=KST)
    samples = (
        KisIndexSample("KOSPI", base, Decimal("100"), Decimal("99"), Decimal("101"), Decimal("98"), volume=10),
        KisIndexSample("KOSPI", base + timedelta(seconds=10), Decimal("102"), Decimal("99"), Decimal("103"), Decimal("98"), volume=20),
        KisIndexSample("KOSDAQ", base, Decimal("200"), Decimal("199"), Decimal("201"), Decimal("198"), volume=30),
    )

    bars = aggregate_index_samples_to_minute_bars(samples)

    assert [(bar.symbol, bar.timestamp.second, bar.open, bar.close, bar.volume) for bar in bars] == [
        ("KOSDAQ", 3, Decimal("200"), Decimal("200"), 30),
        ("KOSPI", 13, Decimal("100"), Decimal("102"), 30),
    ]
    assert [(bar.symbol, bar.high, bar.low) for bar in bars] == [
        ("KOSDAQ", Decimal("200"), Decimal("200")),
        ("KOSPI", Decimal("102"), Decimal("100")),
    ]


def test_aggregate_index_samples_does_not_treat_session_low_as_minute_low():
    base = datetime(2026, 5, 15, 10, 0, 0, tzinfo=KST)
    samples = (
        KisIndexSample("KOSPI", base, Decimal("100"), Decimal("99"), Decimal("101"), Decimal("90"), volume=10),
        KisIndexSample("KOSPI", base + timedelta(seconds=10), Decimal("100.2"), Decimal("99"), Decimal("101"), Decimal("90"), volume=10),
    )

    (bar,) = aggregate_index_samples_to_minute_bars(samples)

    assert bar.low == Decimal("100")
    assert bar.high == Decimal("100.2")


def test_index_snapshot_session_low_is_not_used_for_reclaim_allow_signal():
    observed_at = datetime(2026, 5, 15, 9, 40, tzinfo=KST)
    samples = tuple(
        KisIndexSample(
            "KOSPI",
            observed_at - timedelta(minutes=30 - minute),
            Decimal("100"),
            Decimal("100"),
            Decimal("101"),
            Decimal("95"),
            volume=10,
        )
        for minute in range(31)
    )
    bars = aggregate_index_samples_to_minute_bars(samples)

    state = build_index_trend_state(index_code="KOSPI", bars=list(bars), observed_at=observed_at)
    decision = decide_day_entry_with_index_trend(
        states=(state,),
        config=IndexTrendGateConfig(ten_minute_block_threshold=Decimal("0.001")),
    )

    assert state.reclaim_30m == Decimal("0")
    assert not decision.allowed
    assert decision.reason == "index-trend-slope-block"


def test_index_bars_from_report_loads_post_close_simulation_payload():
    payload = {
        "status": "passed",
        "bars": [
            {
                "symbol": "KOSPI",
                "timestamp": "2026-05-15T09:00:00+09:00",
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "volume": 123,
                "source": "kis-index-poll-10s",
            }
        ],
    }

    bars = index_bars_from_report(payload)

    assert len(bars) == 1
    assert bars[0].symbol == "KOSPI"
    assert bars[0].close == Decimal("100.5")


def test_index_samples_from_report_loads_ten_second_tick_payload():
    payload = {
        "status": "passed",
        "samples": [
            {
                "index_code": "KOSPI",
                "timestamp": "2026-05-15T09:00:03+09:00",
                "price": "100.5",
                "open": "100",
                "high": "101",
                "low": "99",
                "volume": 123,
                "source": "kis-index-poll-10s",
            }
        ],
    }

    (sample,) = index_samples_from_report(payload)

    assert sample.index_code == "KOSPI"
    assert sample.price == Decimal("100.5")
    assert sample.low == Decimal("99")
