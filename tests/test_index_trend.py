from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from zurini.index_trend import build_index_trend_state, decide_day_entry_with_index_trend
from zurini.market import Bar


KST = ZoneInfo("Asia/Seoul")


def test_index_trend_blocks_when_both_main_indices_break_open_and_slope_down():
    observed_at = datetime(2026, 5, 15, 9, 40, tzinfo=KST)
    states = (
        build_index_trend_state(index_code="KOSPI", bars=_index_bars("KOSPI", observed_at, open_price=Decimal("100"), close_price=Decimal("98.5")), observed_at=observed_at),
        build_index_trend_state(index_code="KOSDAQ", bars=_index_bars("KOSDAQ", observed_at, open_price=Decimal("200"), close_price=Decimal("197")), observed_at=observed_at),
    )

    decision = decide_day_entry_with_index_trend(states=states)

    assert not decision.allowed
    assert decision.reason == "index-trend-bearish"


def test_index_trend_recovery_override_allows_after_reclaim():
    observed_at = datetime(2026, 5, 15, 9, 40, tzinfo=KST)
    bars = []
    for minute in range(31):
        timestamp = observed_at - timedelta(minutes=30 - minute)
        price = Decimal("98") if minute < 25 else Decimal("100.5")
        bars.append(_bar("KOSPI", timestamp, Decimal("100"), price))
        bars.append(_bar("KOSDAQ", timestamp, Decimal("200"), price * Decimal("2")))
    states = (
        build_index_trend_state(index_code="KOSPI", bars=bars, observed_at=observed_at),
        build_index_trend_state(index_code="KOSDAQ", bars=bars, observed_at=observed_at),
    )

    decision = decide_day_entry_with_index_trend(states=states)

    assert decision.allowed
    assert decision.reason == "index-trend-allowed"


def test_index_trend_missing_or_stale_blocks_day_entry():
    observed_at = datetime(2026, 5, 15, 9, 40, tzinfo=KST)
    stale_bar = _bar("KOSPI", observed_at - timedelta(minutes=1), Decimal("100"), Decimal("100"))

    state = build_index_trend_state(
        index_code="KOSPI",
        bars=[stale_bar],
        observed_at=observed_at,
        stale_after=timedelta(seconds=10),
    )
    decision = decide_day_entry_with_index_trend(states=(state,))

    assert not decision.allowed
    assert decision.reason == "index-trend-stale"


def test_index_trend_warming_up_blocks_day_entry_until_lookback_is_available():
    observed_at = datetime(2026, 5, 15, 9, 40, tzinfo=KST)
    bars = [_bar("KOSPI", observed_at - timedelta(minutes=minute), Decimal("100"), Decimal("100")) for minute in range(5)]

    state = build_index_trend_state(index_code="KOSPI", bars=bars, observed_at=observed_at)
    decision = decide_day_entry_with_index_trend(states=(state,))

    assert not decision.allowed
    assert decision.reason == "index-trend-warming-up"


def test_index_trend_ignores_prior_session_lookback_for_current_session_warmup():
    observed_at = datetime(2026, 5, 15, 9, 0, tzinfo=KST)
    prior_session = _index_bars(
        "KOSPI",
        datetime(2026, 5, 14, 15, 30, tzinfo=KST),
        open_price=Decimal("100"),
        close_price=Decimal("101"),
    )
    current_open = _bar("KOSPI", observed_at, Decimal("100"), Decimal("100"))

    state = build_index_trend_state(
        index_code="KOSPI",
        bars=[*prior_session, current_open],
        observed_at=observed_at,
    )
    decision = decide_day_entry_with_index_trend(states=(state,))

    assert state.ret_30m is None
    assert not decision.allowed
    assert decision.reason == "index-trend-warming-up"


def test_single_bearish_index_blocks_day_entry():
    observed_at = datetime(2026, 5, 15, 9, 40, tzinfo=KST)
    states = (
        build_index_trend_state(index_code="KOSPI", bars=_index_bars("KOSPI", observed_at, open_price=Decimal("100"), close_price=Decimal("98.5")), observed_at=observed_at),
        build_index_trend_state(index_code="KOSDAQ", bars=_index_bars("KOSDAQ", observed_at, open_price=Decimal("200"), close_price=Decimal("200")), observed_at=observed_at),
    )

    decision = decide_day_entry_with_index_trend(states=states)

    assert not decision.allowed
    assert decision.reason == "index-trend-bearish"


def _index_bars(symbol: str, observed_at: datetime, *, open_price: Decimal, close_price: Decimal) -> list[Bar]:
    bars = []
    for minute in range(31):
        timestamp = observed_at - timedelta(minutes=30 - minute)
        price = open_price + (close_price - open_price) * Decimal(minute) / Decimal("30")
        bars.append(_bar(symbol, timestamp, open_price, price))
    return bars


def _bar(symbol: str, timestamp: datetime, open_price: Decimal, price: Decimal) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=open_price,
        high=max(open_price, price),
        low=min(open_price, price),
        close=price,
        volume=1000,
        value=price * Decimal("1000"),
    )
