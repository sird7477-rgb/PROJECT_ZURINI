from datetime import time, timedelta
from decimal import Decimal

from zurini.data.dummy import generate_dummy_bars
from zurini.data.validation import validate_bars
from zurini.strategies.baseline import RiskState, VwapFirstPullbackStrategy


def test_dummy_bars_are_deterministic_and_valid():
    first = generate_dummy_bars(seed=7477)
    second = generate_dummy_bars(seed=7477)

    assert first == second
    assert len(validate_bars(first)) == 30
    assert all(bar.symbol == "ZRN001" for bar in first)
    assert first == sorted(first, key=lambda bar: (bar.symbol, bar.timestamp))


def test_dummy_bars_trigger_baseline_vwap_signal():
    bars = generate_dummy_bars(seed=7477)
    strategy = VwapFirstPullbackStrategy()
    signals = [
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))
        for bar in bars
    ]

    assert any(signal.action == "buy" for signal in signals)


def test_baseline_vwap_signal_resets_each_trading_day():
    first_day = generate_dummy_bars(seed=7477)
    second_day = [
        type(bar)(
            symbol=bar.symbol,
            timestamp=bar.timestamp + timedelta(days=1),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            value=bar.value,
            source=bar.source,
            bid_ask_ratio=bar.bid_ask_ratio,
        )
        for bar in first_day
    ]
    strategy = VwapFirstPullbackStrategy()

    signals = [
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))
        for bar in [*first_day, *second_day]
    ]

    assert sum(1 for signal in signals if signal.action == "buy") == 2


def test_baseline_vwap_respects_entry_start_window():
    bars = generate_dummy_bars(seed=7477)
    strategy = VwapFirstPullbackStrategy(entry_start=time(15, 0))

    signals = [
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))
        for bar in bars
    ]

    assert all(signal.action == "hold" for signal in signals)


def test_baseline_vwap_respects_min_impulse_volume():
    bars = generate_dummy_bars(seed=7477)
    strategy = VwapFirstPullbackStrategy(min_impulse_volume=10_000_000)

    signals = [
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))
        for bar in bars
    ]

    assert all(signal.action == "hold" for signal in signals)


def test_baseline_vwap_respects_relative_impulse_volume():
    bars = generate_dummy_bars(seed=7477)
    strategy = VwapFirstPullbackStrategy(
        impulse_volume_window=20,
        impulse_volume_multiple=Decimal("100"),
    )

    signals = [
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))
        for bar in bars
    ]

    assert all(signal.action == "hold" for signal in signals)


def test_baseline_vwap_breakout_mode_can_enter_on_impulse():
    bars = generate_dummy_bars(seed=7477)
    strategy = VwapFirstPullbackStrategy(entry_mode="breakout", min_bid_ask_ratio=Decimal("0"))

    signals = [
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))
        for bar in bars
    ]

    assert any(signal.reason == "vwap-breakout" for signal in signals)
