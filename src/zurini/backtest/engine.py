from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

from zurini.market import BacktestReport, Bar, SignalIntent, Trade
from zurini.strategies.baseline import RiskState, VwapFirstPullbackStrategy


class Strategy:
    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        raise NotImplementedError


StrategyFactory = Callable[[], Strategy]


@dataclass(frozen=True)
class BacktestConfig:
    start_equity: Decimal = Decimal("10000000")
    fee_rate: Decimal = Decimal("0.00015")
    slippage_rate: Decimal = Decimal("0.00050")
    profit_target: Decimal = Decimal("0.03")
    hard_stop: Decimal = Decimal("-0.03")
    day_end_exit: bool = True
    max_holding_minutes: int | None = None


@dataclass(frozen=True)
class _SymbolRun:
    report: BacktestReport
    trades: list[Trade]
    equity_curve: list[tuple[datetime, Decimal]]


def run_backtest(
    bars: list[Bar],
    *,
    strategy: Strategy | None = None,
    strategy_factory: StrategyFactory | None = None,
    risk: RiskState | None = None,
    risk_factory: Callable[[], RiskState] | None = None,
    config: BacktestConfig | None = None,
) -> tuple[BacktestReport, list[Trade]]:
    if not bars:
        raise ValueError("bars are required")
    if strategy is not None and strategy_factory is not None:
        raise ValueError("use either strategy or strategy_factory, not both")
    if risk is not None and risk_factory is not None:
        raise ValueError("use either risk or risk_factory, not both")

    config = config or BacktestConfig()
    grouped = _group_by_symbol(bars)
    if strategy is not None and len(grouped) > 1:
        raise ValueError("multi-symbol runs require strategy_factory for independent state")

    allocations = _allocate_equity(config.start_equity, sorted(grouped))
    all_trades: list[Trade] = []
    symbol_runs: dict[str, _SymbolRun] = {}

    for symbol in sorted(grouped):
        symbol_config = BacktestConfig(
            start_equity=allocations[symbol],
            fee_rate=config.fee_rate,
            slippage_rate=config.slippage_rate,
            profit_target=config.profit_target,
            hard_stop=config.hard_stop,
            day_end_exit=config.day_end_exit,
            max_holding_minutes=config.max_holding_minutes,
        )
        symbol_strategy = _new_strategy(
            strategy=strategy,
            strategy_factory=strategy_factory,
            multi_symbol=len(grouped) > 1,
        )
        symbol_risk = risk_factory() if risk_factory is not None else deepcopy(risk)
        result = _run_single_symbol(
            grouped[symbol],
            strategy=symbol_strategy,
            risk=symbol_risk,
            config=symbol_config,
        )
        symbol_runs[symbol] = result
        all_trades.extend(result.trades)

    gross_pnl = sum((run.report.gross_pnl for run in symbol_runs.values()), Decimal("0"))
    net_pnl = sum((run.report.net_pnl for run in symbol_runs.values()), Decimal("0"))
    max_drawdown = _portfolio_max_drawdown(symbol_runs, allocations)
    report = BacktestReport(
        trade_count=len(all_trades),
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        max_drawdown=max_drawdown,
        start_equity=config.start_equity,
        end_equity=config.start_equity + net_pnl,
    )
    return report, sorted(all_trades, key=lambda trade: (trade.entry_time, trade.symbol, trade.exit_time))


def _allocate_equity(total: Decimal, symbols: list[str]) -> dict[str, Decimal]:
    cents = Decimal("0.01")
    base = (total / Decimal(len(symbols))).quantize(cents, rounding=ROUND_DOWN)
    allocations = {symbol: base for symbol in symbols}
    remainder = total - base * Decimal(len(symbols))
    if remainder:
        allocations[symbols[0]] += remainder
    return allocations


def _portfolio_max_drawdown(
    symbol_runs: dict[str, _SymbolRun],
    allocations: dict[str, Decimal],
) -> Decimal:
    timeline = sorted(
        {timestamp for run in symbol_runs.values() for timestamp, _equity in run.equity_curve}
    )
    if not timeline:
        return Decimal("0")

    current = dict(allocations)
    points_by_symbol = {
        symbol: {timestamp: equity for timestamp, equity in run.equity_curve}
        for symbol, run in symbol_runs.items()
    }
    peak = sum(current.values(), Decimal("0"))
    max_drawdown = Decimal("0")

    for timestamp in timeline:
        for symbol, points in points_by_symbol.items():
            if timestamp in points:
                current[symbol] = points[timestamp]
        equity = sum(current.values(), Decimal("0"))
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak
        max_drawdown = min(max_drawdown, drawdown)

    return max_drawdown


def _new_strategy(
    *,
    strategy: Strategy | None,
    strategy_factory: StrategyFactory | None,
    multi_symbol: bool,
) -> Strategy:
    if strategy_factory is not None:
        return strategy_factory()
    if strategy is not None and not multi_symbol:
        return strategy
    return VwapFirstPullbackStrategy()


def _group_by_symbol(bars: list[Bar]) -> dict[str, list[Bar]]:
    grouped: dict[str, list[Bar]] = {}
    for bar in bars:
        grouped.setdefault(bar.symbol, []).append(bar)
    return {
        symbol: sorted(symbol_bars, key=lambda item: item.timestamp)
        for symbol, symbol_bars in grouped.items()
    }


def _run_single_symbol(
    ordered: list[Bar],
    *,
    strategy: Strategy,
    risk: RiskState | None,
    config: BacktestConfig,
) -> _SymbolRun:
    cash = config.start_equity
    peak_equity = config.start_equity
    max_drawdown = Decimal("0")
    position_qty = Decimal("0")
    entry_price: Decimal | None = None
    entry_time = None
    previous_bar: Bar | None = None
    trades: list[Trade] = []
    equity_curve: list[tuple[datetime, Decimal]] = []

    for index, bar in enumerate(ordered):
        if (
            position_qty > 0
            and config.day_end_exit
            and previous_bar is not None
            and _session_date(previous_bar.timestamp) != _session_date(bar.timestamp)
        ):
            assert entry_price is not None
            assert entry_time is not None
            trade = _close_position(
                bar=previous_bar,
                entry_price=entry_price,
                entry_time=entry_time,
                position_qty=position_qty,
                config=config,
                reason="day-end",
            )
            cash += trade.exit_price * position_qty - (trade.exit_price * position_qty * config.fee_rate)
            trades.append(trade)
            position_qty = Decimal("0")
            entry_price = None
            entry_time = None

        effective_risk = risk or RiskState(blacklist_updated_at=bar.timestamp)
        if position_qty == 0:
            signal = strategy.on_bar(bar, effective_risk)
            if signal.action == "buy" and signal.weight > 0:
                fill_price = bar.close * (Decimal("1") + config.slippage_rate)
                budget = cash * signal.weight
                position_qty = (budget / fill_price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
                entry_price = fill_price
                entry_time = bar.timestamp
                cash -= position_qty * fill_price
                equity_curve.append((bar.timestamp, cash + position_qty * bar.close))
            else:
                equity_curve.append((bar.timestamp, cash))
            previous_bar = bar
            continue

        assert entry_price is not None
        assert entry_time is not None
        pnl_ratio = (bar.close - entry_price) / entry_price
        final_bar = index == len(ordered) - 1
        exit_reason = ""
        if pnl_ratio >= config.profit_target:
            exit_reason = "profit-target"
        elif pnl_ratio <= config.hard_stop:
            exit_reason = "hard-stop"
        elif config.max_holding_minutes is not None and _holding_minutes(entry_time, bar.timestamp) >= config.max_holding_minutes:
            exit_reason = "max-holding"
        elif final_bar:
            exit_reason = "end-of-test"

        mark_equity = cash + position_qty * bar.close
        peak_equity = max(peak_equity, mark_equity)
        drawdown = (mark_equity - peak_equity) / peak_equity
        max_drawdown = min(max_drawdown, drawdown)
        equity_curve.append((bar.timestamp, mark_equity))

        if exit_reason:
            trade = _close_position(
                bar=bar,
                entry_price=entry_price,
                entry_time=entry_time,
                position_qty=position_qty,
                config=config,
                reason=exit_reason,
            )
            cash += trade.exit_price * position_qty - (trade.exit_price * position_qty * config.fee_rate)
            trades.append(trade)
            position_qty = Decimal("0")
            entry_price = None
            entry_time = None
        previous_bar = bar

    gross_pnl = sum((trade.gross_pnl for trade in trades), Decimal("0"))
    net_pnl = sum((trade.net_pnl for trade in trades), Decimal("0"))
    report = BacktestReport(
        trade_count=len(trades),
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        max_drawdown=max_drawdown,
        start_equity=config.start_equity,
        end_equity=config.start_equity + net_pnl,
    )
    return _SymbolRun(report=report, trades=trades, equity_curve=equity_curve)


def _close_position(
    *,
    bar: Bar,
    entry_price: Decimal,
    entry_time: datetime,
    position_qty: Decimal,
    config: BacktestConfig,
    reason: str,
) -> Trade:
    exit_price = bar.close * (Decimal("1") - config.slippage_rate)
    gross_pnl = (exit_price - entry_price) * position_qty
    fees = (entry_price + exit_price) * position_qty * config.fee_rate
    net_pnl = gross_pnl - fees
    return Trade(
        symbol=bar.symbol,
        entry_time=entry_time,
        exit_time=bar.timestamp,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=position_qty,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        reason=reason,
    )


def _session_date(timestamp: datetime):
    if timestamp.tzinfo is None:
        return timestamp.date()
    return timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()


def _holding_minutes(entry_time: datetime, current_time: datetime) -> int:
    return int((current_time - entry_time).total_seconds() // 60)
