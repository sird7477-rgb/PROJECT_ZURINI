from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from zurini.data.dummy import money
from zurini.market import Bar, SignalIntent
from zurini.strategies.baseline import RiskState
from zurini.strategies.regime import (
    RegimeFilteredStrategy,
    RegimeState,
    RelativeStrengthFilteredStrategy,
    build_regime_states,
)


def test_regime_states_use_previous_daily_closes_only():
    start = datetime(2026, 1, 1, 15, 30, tzinfo=ZoneInfo("Asia/Seoul")).date()
    daily = [(start + timedelta(days=index), Decimal(100 + index)) for index in range(61)]

    regimes = build_regime_states(daily)

    first_regime = regimes[start + timedelta(days=60)]
    assert first_regime.name == "bull"
    assert first_regime.sma5 == Decimal("157")
    assert first_regime.sma20 == Decimal("149.5")
    assert first_regime.sma60 == Decimal("129.5")


def test_regime_filtered_strategy_blocks_bear_entries():
    class BuyAlways:
        def on_bar(self, bar, risk=None):
            return SignalIntent("buy", weight=Decimal("1"))

    session_date = datetime(2026, 1, 5, tzinfo=ZoneInfo("Asia/Seoul")).date()
    regimes = build_regime_states(
        [(session_date - timedelta(days=60 - index), Decimal(200 - index)) for index in range(61)]
    )
    strategy = RegimeFilteredStrategy(
        BuyAlways,
        regimes=regimes,
        allowed_regimes=frozenset({"bull", "range"}),
    )
    bar = Bar(
        "A000001",
        datetime(2026, 1, 5, 9, 1, tzinfo=ZoneInfo("Asia/Seoul")),
        money(100),
        money(100),
        money(100),
        money(100),
        10,
        money(1000),
    )

    signal = strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))

    assert signal.action == "hold"
    assert signal.reason == "regime-blocked-bear"


def test_regime_filter_does_not_consume_inner_state_when_blocked():
    class BuyOnce:
        def __init__(self):
            self.entered = False

        def on_bar(self, bar, risk=None):
            if self.entered:
                return SignalIntent("hold", reason="already-entered")
            self.entered = True
            return SignalIntent("buy", weight=Decimal("1"), reason="buy-once")

    blocked_day = datetime(2026, 1, 5, tzinfo=ZoneInfo("Asia/Seoul")).date()
    allowed_day = blocked_day + timedelta(days=1)
    strategy = RegimeFilteredStrategy(
        BuyOnce,
        regimes={
            blocked_day: RegimeState("bear", Decimal("1"), Decimal("2"), Decimal("3")),
            allowed_day: RegimeState("bull", Decimal("3"), Decimal("2"), Decimal("1")),
        },
        allowed_regimes=frozenset({"bull"}),
    )
    blocked_bar = Bar("A000001", datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")), money(100), money(100), money(100), money(100), 10, money(1000))
    allowed_bar = Bar("A000001", datetime(2026, 1, 6, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")), money(100), money(100), money(100), money(100), 10, money(1000))

    assert strategy.on_bar(blocked_bar).reason == "regime-blocked-bear"
    assert strategy.on_bar(allowed_bar).action == "buy"


def test_relative_strength_filter_does_not_consume_inner_state_when_blocked():
    class BuyOnce:
        def __init__(self):
            self.entered = False

        def on_bar(self, bar, risk=None):
            if self.entered:
                return SignalIntent("hold", reason="already-entered")
            self.entered = True
            return SignalIntent("buy", weight=Decimal("1"), reason="buy-once")

    first = datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    second = first + timedelta(minutes=1)
    strategy = RelativeStrengthFilteredStrategy(
        BuyOnce,
        index_bars={
            first: Bar("U001", first, money(100), money(100), money(100), money(100), 10, money(1000)),
            second: Bar("U001", second, money(100), money(100), money(100), money(100), 10, money(1000)),
        },
        min_relative_return=Decimal("0.01"),
    )
    blocked_bar = Bar("A000001", first, money(100), money(100), money(100), money(100), 10, money(1000))
    allowed_bar = Bar("A000001", second, money(100), money(102), money(100), money(102), 10, money(1020))

    assert strategy.on_bar(blocked_bar).reason == "relative-strength-blocked"
    assert strategy.on_bar(allowed_bar).action == "buy"
