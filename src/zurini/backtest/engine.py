from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from zoneinfo import ZoneInfo

from zurini.market import BacktestReport, Bar, SignalIntent, Trade
from zurini.strategies.baseline import RiskState, VwapFirstPullbackStrategy

KST = ZoneInfo("Asia/Seoul")


class Strategy:
    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        raise NotImplementedError


StrategyFactory = Callable[[], Strategy]


@dataclass(frozen=True)
class BacktestConfig:
    start_equity: Decimal = Decimal("10000000")
    fee_rate: Decimal = Decimal("0.00015")
    slippage_rate: Decimal = Decimal("0.00050")
    quantity_step: Decimal = Decimal("0.000001")
    profit_target: Decimal = Decimal("0.03")
    hard_stop: Decimal = Decimal("-0.03")
    day_end_exit: bool = True
    day_end_exit_time: time | None = None
    max_holding_minutes: int | None = None
    intrabar_policy: str = "close-only"
    ambiguous_intrabar_policy: str = "stop-first"
    capital_mode: str = "per-symbol"
    max_open_positions: int = 5
    variable_slot_count: bool = False
    slot_capital_cap: Decimal | None = None
    weekly_contribution: Decimal = Decimal("0")
    max_daily_stop_losses: int | None = None
    max_daily_loss: Decimal | None = None
    signal_group_max_open_positions: tuple[tuple[str, int], ...] = ()
    signal_group_strategy_ids: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class _SymbolRun:
    report: BacktestReport
    trades: list[Trade]
    equity_curve: list[tuple[datetime, Decimal]]


@dataclass
class _OpenPosition:
    quantity: Decimal
    entry_price: Decimal
    entry_time: datetime
    profit_target: Decimal
    hard_stop: Decimal
    max_holding_minutes: int | None
    day_end_exit: bool
    group: str = ""
    strategy_id: str = ""
    entry_rule: str = ""
    slot_id: str = "shared-slot"


@dataclass(frozen=True)
class _EntryCandidate:
    bar: Bar
    signal: SignalIntent


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
    if config.capital_mode == "shared-slot":
        if strategy is not None:
            raise ValueError("shared-slot runs require strategy_factory for independent symbol state")
        return _run_shared_slot_backtest(
            grouped,
            strategy_factory=strategy_factory or VwapFirstPullbackStrategy,
            risk=risk,
            risk_factory=risk_factory,
            config=config,
        )
    if config.capital_mode != "per-symbol":
        raise ValueError("capital_mode must be 'per-symbol' or 'shared-slot'")
    if strategy is not None and len(grouped) > 1:
        raise ValueError("multi-symbol runs require strategy_factory for independent state")

    symbols = sorted(grouped)
    allocations = _allocate_equity(config.start_equity, symbols)
    contribution_allocations = _allocate_equity(config.weekly_contribution, symbols)
    all_trades: list[Trade] = []
    symbol_runs: dict[str, _SymbolRun] = {}

    for symbol in symbols:
        symbol_config = BacktestConfig(
            start_equity=allocations[symbol],
            fee_rate=config.fee_rate,
            slippage_rate=config.slippage_rate,
            quantity_step=config.quantity_step,
            profit_target=config.profit_target,
            hard_stop=config.hard_stop,
            day_end_exit=config.day_end_exit,
            day_end_exit_time=config.day_end_exit_time,
            max_holding_minutes=config.max_holding_minutes,
            intrabar_policy=config.intrabar_policy,
            ambiguous_intrabar_policy=config.ambiguous_intrabar_policy,
            capital_mode=config.capital_mode,
            max_open_positions=config.max_open_positions,
            variable_slot_count=config.variable_slot_count,
            slot_capital_cap=config.slot_capital_cap,
            weekly_contribution=contribution_allocations[symbol],
            max_daily_stop_losses=config.max_daily_stop_losses,
            max_daily_loss=config.max_daily_loss,
            signal_group_max_open_positions=config.signal_group_max_open_positions,
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
    external_contributions = sum(
        (run.report.external_contributions for run in symbol_runs.values()),
        Decimal("0"),
    )
    max_drawdown = _portfolio_max_drawdown(symbol_runs, allocations)
    report = BacktestReport(
        trade_count=len(all_trades),
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        max_drawdown=max_drawdown,
        start_equity=config.start_equity,
        end_equity=_end_equity(config.start_equity, net_pnl, external_contributions),
        external_contributions=external_contributions,
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


def _run_shared_slot_backtest(
    grouped: dict[str, list[Bar]],
    *,
    strategy_factory: StrategyFactory,
    risk: RiskState | None,
    risk_factory: Callable[[], RiskState] | None,
    config: BacktestConfig,
) -> tuple[BacktestReport, list[Trade]]:
    if config.max_open_positions <= 0:
        raise ValueError("max_open_positions must be positive")
    if config.slot_capital_cap is not None and config.slot_capital_cap <= 0:
        raise ValueError("slot_capital_cap must be positive")
    if config.variable_slot_count and config.slot_capital_cap is None:
        raise ValueError("variable_slot_count requires slot_capital_cap")
    group_limits = _signal_group_max_open_positions(config)

    strategies = {symbol: strategy_factory() for symbol in grouped}
    risks = {
        symbol: risk_factory() if risk_factory is not None else deepcopy(risk)
        for symbol in grouped
    }
    positions: dict[str, _OpenPosition] = {}
    previous_bars: dict[str, Bar] = {}
    latest_closes: dict[str, Decimal] = {}
    cash = config.start_equity
    peak_equity = config.start_equity
    external_contributions = Decimal("0")
    current_contribution_week: tuple[int, int] | None = None
    max_drawdown = Decimal("0")
    trades: list[Trade] = []
    equity_curve: list[tuple[datetime, Decimal]] = []
    stop_losses_by_day: dict[object, int] = {}
    pnl_by_day: dict[object, Decimal] = {}

    bars_by_timestamp: dict[datetime, list[Bar]] = defaultdict(list)
    final_timestamp_by_symbol: dict[str, datetime] = {}
    for symbol_bars in grouped.values():
        for bar in symbol_bars:
            bars_by_timestamp[bar.timestamp].append(bar)
            final_timestamp_by_symbol[bar.symbol] = bar.timestamp

    for timestamp in sorted(bars_by_timestamp):
        contribution_week = _contribution_week(timestamp)
        if current_contribution_week is None:
            current_contribution_week = contribution_week
        elif contribution_week != current_contribution_week:
            cash += config.weekly_contribution
            external_contributions += config.weekly_contribution
            current_contribution_week = contribution_week

        timestamp_bars = sorted(bars_by_timestamp[timestamp], key=lambda item: item.symbol)
        for bar in timestamp_bars:
            latest_closes[bar.symbol] = bar.close

        entry_candidates: list[_EntryCandidate] = []
        for bar in timestamp_bars:
            previous_bar = previous_bars.get(bar.symbol)
            position = positions.get(bar.symbol)
            if (
                position is not None
                and position.day_end_exit
                and previous_bar is not None
                and _session_date(previous_bar.timestamp) != _session_date(bar.timestamp)
            ):
                trade = _close_position(
                    bar=previous_bar,
                    entry_price=position.entry_price,
                    entry_time=position.entry_time,
                    position_qty=position.quantity,
                    config=config,
                    reason="day-end",
                    strategy_group=position.group,
                    strategy_id=position.strategy_id,
                    entry_rule=position.entry_rule,
                    slot_id=position.slot_id,
                    applied_profit_target=position.profit_target,
                    applied_hard_stop=position.hard_stop,
                    applied_max_holding_minutes=position.max_holding_minutes,
                    applied_day_end_exit=position.day_end_exit,
                )
                cash = _record_shared_slot_exit(
                    trade=trade,
                    position=position,
                    config=config,
                    cash=cash,
                    trades=trades,
                    pnl_by_day=pnl_by_day,
                    stop_losses_by_day=stop_losses_by_day,
                )
                del positions[bar.symbol]
                position = None

            if position is None:
                effective_risk = risks[bar.symbol] or RiskState(blacklist_updated_at=bar.timestamp)
                signal = strategies[bar.symbol].on_bar(bar, effective_risk)
                session_date = _session_date(bar.timestamp)
                stop_fuse_open = (
                    config.max_daily_stop_losses is not None
                    and stop_losses_by_day.get(session_date, 0) >= config.max_daily_stop_losses
                )
                loss_fuse_open = (
                    config.max_daily_loss is not None
                    and pnl_by_day.get(session_date, Decimal("0")) <= -config.max_daily_loss
                )
                if (
                    signal.action == "buy"
                    and signal.weight > 0
                    and not stop_fuse_open
                    and not loss_fuse_open
                ):
                    entry_candidates.append(_EntryCandidate(bar=bar, signal=signal))
            else:
                exit_reason, exit_reference_price, ambiguous_intrabar, execution_note = _exit_decision(
                    bar=bar,
                    entry_price=position.entry_price,
                    config=config,
                    profit_target=position.profit_target,
                    hard_stop=position.hard_stop,
                )
                pnl_ratio = (bar.close - position.entry_price) / position.entry_price
                final_symbol_bar = final_timestamp_by_symbol[bar.symbol] == bar.timestamp
                if not exit_reason and pnl_ratio >= position.profit_target:
                    exit_reason = "profit-target"
                elif not exit_reason and pnl_ratio <= position.hard_stop:
                    exit_reason = "hard-stop"
                elif (
                    not exit_reason
                    and position.max_holding_minutes is not None
                    and _holding_minutes(position.entry_time, bar.timestamp) >= position.max_holding_minutes
                ):
                    exit_reason = "max-holding"
                elif not exit_reason and position.day_end_exit and _is_day_end_exit_bar_for_policy(bar, config):
                    exit_reason = "day-end"
                elif not exit_reason and final_symbol_bar:
                    exit_reason = "end-of-test"

                if exit_reason:
                    trade = _close_position(
                        bar=bar,
                        entry_price=position.entry_price,
                        entry_time=position.entry_time,
                        position_qty=position.quantity,
                        config=config,
                        reason=exit_reason,
                        reference_price=exit_reference_price,
                        ambiguous_intrabar=ambiguous_intrabar,
                        execution_note=execution_note,
                        strategy_group=position.group,
                        strategy_id=position.strategy_id,
                        entry_rule=position.entry_rule,
                        slot_id=position.slot_id,
                        applied_profit_target=position.profit_target,
                        applied_hard_stop=position.hard_stop,
                        applied_max_holding_minutes=position.max_holding_minutes,
                        applied_day_end_exit=position.day_end_exit,
                    )
                    cash = _record_shared_slot_exit(
                        trade=trade,
                        position=position,
                        config=config,
                        cash=cash,
                        trades=trades,
                        pnl_by_day=pnl_by_day,
                        stop_losses_by_day=stop_losses_by_day,
                    )
                    del positions[bar.symbol]

        for candidate in sorted(entry_candidates, key=lambda item: (-item.signal.score, item.bar.symbol)):
            bar = candidate.bar
            signal = candidate.signal
            if bar.symbol in positions:
                continue
            session_date = _session_date(bar.timestamp)
            stop_fuse_open = (
                config.max_daily_stop_losses is not None
                and stop_losses_by_day.get(session_date, 0) >= config.max_daily_stop_losses
            )
            loss_fuse_open = (
                config.max_daily_loss is not None
                and pnl_by_day.get(session_date, Decimal("0")) <= -config.max_daily_loss
            )
            if stop_fuse_open or loss_fuse_open:
                continue
            fill_price = bar.close * (Decimal("1") + config.slippage_rate)
            portfolio_equity = _portfolio_equity(cash, positions, latest_closes, config)
            effective_slots = _effective_max_open_positions(portfolio_equity, config)
            if len(positions) >= effective_slots:
                continue
            if signal.group and _open_group_count(positions, signal.group) >= group_limits.get(
                signal.group,
                effective_slots,
            ):
                continue
            slot_budget = portfolio_equity / Decimal(effective_slots)
            if config.slot_capital_cap is not None:
                slot_budget = min(slot_budget, config.slot_capital_cap)
            budget = min(cash, slot_budget * signal.weight)
            quantity = (budget / (fill_price * (Decimal("1") + config.fee_rate))).quantize(
                config.quantity_step,
                rounding=ROUND_DOWN,
            )
            if quantity > 0:
                cash -= quantity * fill_price * (Decimal("1") + config.fee_rate)
                positions[bar.symbol] = _OpenPosition(
                    quantity=quantity,
                    entry_price=fill_price,
                    entry_time=bar.timestamp,
                    profit_target=(
                        signal.profit_target if signal.profit_target is not None else config.profit_target
                    ),
                    hard_stop=signal.hard_stop if signal.hard_stop is not None else config.hard_stop,
                    max_holding_minutes=(
                        signal.max_holding_minutes
                        if signal.max_holding_minutes is not None
                        else config.max_holding_minutes
                    ),
                    day_end_exit=signal.day_end_exit if signal.day_end_exit is not None else config.day_end_exit,
                    group=signal.group,
                    strategy_id=_strategy_id_for_signal(signal, config),
                    entry_rule=signal.reason,
                    slot_id=f"shared-slot-{len(positions) + 1}",
                )

        for bar in timestamp_bars:
            previous_bars[bar.symbol] = bar
        equity = _portfolio_equity(cash, positions, latest_closes, config)
        peak_equity = max(peak_equity, equity)
        drawdown = (equity - peak_equity) / peak_equity
        max_drawdown = min(max_drawdown, drawdown)
        equity_curve.append((timestamp, equity))

    for symbol, position in list(positions.items()):
        final_bar = max(grouped[symbol], key=lambda item: item.timestamp)
        trade = _close_position(
            bar=final_bar,
            entry_price=position.entry_price,
            entry_time=position.entry_time,
            position_qty=position.quantity,
            config=config,
            reason="end-of-test",
            strategy_group=position.group,
            strategy_id=position.strategy_id,
            entry_rule=position.entry_rule,
            slot_id=position.slot_id,
            applied_profit_target=position.profit_target,
            applied_hard_stop=position.hard_stop,
            applied_max_holding_minutes=position.max_holding_minutes,
            applied_day_end_exit=position.day_end_exit,
        )
        cash = _record_shared_slot_exit(
            trade=trade,
            position=position,
            config=config,
            cash=cash,
            trades=trades,
            pnl_by_day=pnl_by_day,
            stop_losses_by_day=stop_losses_by_day,
        )
        del positions[symbol]

    net_pnl = sum((trade.net_pnl for trade in trades), Decimal("0"))
    gross_pnl = sum((trade.gross_pnl for trade in trades), Decimal("0"))
    return (
        BacktestReport(
            trade_count=len(trades),
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            max_drawdown=max_drawdown,
            start_equity=config.start_equity,
            end_equity=_end_equity(config.start_equity, net_pnl, external_contributions),
            external_contributions=external_contributions,
        ),
        sorted(trades, key=lambda trade: (trade.entry_time, trade.symbol, trade.exit_time)),
    )


def _portfolio_equity(
    cash: Decimal,
    positions: dict[str, _OpenPosition],
    latest_closes: dict[str, Decimal],
    config: BacktestConfig,
) -> Decimal:
    return cash + sum(
        position.quantity * latest_closes.get(symbol, position.entry_price) * (Decimal("1") - config.fee_rate)
        for symbol, position in positions.items()
    )


def _record_shared_slot_exit(
    *,
    trade: Trade,
    position: _OpenPosition,
    config: BacktestConfig,
    cash: Decimal,
    trades: list[Trade],
    pnl_by_day: dict[object, Decimal],
    stop_losses_by_day: dict[object, int],
) -> Decimal:
    trades.append(trade)
    pnl_day = _session_date(trade.exit_time)
    pnl_by_day[pnl_day] = pnl_by_day.get(pnl_day, Decimal("0")) + trade.net_pnl
    if _is_stop_loss_trade(trade):
        stop_losses_by_day[pnl_day] = stop_losses_by_day.get(pnl_day, 0) + 1
    return cash + _cash_from_exit(trade, position.quantity, config)


def _effective_max_open_positions(equity: Decimal, config: BacktestConfig) -> int:
    if not config.variable_slot_count:
        return config.max_open_positions
    assert config.slot_capital_cap is not None
    if equity <= 0:
        return 1
    derived_slots = max(
        1,
        int((equity / config.slot_capital_cap).to_integral_value(rounding=ROUND_CEILING)),
    )
    return min(config.max_open_positions, derived_slots)


def _signal_group_max_open_positions(config: BacktestConfig) -> dict[str, int]:
    limits: dict[str, int] = {}
    for group, limit in config.signal_group_max_open_positions:
        if not group:
            raise ValueError("signal group name must be non-empty")
        if limit <= 0:
            raise ValueError("signal group max open positions must be positive")
        limits[group] = limit
    return limits


def _open_group_count(positions: dict[str, _OpenPosition], group: str) -> int:
    return sum(1 for position in positions.values() if position.group == group)


def _contribution_week(timestamp: datetime) -> tuple[int, int]:
    iso_year, iso_week, _weekday = timestamp.isocalendar()
    return iso_year, iso_week


def _is_day_end_exit_bar(bar: Bar, config: BacktestConfig) -> bool:
    if not config.day_end_exit or config.day_end_exit_time is None:
        return False
    return _is_day_end_exit_bar_for_policy(bar, config)


def _is_day_end_exit_bar_for_policy(bar: Bar, config: BacktestConfig) -> bool:
    if config.day_end_exit_time is None:
        return False
    if bar.timestamp.tzinfo is None:
        return bar.timestamp.time() >= config.day_end_exit_time
    return bar.timestamp.astimezone(KST).time() >= config.day_end_exit_time


def _end_equity(start_equity: Decimal, net_pnl: Decimal, external_contributions: Decimal) -> Decimal:
    return start_equity + external_contributions + net_pnl


def _run_single_symbol(
    ordered: list[Bar],
    *,
    strategy: Strategy,
    risk: RiskState | None,
    config: BacktestConfig,
) -> _SymbolRun:
    cash = config.start_equity
    peak_equity = config.start_equity
    external_contributions = Decimal("0")
    current_contribution_week: tuple[int, int] | None = None
    max_drawdown = Decimal("0")
    position_qty = Decimal("0")
    entry_price: Decimal | None = None
    entry_time = None
    previous_bar: Bar | None = None
    trades: list[Trade] = []
    equity_curve: list[tuple[datetime, Decimal]] = []
    position_group = ""
    position_strategy_id = ""
    position_entry_rule = ""
    position_slot_id = "per-symbol"
    position_profit_target = config.profit_target
    position_hard_stop = config.hard_stop
    position_max_holding_minutes = config.max_holding_minutes
    position_day_end_exit = config.day_end_exit

    for index, bar in enumerate(ordered):
        contribution_week = _contribution_week(bar.timestamp)
        if current_contribution_week is None:
            current_contribution_week = contribution_week
        elif contribution_week != current_contribution_week:
            cash += config.weekly_contribution
            external_contributions += config.weekly_contribution
            current_contribution_week = contribution_week

        if (
            position_qty > 0
            and position_day_end_exit
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
                strategy_group=position_group,
                strategy_id=position_strategy_id,
                entry_rule=position_entry_rule,
                slot_id=position_slot_id,
                applied_profit_target=position_profit_target,
                applied_hard_stop=position_hard_stop,
                applied_max_holding_minutes=position_max_holding_minutes,
                applied_day_end_exit=position_day_end_exit,
            )
            cash += trade.exit_price * position_qty - (trade.exit_price * position_qty * config.fee_rate)
            trades.append(trade)
            position_qty = Decimal("0")
            entry_price = None
            entry_time = None
            position_group = ""
            position_strategy_id = ""
            position_entry_rule = ""
            position_slot_id = "per-symbol"
            position_profit_target = config.profit_target
            position_hard_stop = config.hard_stop
            position_max_holding_minutes = config.max_holding_minutes
            position_day_end_exit = config.day_end_exit

        effective_risk = risk or RiskState(blacklist_updated_at=bar.timestamp)
        if position_qty == 0:
            signal = strategy.on_bar(bar, effective_risk)
            if signal.action == "buy" and signal.weight > 0:
                fill_price = bar.close * (Decimal("1") + config.slippage_rate)
                budget = cash * signal.weight
                position_qty = (budget / (fill_price * (Decimal("1") + config.fee_rate))).quantize(
                    config.quantity_step,
                    rounding=ROUND_DOWN,
                )
                if position_qty <= 0:
                    equity_curve.append((bar.timestamp, cash))
                    previous_bar = bar
                    continue
                entry_price = fill_price
                entry_time = bar.timestamp
                position_group = signal.group
                position_strategy_id = _strategy_id_for_signal(signal, config)
                position_entry_rule = signal.reason
                position_slot_id = f"per-symbol-{bar.symbol}"
                position_profit_target = (
                    signal.profit_target if signal.profit_target is not None else config.profit_target
                )
                position_hard_stop = signal.hard_stop if signal.hard_stop is not None else config.hard_stop
                position_max_holding_minutes = (
                    signal.max_holding_minutes
                    if signal.max_holding_minutes is not None
                    else config.max_holding_minutes
                )
                position_day_end_exit = signal.day_end_exit if signal.day_end_exit is not None else config.day_end_exit
                cash -= position_qty * fill_price * (Decimal("1") + config.fee_rate)
                equity_curve.append((bar.timestamp, cash + position_qty * bar.close))
            else:
                equity_curve.append((bar.timestamp, cash))
            previous_bar = bar
            continue

        assert entry_price is not None
        assert entry_time is not None
        exit_reason, exit_reference_price, ambiguous_intrabar, execution_note = _exit_decision(
            bar=bar,
            entry_price=entry_price,
            config=config,
            profit_target=position_profit_target,
            hard_stop=position_hard_stop,
        )
        pnl_ratio = (bar.close - entry_price) / entry_price
        final_bar = index == len(ordered) - 1
        if not exit_reason and pnl_ratio >= position_profit_target:
            exit_reason = "profit-target"
        elif not exit_reason and pnl_ratio <= position_hard_stop:
            exit_reason = "hard-stop"
        elif (
            not exit_reason
            and position_max_holding_minutes is not None
            and _holding_minutes(entry_time, bar.timestamp) >= position_max_holding_minutes
        ):
            exit_reason = "max-holding"
        elif not exit_reason and position_day_end_exit and _is_day_end_exit_bar_for_policy(bar, config):
            exit_reason = "day-end"
        elif not exit_reason and final_bar:
            exit_reason = "end-of-test"

        mark_equity = cash + position_qty * bar.close * (Decimal("1") - config.fee_rate)
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
                reference_price=exit_reference_price,
                ambiguous_intrabar=ambiguous_intrabar,
                execution_note=execution_note,
                strategy_group=position_group,
                strategy_id=position_strategy_id,
                entry_rule=position_entry_rule,
                slot_id=position_slot_id,
                applied_profit_target=position_profit_target,
                applied_hard_stop=position_hard_stop,
                applied_max_holding_minutes=position_max_holding_minutes,
                applied_day_end_exit=position_day_end_exit,
            )
            cash += trade.exit_price * position_qty - (trade.exit_price * position_qty * config.fee_rate)
            trades.append(trade)
            position_qty = Decimal("0")
            entry_price = None
            entry_time = None
            position_group = ""
            position_strategy_id = ""
            position_entry_rule = ""
            position_slot_id = "per-symbol"
            position_profit_target = config.profit_target
            position_hard_stop = config.hard_stop
            position_max_holding_minutes = config.max_holding_minutes
            position_day_end_exit = config.day_end_exit
        previous_bar = bar

    gross_pnl = sum((trade.gross_pnl for trade in trades), Decimal("0"))
    net_pnl = sum((trade.net_pnl for trade in trades), Decimal("0"))
    report = BacktestReport(
        trade_count=len(trades),
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        max_drawdown=max_drawdown,
        start_equity=config.start_equity,
        end_equity=_end_equity(config.start_equity, net_pnl, external_contributions),
        external_contributions=external_contributions,
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
    reference_price: Decimal | None = None,
    ambiguous_intrabar: bool = False,
    execution_note: str = "",
    strategy_id: str = "",
    strategy_group: str = "",
    entry_rule: str = "",
    slot_id: str = "",
    applied_profit_target: Decimal | None = None,
    applied_hard_stop: Decimal | None = None,
    applied_max_holding_minutes: int | None = None,
    applied_day_end_exit: bool | None = None,
) -> Trade:
    exit_price = (reference_price or bar.close) * (Decimal("1") - config.slippage_rate)
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
        ambiguous_intrabar=ambiguous_intrabar,
        execution_note=execution_note,
        strategy_id=strategy_id,
        strategy_group=strategy_group,
        entry_rule=entry_rule,
        exit_rule=reason,
        slot_id=slot_id,
        cost_model=_cost_model(config),
        applied_profit_target=applied_profit_target,
        applied_hard_stop=applied_hard_stop,
        applied_max_holding_minutes=applied_max_holding_minutes,
        applied_day_end_exit=applied_day_end_exit,
    )


def _cost_model(config: BacktestConfig) -> str:
    return f"fee_rate={config.fee_rate};slippage_rate={config.slippage_rate}"


def _strategy_id_for_signal(signal: SignalIntent, config: BacktestConfig) -> str:
    if signal.strategy_id:
        return signal.strategy_id
    return dict(config.signal_group_strategy_ids).get(signal.group, "")


def _cash_from_exit(trade: Trade, quantity: Decimal, config: BacktestConfig) -> Decimal:
    return trade.exit_price * quantity - (trade.exit_price * quantity * config.fee_rate)


def _is_stop_loss_trade(trade: Trade) -> bool:
    note = trade.execution_note.lower()
    return trade.reason == "hard-stop" or "stop" in note


def _exit_decision(
    *,
    bar: Bar,
    entry_price: Decimal,
    config: BacktestConfig,
    profit_target: Decimal | None = None,
    hard_stop: Decimal | None = None,
) -> tuple[str, Decimal | None, bool, str]:
    if config.intrabar_policy == "close-only":
        return "", None, False, ""
    if config.intrabar_policy != "conservative":
        raise ValueError("intrabar_policy must be 'close-only' or 'conservative'")
    if config.ambiguous_intrabar_policy != "stop-first":
        raise ValueError("ambiguous_intrabar_policy must be 'stop-first'")

    target_price = entry_price * (Decimal("1") + (profit_target if profit_target is not None else config.profit_target))
    stop_price = entry_price * (Decimal("1") + (hard_stop if hard_stop is not None else config.hard_stop))
    target_touched = bar.high >= target_price
    stop_touched = bar.low <= stop_price
    if target_touched and stop_touched:
        return "hard-stop", stop_price, True, "target-and-stop-touched-stop-first"
    if stop_touched:
        return "hard-stop", stop_price, False, "intrabar-stop-touched"
    if target_touched:
        return "profit-target", target_price, False, "intrabar-target-touched"
    return "", None, False, ""


def _session_date(timestamp: datetime):
    if timestamp.tzinfo is None:
        return timestamp.date()
    return timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()


def _holding_minutes(entry_time: datetime, current_time: datetime) -> int:
    return int((current_time - entry_time).total_seconds() // 60)
