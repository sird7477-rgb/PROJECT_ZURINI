from decimal import Decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from zurini.backtest.engine import BacktestConfig, run_backtest
from zurini.data.dummy import money
from zurini.data.dummy import generate_dummy_bars
from zurini.market import Bar, SignalIntent
from zurini.strategies.baseline import RiskState


def test_backtest_report_is_deterministic_and_complete():
    bars = generate_dummy_bars(seed=7477)
    report_a, trades_a = run_backtest(bars)
    report_b, trades_b = run_backtest(bars)

    assert report_a == report_b
    assert trades_a == trades_b
    assert report_a.trade_count >= 1
    assert report_a.start_equity == Decimal("10000000")
    assert report_a.end_equity == report_a.start_equity + report_a.net_pnl
    assert report_a.max_drawdown <= Decimal("0")


def test_backtest_hand_checkable_profit_target_fixture():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    closes = [Decimal("100.0"), Decimal("102.0"), Decimal("101.2"), Decimal("104.236")]
    volumes = [1000, 4000, 1200, 1000]
    bars = [
        Bar(
            symbol="FIXTURE",
            timestamp=start + timedelta(minutes=index),
            open=money(close),
            high=money(close * Decimal("1.001")),
            low=money(close * Decimal("0.999")),
            close=money(close),
            volume=volumes[index],
            value=money(close * volumes[index]),
            bid_ask_ratio=Decimal("2.5"),
        )
        for index, close in enumerate(closes)
    ]

    report, trades = run_backtest(
        bars,
        config=BacktestConfig(
            start_equity=Decimal("10000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
        ),
    )

    assert report.trade_count == 1
    assert trades[0].reason == "profit-target"
    assert report.gross_pnl.quantize(Decimal("0.01")) == Decimal("300.00")
    assert report.net_pnl.quantize(Decimal("0.01")) == Decimal("300.00")


def test_beta_throttle_blocks_entries_at_all_stop():
    report, trades = run_backtest(
        generate_dummy_bars(seed=7477),
        risk=RiskState(nasdaq_future_return=Decimal("-0.05")),
        config=BacktestConfig(start_equity=Decimal("1000000")),
    )

    assert trades == []
    assert report.trade_count == 0
    assert report.end_equity == Decimal("1000000")


def test_blacklist_blocks_entries_conservatively():
    report, trades = run_backtest(
        generate_dummy_bars(seed=7477),
        risk=RiskState(blacklisted_symbols=frozenset({"ZRN001"})),
    )

    assert trades == []
    assert report.trade_count == 0


def test_missing_blacklist_heartbeat_blocks_entries_conservatively():
    report, trades = run_backtest(generate_dummy_bars(seed=7477), risk=RiskState())

    assert trades == []
    assert report.trade_count == 0


def test_phase_one_backtest_supports_multi_symbol_runs():
    second_symbol = generate_dummy_bars(symbol="ZRN002", trading_day="2026-01-06")
    bars = generate_dummy_bars(symbol="ZRN001") + second_symbol

    report, trades = run_backtest(bars)

    assert report.trade_count == 2
    assert {trade.symbol for trade in trades} == {"ZRN001", "ZRN002"}
    assert [trade.entry_time for trade in trades] == sorted(trade.entry_time for trade in trades)
    assert report.start_equity == Decimal("10000000")
    assert report.end_equity == report.start_equity + report.net_pnl


def test_multi_symbol_run_uses_strategy_factory_per_symbol():
    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    bars = generate_dummy_bars(symbol="ZRN001")[:3] + generate_dummy_bars(symbol="ZRN002")[:3]

    report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(fee_rate=Decimal("0"), slippage_rate=Decimal("0")),
    )

    assert report.trade_count == 2
    assert {trade.symbol for trade in trades} == {"ZRN001", "ZRN002"}


def test_multi_symbol_non_divisible_equity_allocation_is_deterministic():
    bars = (
        generate_dummy_bars(symbol="ZRN001")
        + generate_dummy_bars(symbol="ZRN002")
        + generate_dummy_bars(symbol="ZRN003")
    )

    report_a, trades_a = run_backtest(bars, config=BacktestConfig(start_equity=Decimal("10000.01")))
    report_b, trades_b = run_backtest(bars, config=BacktestConfig(start_equity=Decimal("10000.01")))

    assert report_a == report_b
    assert trades_a == trades_b
    assert report_a.start_equity == Decimal("10000.01")
    assert report_a.end_equity == report_a.start_equity + report_a.net_pnl


def test_multi_symbol_run_rejects_shared_strategy_instance():
    bars = generate_dummy_bars(symbol="ZRN001") + generate_dummy_bars(symbol="ZRN002")

    with pytest.raises(ValueError, match="strategy_factory"):
        run_backtest(bars, strategy=object())
