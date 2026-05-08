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
