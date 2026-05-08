from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from zurini.market import BacktestReport, Bar, Trade
from zurini.strategies.baseline import RiskState, VwapFirstPullbackStrategy


@dataclass(frozen=True)
class BacktestConfig:
    start_equity: Decimal = Decimal("10000000")
    fee_rate: Decimal = Decimal("0.00015")
    slippage_rate: Decimal = Decimal("0.00050")
    profit_target: Decimal = Decimal("0.03")
    hard_stop: Decimal = Decimal("-0.03")


def run_backtest(
    bars: list[Bar],
    *,
    strategy: VwapFirstPullbackStrategy | None = None,
    risk: RiskState | None = None,
    config: BacktestConfig | None = None,
) -> tuple[BacktestReport, list[Trade]]:
    if not bars:
        raise ValueError("bars are required")
    symbols = {bar.symbol for bar in bars}
    if len(symbols) != 1:
        raise ValueError("phase-1 backtest supports exactly one symbol per run")

    strategy = strategy or VwapFirstPullbackStrategy()
    config = config or BacktestConfig()
    cash = config.start_equity
    peak_equity = config.start_equity
    max_drawdown = Decimal("0")
    position_qty = Decimal("0")
    entry_price: Decimal | None = None
    entry_time = None
    trades: list[Trade] = []
    ordered = sorted(bars, key=lambda item: (item.symbol, item.timestamp))

    for index, bar in enumerate(ordered):
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
            continue

        assert entry_price is not None
        pnl_ratio = (bar.close - entry_price) / entry_price
        final_bar = index == len(ordered) - 1
        exit_reason = ""
        if pnl_ratio >= config.profit_target:
            exit_reason = "profit-target"
        elif pnl_ratio <= config.hard_stop:
            exit_reason = "hard-stop"
        elif final_bar:
            exit_reason = "end-of-test"

        mark_equity = cash + position_qty * bar.close
        peak_equity = max(peak_equity, mark_equity)
        drawdown = (mark_equity - peak_equity) / peak_equity
        max_drawdown = min(max_drawdown, drawdown)

        if exit_reason:
            exit_price = bar.close * (Decimal("1") - config.slippage_rate)
            gross_pnl = (exit_price - entry_price) * position_qty
            fees = (entry_price + exit_price) * position_qty * config.fee_rate
            net_pnl = gross_pnl - fees
            cash += position_qty * exit_price - (exit_price * position_qty * config.fee_rate)
            trades.append(
                Trade(
                    symbol=bar.symbol,
                    entry_time=entry_time,
                    exit_time=bar.timestamp,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=position_qty,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    reason=exit_reason,
                )
            )
            position_qty = Decimal("0")
            entry_price = None
            entry_time = None

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
    return report, trades
