from decimal import Decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from zurini.backtest.engine import BacktestConfig, run_backtest
from zurini.data.dummy import money
from zurini.data.dummy import generate_dummy_bars
from zurini.market import Bar, SignalIntent
from zurini.strategies.baseline import (
    ConfirmedPullbackDayStrategy,
    DaySupportPullbackStrategy,
    GapReboundDayStrategy,
    IntradayMomentumContinuationStrategy,
    OpeningRangeBreakoutDayStrategy,
    PriorMomentumContinuationStrategy,
    RiskState,
    SwingSupportStrategy,
)


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


def test_risk_state_reports_specific_block_reason():
    timestamp = datetime(2026, 5, 14, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bar = Bar("A000001", timestamp, money(100), money(101), money(99), money(100), 1000, money(100000))

    assert RiskState().block_reason(bar) == "risk-block:missing-blacklist-heartbeat"
    assert (
        RiskState(blacklist_updated_at=timestamp - timedelta(minutes=6)).block_reason(bar)
        == "risk-block:stale-blacklist-heartbeat"
    )
    assert (
        RiskState(blacklist_updated_at=timestamp, blacklisted_symbols=frozenset({"A000001"})).block_reason(bar)
        == "risk-block:blacklisted-symbol"
    )


def test_swing_support_uses_first_snapshot_after_decision_time():
    start = datetime(2026, 1, 5, 15, 15, tzinfo=ZoneInfo("Asia/Seoul"))
    strategy = SwingSupportStrategy(
        decision_time=start.time(),
        sma_window=3,
        volume_window=2,
        support_band=Decimal("0.20"),
        max_volume_ratio=Decimal("2.00"),
        max_rsi=Decimal("101"),
    )
    bars = [
        Bar("FIXTURE", start + timedelta(days=day), money(100), money(101), money(99), money(100), 1000, money(100000))
        for day in range(2)
    ]
    decision_bar = Bar(
        "FIXTURE",
        start + timedelta(days=2, seconds=20),
        money(100),
        money(101),
        money(99),
        money(100),
        1000,
        money(100000),
    )

    for bar in bars:
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))

    assert strategy.on_bar(decision_bar, RiskState(blacklist_updated_at=decision_bar.timestamp)).action == "buy"


def test_plan_a_day_leg_blocks_pre_1000_signal_by_entry_window():
    strategy = IntradayMomentumContinuationStrategy(
        sma_window=2,
        atr_window=1,
        value_window=1,
        min_average_value=Decimal("1"),
        min_atr_ratio=Decimal("0.001"),
        min_session_value=Decimal("1"),
        min_bid_ask_ratio=Decimal("1"),
        max_opening_gap=Decimal("0.10"),
        entry_start=datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")).time(),
        entry_end=datetime(2026, 1, 5, 13, 30, tzinfo=ZoneInfo("Asia/Seoul")).time(),
        min_day_return=Decimal("0.01"),
        max_day_return=Decimal("0.20"),
        min_vwap_distance=Decimal("0.001"),
    )
    prior_1 = Bar("A000001", datetime(2026, 1, 5, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")), money(100), money(104), money(99), money(100), 1000, money(100000))
    prior_2 = Bar("A000001", datetime(2026, 1, 6, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")), money(101), money(105), money(100), money(102), 1000, money(102000))
    warmup = Bar("A000001", datetime(2026, 1, 7, 9, 58, tzinfo=ZoneInfo("Asia/Seoul")), money(102), money(102), money(102), money(102), 1000, money(102000))
    pre_1000_signal = Bar("A000001", datetime(2026, 1, 7, 9, 59, tzinfo=ZoneInfo("Asia/Seoul")), money(102), money(106), money(102), money(106), 1000, money(106000))

    for bar in (prior_1, prior_2, warmup):
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))

    signal = strategy.on_bar(pre_1000_signal, RiskState(blacklist_updated_at=pre_1000_signal.timestamp))

    assert signal.action == "hold"
    assert signal.reason == "entry-window"


def test_plan_a_day_leg_allows_same_signal_at_1000():
    strategy = IntradayMomentumContinuationStrategy(
        sma_window=2,
        atr_window=1,
        value_window=1,
        min_average_value=Decimal("1"),
        min_atr_ratio=Decimal("0.001"),
        min_session_value=Decimal("1"),
        min_bid_ask_ratio=Decimal("1"),
        max_opening_gap=Decimal("0.10"),
        entry_start=datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")).time(),
        entry_end=datetime(2026, 1, 5, 13, 30, tzinfo=ZoneInfo("Asia/Seoul")).time(),
        min_day_return=Decimal("0.01"),
        max_day_return=Decimal("0.20"),
        min_vwap_distance=Decimal("0.001"),
    )
    prior_1 = Bar("A000001", datetime(2026, 1, 5, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")), money(100), money(104), money(99), money(100), 1000, money(100000))
    prior_2 = Bar("A000001", datetime(2026, 1, 6, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")), money(101), money(105), money(100), money(102), 1000, money(102000))
    warmup = Bar("A000001", datetime(2026, 1, 7, 9, 58, tzinfo=ZoneInfo("Asia/Seoul")), money(102), money(102), money(102), money(102), 1000, money(102000))
    at_1000_signal = Bar("A000001", datetime(2026, 1, 7, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")), money(102), money(106), money(102), money(106), 1000, money(106000))

    for bar in (prior_1, prior_2, warmup):
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))

    signal = strategy.on_bar(at_1000_signal, RiskState(blacklist_updated_at=at_1000_signal.timestamp))

    assert signal.action == "buy"
    assert signal.reason == "intraday-momentum-continuation"


def _plan_a_day_signal_at(signal_time: datetime) -> SignalIntent:
    strategy = IntradayMomentumContinuationStrategy(
        sma_window=2,
        atr_window=1,
        value_window=1,
        min_average_value=Decimal("1"),
        min_atr_ratio=Decimal("0.001"),
        min_session_value=Decimal("1"),
        min_bid_ask_ratio=Decimal("1"),
        max_opening_gap=Decimal("0.10"),
        entry_start=datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")).time(),
        entry_end=datetime(2026, 1, 5, 13, 30, tzinfo=ZoneInfo("Asia/Seoul")).time(),
        min_day_return=Decimal("0.01"),
        max_day_return=Decimal("0.20"),
        min_vwap_distance=Decimal("0.001"),
    )
    prior_1 = Bar("A000001", datetime(2026, 1, 5, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")), money(100), money(104), money(99), money(100), 1000, money(100000))
    prior_2 = Bar("A000001", datetime(2026, 1, 6, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")), money(101), money(105), money(100), money(102), 1000, money(102000))
    warmup = Bar("A000001", datetime(2026, 1, 7, 13, 29, tzinfo=ZoneInfo("Asia/Seoul")), money(102), money(102), money(102), money(102), 1000, money(102000))
    signal_bar = Bar("A000001", signal_time, money(102), money(106), money(102), money(106), 1000, money(106000))

    for bar in (prior_1, prior_2, warmup):
        strategy.on_bar(bar, RiskState(blacklist_updated_at=bar.timestamp))
    return strategy.on_bar(signal_bar, RiskState(blacklist_updated_at=signal_bar.timestamp))


def test_plan_a_day_leg_allows_1330_boundary_signal():
    signal = _plan_a_day_signal_at(datetime(2026, 1, 7, 13, 30, tzinfo=ZoneInfo("Asia/Seoul")))

    assert signal.action == "buy"
    assert signal.reason == "intraday-momentum-continuation"


def test_plan_a_day_leg_blocks_1331_signal_by_entry_window():
    signal = _plan_a_day_signal_at(datetime(2026, 1, 7, 13, 31, tzinfo=ZoneInfo("Asia/Seoul")))

    assert signal.action == "hold"
    assert signal.reason == "entry-window"


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


def test_backtest_nonzero_costs_reduce_net_pnl_exactly():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("FIXTURE", start + timedelta(minutes=1), money(104), money(104), money(104), money(104), 10, money(1040)),
    ]

    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    _report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0.001"),
            slippage_rate=Decimal("0.01"),
            profit_target=Decimal("0.01"),
        ),
    )

    trade = trades[0]
    expected_fees = (trade.entry_price + trade.exit_price) * trade.quantity * Decimal("0.001")
    assert trade.entry_price == Decimal("101.00")
    assert trade.entry_price * trade.quantity * Decimal("1.001") <= Decimal("1000")
    assert trade.exit_price == Decimal("102.96")
    assert trade.net_pnl == trade.gross_pnl - expected_fees


def test_backtest_can_use_whole_share_position_sizing():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(330), money(330), money(330), money(330), 10, money(3300)),
        Bar("FIXTURE", start + timedelta(minutes=1), money(340), money(340), money(340), money(340), 10, money(3400)),
    ]

    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    _report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            profit_target=Decimal("0.01"),
        ),
    )

    assert trades[0].quantity == Decimal("3")


def test_backtest_skips_unaffordable_whole_share_entry():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(1100), money(1100), money(1100), money(1100), 10, money(11000)),
        Bar("FIXTURE", start + timedelta(minutes=1), money(1200), money(1200), money(1200), money(1200), 10, money(12000)),
    ]

    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
        ),
    )

    assert trades == []
    assert report.end_equity == Decimal("1000")


def test_shared_slot_capital_mode_uses_portfolio_slots():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = []
    for symbol in ["AAA", "BBB"]:
        bars.extend(
            [
                Bar(symbol, start, money(100), money(100), money(100), money(100), 10, money(1000)),
                Bar(symbol, start + timedelta(minutes=1), money(104), money(104), money(104), money(104), 10, money(1040)),
            ]
        )

    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    _report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            profit_target=Decimal("0.03"),
            capital_mode="shared-slot",
            max_open_positions=2,
        ),
    )

    assert len(trades) == 2
    assert {trade.quantity for trade in trades} == {Decimal("5")}


def test_shared_slot_intrabar_exit_uses_signal_specific_thresholds():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("AAA", start, money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("AAA", start + timedelta(minutes=1), money(101), money(103), money(100), money(101), 10, money(1010)),
    ]

    class CustomExitStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent(
                "buy",
                weight=Decimal("1.0"),
                reason="custom-entry",
                strategy_id="C-IDMOM-D3-U1-S1",
                profit_target=Decimal("0.03"),
                hard_stop=Decimal("-0.20"),
                max_holding_minutes=30,
                day_end_exit=True,
                group="day",
            )

    _report, trades = run_backtest(
        bars,
        strategy_factory=CustomExitStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            profit_target=Decimal("0.50"),
            hard_stop=Decimal("-0.50"),
            intrabar_policy="conservative",
            capital_mode="shared-slot",
            max_open_positions=1,
        ),
    )

    assert len(trades) == 1
    assert trades[0].reason == "profit-target"
    assert trades[0].exit_price == Decimal("103.00")
    assert trades[0].strategy_id == "C-IDMOM-D3-U1-S1"
    assert trades[0].strategy_group == "day"
    assert trades[0].entry_rule == "custom-entry"
    assert trades[0].exit_rule == "profit-target"
    assert trades[0].slot_id == "shared-slot-1"
    assert trades[0].cost_model == "fee_rate=0;slippage_rate=0"
    assert trades[0].applied_profit_target == Decimal("0.03")
    assert trades[0].applied_hard_stop == Decimal("-0.20")
    assert trades[0].applied_max_holding_minutes == 30
    assert trades[0].applied_day_end_exit is True


def test_shared_slot_signal_day_end_exit_overrides_disabled_global_policy():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    day_end = start.replace(hour=15, minute=15)
    bars = [
        Bar("AAA", start, money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("AAA", day_end, money(100), money(100), money(100), money(100), 10, money(1000)),
    ]

    class SignalDayEndExitStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent(
                "buy",
                weight=Decimal("1.0"),
                reason="custom-entry",
                strategy_id="C-IDMOM-D3-U1-S1",
                profit_target=Decimal("0.50"),
                hard_stop=Decimal("-0.50"),
                max_holding_minutes=None,
                day_end_exit=True,
                group="day",
            )

    _report, trades = run_backtest(
        bars,
        strategy_factory=SignalDayEndExitStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            day_end_exit=False,
            day_end_exit_time=day_end.time(),
            capital_mode="shared-slot",
            max_open_positions=1,
        ),
    )

    assert len(trades) == 1
    assert trades[0].reason == "day-end"
    assert trades[0].applied_day_end_exit is True


def test_per_symbol_intrabar_exit_uses_signal_specific_thresholds():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("AAA", start, money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("AAA", start + timedelta(minutes=1), money(101), money(103), money(100), money(101), 10, money(1010)),
    ]

    class CustomExitStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent(
                "buy",
                weight=Decimal("1.0"),
                reason="custom-entry",
                strategy_id="C-IDMOM-D3-U1-S1",
                profit_target=Decimal("0.03"),
                hard_stop=Decimal("-0.20"),
                max_holding_minutes=30,
                day_end_exit=True,
                group="day",
            )

    _report, trades = run_backtest(
        bars,
        strategy_factory=CustomExitStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            profit_target=Decimal("0.50"),
            hard_stop=Decimal("-0.50"),
            intrabar_policy="conservative",
        ),
    )

    assert len(trades) == 1
    assert trades[0].reason == "profit-target"
    assert trades[0].exit_price == Decimal("103.00")
    assert trades[0].strategy_id == "C-IDMOM-D3-U1-S1"
    assert trades[0].strategy_group == "day"
    assert trades[0].entry_rule == "custom-entry"
    assert trades[0].exit_rule == "profit-target"
    assert trades[0].slot_id == "per-symbol-AAA"
    assert trades[0].cost_model == "fee_rate=0;slippage_rate=0"
    assert trades[0].applied_profit_target == Decimal("0.03")
    assert trades[0].applied_hard_stop == Decimal("-0.20")
    assert trades[0].applied_max_holding_minutes == 30
    assert trades[0].applied_day_end_exit is True


def test_shared_slot_preserves_explicit_zero_exit_overrides():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("AAA", start, money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("AAA", start + timedelta(minutes=1), money(101), money(101), money(99), money(101), 10, money(1010)),
    ]

    class ZeroTargetStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent(
                "buy",
                weight=Decimal("1.0"),
                profit_target=Decimal("0"),
                hard_stop=Decimal("0"),
            )

    _report, trades = run_backtest(
        bars,
        strategy_factory=ZeroTargetStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            profit_target=Decimal("0.50"),
            hard_stop=Decimal("-0.50"),
            capital_mode="shared-slot",
            max_open_positions=1,
        ),
    )

    assert len(trades) == 1
    assert trades[0].reason == "profit-target"
    assert trades[0].exit_price == Decimal("101.000000")


def test_shared_slot_stop_fuse_counts_stop_first_execution_notes():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("AAA", start, money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("BBB", start, money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("AAA", start + timedelta(minutes=1), money(100), money(106), money(94), money(101), 10, money(1010)),
        Bar("BBB", start + timedelta(minutes=1), money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("BBB", start + timedelta(minutes=2), money(104), money(104), money(104), money(104), 10, money(1040)),
    ]

    class StaggeredBuyStrategy:
        def on_bar(self, bar, risk=None):
            if bar.symbol == "AAA" and bar.timestamp.minute == 0:
                return SignalIntent("buy", weight=Decimal("1.0"))
            if bar.symbol == "BBB" and bar.timestamp.minute == 1:
                return SignalIntent("buy", weight=Decimal("1.0"))
            return SignalIntent("hold")

    _report, trades = run_backtest(
        bars,
        strategy_factory=StaggeredBuyStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            profit_target=Decimal("0.03"),
            hard_stop=Decimal("-0.03"),
            intrabar_policy="conservative",
            capital_mode="shared-slot",
            max_open_positions=2,
            max_daily_stop_losses=1,
        ),
    )

    assert len(trades) == 1
    assert trades[0].symbol == "AAA"
    assert trades[0].reason == "hard-stop"
    assert trades[0].execution_note == "target-and-stop-touched-stop-first"


def test_shared_slot_entry_candidates_use_signal_score_before_symbol_order():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = []
    for symbol in ["AAA", "BBB"]:
        bars.extend(
            [
                Bar(symbol, start, money(100), money(100), money(100), money(100), 10, money(1000)),
                Bar(symbol, start + timedelta(minutes=1), money(104), money(104), money(104), money(104), 10, money(1040)),
            ]
        )

    class ScoredBuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            score = Decimal("10") if bar.symbol == "BBB" else Decimal("1")
            return SignalIntent("buy", weight=Decimal("1.0"), score=score)

    _report, trades = run_backtest(
        bars,
        strategy_factory=ScoredBuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            profit_target=Decimal("0.03"),
            capital_mode="shared-slot",
            max_open_positions=1,
        ),
    )

    assert [trade.symbol for trade in trades] == ["BBB"]


def test_shared_slot_entry_candidates_obey_signal_group_caps():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = []
    for symbol in ["DAY1", "DAY2", "SWING"]:
        bars.extend(
            [
                Bar(symbol, start, money(100), money(100), money(100), money(100), 10, money(1000)),
                Bar(symbol, start + timedelta(minutes=1), money(104), money(104), money(104), money(104), 10, money(1040)),
            ]
        )

    class GroupedBuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            group = "swing" if bar.symbol == "SWING" else "day"
            score = {
                "DAY1": Decimal("10"),
                "DAY2": Decimal("9"),
                "SWING": Decimal("1"),
            }[bar.symbol]
            return SignalIntent("buy", weight=Decimal("1.0"), score=score, group=group)

    _report, trades = run_backtest(
        bars,
        strategy_factory=GroupedBuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("3000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            profit_target=Decimal("0.03"),
            capital_mode="shared-slot",
            max_open_positions=3,
            signal_group_max_open_positions=(("day", 1),),
        ),
    )

    assert [trade.symbol for trade in trades] == ["DAY1", "SWING"]


def test_shared_slot_final_bar_entry_is_liquidated_at_end_of_test():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("AAA", start, money(100), money(100), money(100), money(100), 10, money(1000)),
    ]

    class FinalBarBuyStrategy:
        def on_bar(self, bar, risk=None):
            return SignalIntent("buy", weight=Decimal("1.0"))

    report, trades = run_backtest(
        bars,
        strategy_factory=FinalBarBuyStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            capital_mode="shared-slot",
            max_open_positions=1,
        ),
    )

    assert len(trades) == 1
    assert trades[0].reason == "end-of-test"
    assert report.end_equity == Decimal("1000")


def test_shared_slot_variable_slot_count_uses_equity_and_slot_cap():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = []
    for symbol in ["AAA", "BBB"]:
        bars.extend(
            [
                Bar(symbol, start, money(100), money(100), money(100), money(100), 10, money(1000)),
                Bar(symbol, start + timedelta(minutes=1), money(104), money(104), money(104), money(104), 10, money(1040)),
            ]
        )

    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    _report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            profit_target=Decimal("0.03"),
            capital_mode="shared-slot",
            variable_slot_count=True,
            slot_capital_cap=Decimal("600"),
        ),
    )

    assert len(trades) == 2
    assert {trade.quantity for trade in trades} == {Decimal("5")}


def test_shared_slot_rejects_zero_max_positions_with_variable_slots():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("AAA", start, money(100), money(100), money(100), money(100), 10, money(1000)),
    ]

    class BuyStrategy:
        def on_bar(self, bar, risk=None):
            return SignalIntent("buy", weight=Decimal("1.0"))

    with pytest.raises(ValueError, match="max_open_positions"):
        run_backtest(
            bars,
            strategy_factory=BuyStrategy,
            config=BacktestConfig(
                start_equity=Decimal("1000"),
                fee_rate=Decimal("0"),
                slippage_rate=Decimal("0"),
                capital_mode="shared-slot",
                max_open_positions=0,
                variable_slot_count=True,
                slot_capital_cap=Decimal("100"),
            ),
        )


def test_weekly_contributions_are_reported_separately_from_trading_pnl():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("FIXTURE", start + timedelta(days=7), money(100), money(100), money(100), money(100), 10, money(1000)),
    ]

    class HoldStrategy:
        def on_bar(self, bar, risk=None):
            return SignalIntent("hold")

    report, trades = run_backtest(
        bars,
        strategy_factory=HoldStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            weekly_contribution=Decimal("100"),
        ),
    )

    assert trades == []
    assert report.net_pnl == Decimal("0")
    assert report.external_contributions == Decimal("100")
    assert report.end_equity == Decimal("1100")


def test_defensive_pullback_day_strategy_requires_prior_universe_before_entry():
    from zurini.strategies.baseline import DefensivePullbackDayStrategy

    start = datetime(2026, 1, 5, 9, 5, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar(
            "FIXTURE",
            start + timedelta(days=day),
            money(100 + day),
            money(105 + day),
            money(98 + day),
            money(102 + day),
            1000,
            money((102 + day) * 1000),
        )
        for day in range(20)
    ]
    bars.append(
        Bar(
            "FIXTURE",
            start + timedelta(days=20),
            money(130),
            money(131),
            money(129),
            money(130),
            1000,
            money(130000),
            bid_ask_ratio=Decimal("2.5"),
        )
    )
    bars.append(
        Bar(
            "FIXTURE",
            start + timedelta(days=20, minutes=1),
            money(130),
            money(131),
            money(129),
            money(130),
            1000,
            money(130000),
            bid_ask_ratio=Decimal("2.5"),
        )
    )
    bars.append(
        Bar(
            "FIXTURE",
            start + timedelta(days=20, minutes=2),
            money(130),
            money(131),
            money(129),
            money(130),
            1000,
            money(130000),
            bid_ask_ratio=Decimal("2.5"),
        )
    )

    report, trades = run_backtest(
        bars,
        strategy_factory=lambda: DefensivePullbackDayStrategy(
            min_average_value=Decimal("0"),
            min_atr_ratio=Decimal("0.01"),
            pullback_band=Decimal("0.10"),
            max_opening_gap=Decimal("0.30"),
            entry_start=start.time(),
            entry_end=(start + timedelta(minutes=1)).time(),
        ),
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            day_end_exit_time=(start + timedelta(minutes=2)).time(),
        ),
    )

    assert report.trade_count == 1
    assert trades[0].reason == "day-end"
    assert trades[0].entry_time == start + timedelta(days=20, minutes=1)


def test_day_support_pullback_strategy_enters_from_prior_support_context():
    start = datetime(2026, 1, 5, 14, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(100), money(101), money(99), money(100), 1000, money(100000)),
        Bar("FIXTURE", start + timedelta(days=1), money(100), money(101), money(99), money(100), 1000, money(100000)),
        Bar(
            "FIXTURE",
            start + timedelta(days=2),
            money(100),
            money(101),
            money(99),
            money(100),
            100,
            money(10000),
            bid_ask_ratio=Decimal("2.0"),
        ),
        Bar(
            "FIXTURE",
            start + timedelta(days=2, minutes=45),
            money(101),
            money(103),
            money(101),
            money(102),
            100,
            money(10200),
            bid_ask_ratio=Decimal("2.0"),
        ),
    ]

    report, trades = run_backtest(
        bars,
        strategy_factory=lambda: DaySupportPullbackStrategy(
            entry_start=start.time(),
            entry_end=(start + timedelta(minutes=30)).time(),
            sma_window=3,
            volume_window=2,
            support_band=Decimal("0.02"),
            max_volume_ratio=Decimal("0.20"),
            max_rsi=Decimal("101"),
        ),
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            day_end_exit_time=(start + timedelta(minutes=45)).time(),
        ),
    )

    assert report.trade_count == 1
    assert trades[0].entry_time == start + timedelta(days=2)
    assert trades[0].reason == "day-end"


def test_confirmed_pullback_day_strategy_waits_for_reclaim_before_entry():
    from zurini.strategies.baseline import DefensivePullbackDayStrategy

    start = datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar(
            "FIXTURE",
            start + timedelta(days=day),
            money(100 + day),
            money(105 + day),
            money(98 + day),
            money(102 + day),
            1000,
            money((102 + day) * 1000),
        )
        for day in range(20)
    ]
    bars.extend(
        [
            Bar("FIXTURE", start + timedelta(days=20), money(130), money(130), money(130), money(130), 1000, money(130000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=1), money(130), money(131), money(129), money(130), 1000, money(130000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=2), money(132), money(133), money(132), money(133), 1000, money(133000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=3), money(133), money(134), money(133), money(134), 1000, money(134000), bid_ask_ratio=Decimal("2.5")),
        ]
    )

    common_config = BacktestConfig(
        start_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
        quantity_step=Decimal("1"),
        day_end_exit_time=(start + timedelta(minutes=3)).time(),
    )
    kwargs = {
        "min_average_value": Decimal("0"),
        "min_atr_ratio": Decimal("0.01"),
        "pullback_band": Decimal("0.10"),
        "max_opening_gap": Decimal("0.30"),
        "entry_start": start.time(),
        "entry_end": (start + timedelta(minutes=2)).time(),
    }

    _base_report, base_trades = run_backtest(
        bars,
        strategy_factory=lambda: DefensivePullbackDayStrategy(**kwargs),
        config=common_config,
    )
    _confirmed_report, confirmed_trades = run_backtest(
        bars,
        strategy_factory=lambda: ConfirmedPullbackDayStrategy(reclaim_threshold=Decimal("0.001"), **kwargs),
        config=common_config,
    )

    assert base_trades[0].entry_time == start + timedelta(days=20, minutes=1)
    assert confirmed_trades[0].entry_time == start + timedelta(days=20, minutes=2)


def test_opening_range_breakout_strategy_waits_for_range_then_breakout():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar(
            "FIXTURE",
            start + timedelta(days=day),
            money(100 + day),
            money(105 + day),
            money(98 + day),
            money(102 + day),
            1000,
            money((102 + day) * 1000),
        )
        for day in range(20)
    ]
    bars.extend(
        [
            Bar("FIXTURE", start + timedelta(days=20), money(130), money(131), money(129), money(130), 1000, money(130000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=1), money(130), money(131), money(129), money(130), 1000, money(130000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=2), money(132), money(133), money(132), money(133), 1000, money(133000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=3), money(133), money(134), money(133), money(134), 1000, money(134000), bid_ask_ratio=Decimal("2.5")),
        ]
    )

    report, trades = run_backtest(
        bars,
        strategy_factory=lambda: OpeningRangeBreakoutDayStrategy(
            range_minutes=1,
            breakout_buffer=Decimal("0.001"),
            max_range_ratio=Decimal("0.05"),
            min_average_value=Decimal("0"),
            min_atr_ratio=Decimal("0.01"),
            max_opening_gap=Decimal("0.30"),
            entry_start=(start + timedelta(minutes=2)).time(),
            entry_end=(start + timedelta(minutes=2)).time(),
        ),
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            day_end_exit_time=(start + timedelta(minutes=3)).time(),
        ),
    )

    assert report.trade_count == 1
    assert trades[0].entry_time == start + timedelta(days=20, minutes=2)
    assert trades[0].reason == "day-end"


def test_intraday_momentum_strategy_enters_after_day_return_and_vwap_confirmation():
    start = datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar(
            "FIXTURE",
            start + timedelta(days=day),
            money(100 + day),
            money(105 + day),
            money(98 + day),
            money(102 + day),
            1000,
            money((102 + day) * 1000),
        )
        for day in range(20)
    ]
    bars.extend(
        [
            Bar("FIXTURE", start + timedelta(days=20), money(130), money(130), money(130), money(130), 1000, money(130000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=1), money(130), money(135), money(130), money(135), 1000, money(135000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=2), money(135), money(136), money(135), money(136), 1000, money(136000), bid_ask_ratio=Decimal("2.5")),
        ]
    )

    report, trades = run_backtest(
        bars,
        strategy_factory=lambda: IntradayMomentumContinuationStrategy(
            min_day_return=Decimal("0.03"),
            max_day_return=Decimal("0.10"),
            min_vwap_distance=Decimal("0.001"),
            min_average_value=Decimal("0"),
            min_atr_ratio=Decimal("0.01"),
            max_opening_gap=Decimal("0.30"),
            entry_start=(start + timedelta(minutes=1)).time(),
            entry_end=(start + timedelta(minutes=1)).time(),
        ),
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            day_end_exit_time=(start + timedelta(minutes=2)).time(),
        ),
    )

    assert report.trade_count == 1
    assert trades[0].entry_time == start + timedelta(days=20, minutes=1)
    assert trades[0].reason == "day-end"


def test_prior_momentum_strategy_uses_previous_session_return_before_entry():
    start = datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar(
            "FIXTURE",
            start + timedelta(days=day),
            money(100),
            money(105),
            money(98),
            money(100),
            1000,
            money(100000),
        )
        for day in range(19)
    ]
    bars.extend(
        [
            Bar("FIXTURE", start + timedelta(days=19), money(100), money(107), money(99), money(106), 1000, money(106000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20), money(106), money(108), money(106), money(107), 1000, money(107000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=1), money(107), money(108), money(107), money(108), 1000, money(108000), bid_ask_ratio=Decimal("2.5")),
        ]
    )

    report, trades = run_backtest(
        bars,
        strategy_factory=lambda: PriorMomentumContinuationStrategy(
            min_prior_return=Decimal("0.04"),
            max_prior_return=Decimal("0.10"),
            min_confirm_above_prior_close=Decimal("0.005"),
            min_average_value=Decimal("0"),
            min_atr_ratio=Decimal("0.01"),
            max_opening_gap=Decimal("0.30"),
            entry_start=start.time(),
            entry_end=start.time(),
        ),
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            day_end_exit_time=(start + timedelta(minutes=1)).time(),
        ),
    )

    assert report.trade_count == 1
    assert trades[0].entry_time == start + timedelta(days=20)
    assert trades[0].reason == "day-end"


def test_gap_rebound_strategy_enters_after_gap_down_reclaim():
    start = datetime(2026, 1, 5, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar(
            "FIXTURE",
            start + timedelta(days=day),
            money(100 + day),
            money(105 + day),
            money(98 + day),
            money(102 + day),
            1000,
            money((102 + day) * 1000),
        )
        for day in range(19)
    ]
    bars.extend(
        [
            Bar("FIXTURE", start + timedelta(days=19), money(120), money(122), money(119), money(120), 1000, money(120000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20), money(117), money(121), money(117), money(121), 1000, money(121000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=1), money(121), money(122), money(121), money(122), 1000, money(122000), bid_ask_ratio=Decimal("2.5")),
            Bar("FIXTURE", start + timedelta(days=20, minutes=2), money(122), money(123), money(122), money(123), 1000, money(123000), bid_ask_ratio=Decimal("2.5")),
        ]
    )

    report, trades = run_backtest(
        bars,
        strategy_factory=lambda: GapReboundDayStrategy(
            min_gap_down=Decimal("0.005"),
            max_gap_down=Decimal("0.04"),
            reclaim_over_prior_close=Decimal("0.001"),
            min_vwap_distance=Decimal("0"),
            min_average_value=Decimal("0"),
            min_atr_ratio=Decimal("0.01"),
            min_session_value=Decimal("0"),
            entry_start=start.time(),
            entry_end=(start + timedelta(minutes=1)).time(),
        ),
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            quantity_step=Decimal("1"),
            day_end_exit_time=(start + timedelta(minutes=2)).time(),
        ),
    )

    assert report.trade_count == 1
    assert trades[0].entry_time == start + timedelta(days=20, minutes=1)
    assert trades[0].reason == "day-end"


def test_conservative_intrabar_policy_marks_ambiguous_stop_first():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(100), money(100), money(100), money(100), 10, money(1000)),
        Bar("FIXTURE", start + timedelta(minutes=1), money(100), money(106), money(94), money(101), 10, money(1010)),
    ]

    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    _report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            profit_target=Decimal("0.03"),
            hard_stop=Decimal("-0.03"),
            intrabar_policy="conservative",
        ),
    )

    assert trades[0].reason == "hard-stop"
    assert trades[0].exit_price == Decimal("97.00")
    assert trades[0].ambiguous_intrabar is True
    assert trades[0].execution_note == "target-and-stop-touched-stop-first"


def test_conservative_intrabar_policy_does_not_exit_on_entry_bar_range():
    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(100), money(110), money(90), money(100), 10, money(1000)),
        Bar("FIXTURE", start + timedelta(minutes=1), money(100), money(101), money(99), money(100), 10, money(1000)),
    ]

    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    _report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            profit_target=Decimal("0.03"),
            hard_stop=Decimal("-0.03"),
            intrabar_policy="conservative",
        ),
    )

    assert trades[0].reason == "end-of-test"
    assert trades[0].ambiguous_intrabar is False
    assert trades[0].execution_note == ""


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


def test_backtest_liquidates_open_positions_at_day_end_before_next_session():
    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(100), money(100), money(100), money(100), 1, money(100)),
        Bar(
            "FIXTURE",
            start.replace(hour=15, minute=30),
            money(101),
            money(101),
            money(101),
            money(101),
            1,
            money(101),
        ),
        Bar(
            "FIXTURE",
            start + timedelta(days=1),
            money(102),
            money(102),
            money(102),
            money(102),
            1,
            money(102),
        ),
    ]

    report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            profit_target=Decimal("0.50"),
            hard_stop=Decimal("-0.50"),
        ),
    )

    assert report.trade_count == 1
    assert trades[0].reason == "day-end"
    assert trades[0].exit_time == start.replace(hour=15, minute=30)


def test_backtest_liquidates_open_positions_at_configured_day_end_time():
    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(100), money(100), money(100), money(100), 1, money(100)),
        Bar("FIXTURE", start.replace(hour=15, minute=15), money(101), money(101), money(101), money(101), 1, money(101)),
        Bar("FIXTURE", start.replace(hour=15, minute=30), money(102), money(102), money(102), money(102), 1, money(102)),
    ]

    _report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            profit_target=Decimal("0.50"),
            hard_stop=Decimal("-0.50"),
            day_end_exit_time=start.replace(hour=15, minute=15).time(),
        ),
    )

    assert len(trades) == 1
    assert trades[0].reason == "day-end"
    assert trades[0].exit_time == start.replace(hour=15, minute=15)


def test_backtest_treats_naive_day_end_exit_time_as_kst():
    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    start = datetime(2026, 1, 5, 9, 0)
    bars = [
        Bar("FIXTURE", start, money(100), money(100), money(100), money(100), 1, money(100)),
        Bar("FIXTURE", start.replace(hour=15, minute=15), money(101), money(101), money(101), money(101), 1, money(101)),
        Bar("FIXTURE", start.replace(hour=15, minute=30), money(102), money(102), money(102), money(102), 1, money(102)),
    ]

    _report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            profit_target=Decimal("0.50"),
            hard_stop=Decimal("-0.50"),
            day_end_exit_time=start.replace(hour=15, minute=15).time(),
        ),
    )

    assert len(trades) == 1
    assert trades[0].reason == "day-end"
    assert trades[0].exit_time == start.replace(hour=15, minute=15)


def test_backtest_can_liquidate_after_configured_max_holding_minutes():
    class BuyOnceStrategy:
        def __init__(self):
            self.seen = False

        def on_bar(self, bar, risk=None):
            if self.seen:
                return SignalIntent("hold")
            self.seen = True
            return SignalIntent("buy", weight=Decimal("1.0"))

    start = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    bars = [
        Bar("FIXTURE", start, money(100), money(100), money(100), money(100), 1, money(100)),
        Bar(
            "FIXTURE",
            start + timedelta(minutes=3),
            money(100),
            money(100),
            money(100),
            money(100),
            1,
            money(100),
        ),
    ]

    report, trades = run_backtest(
        bars,
        strategy_factory=BuyOnceStrategy,
        config=BacktestConfig(
            start_equity=Decimal("1000"),
            fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
            profit_target=Decimal("0.50"),
            hard_stop=Decimal("-0.50"),
            max_holding_minutes=3,
        ),
    )

    assert report.trade_count == 1
    assert trades[0].reason == "max-holding"
