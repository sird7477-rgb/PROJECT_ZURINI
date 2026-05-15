from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    value: Decimal
    source: str = "dummy"
    bid_ask_ratio: Decimal = Decimal("2.0")


@dataclass(frozen=True)
class SignalIntent:
    action: str
    weight: Decimal = Decimal("0")
    reason: str = ""
    score: Decimal = Decimal("0")
    profit_target: Decimal | None = None
    hard_stop: Decimal | None = None
    max_holding_minutes: int | None = None
    day_end_exit: bool | None = None
    group: str = ""
    strategy_id: str = ""


@dataclass(frozen=True)
class Trade:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    reason: str
    ambiguous_intrabar: bool = False
    execution_note: str = ""
    strategy_id: str = ""
    strategy_group: str = ""
    entry_rule: str = ""
    exit_rule: str = ""
    slot_id: str = ""
    cost_model: str = ""
    applied_profit_target: Decimal | None = None
    applied_hard_stop: Decimal | None = None
    applied_max_holding_minutes: int | None = None
    applied_day_end_exit: bool | None = None


@dataclass(frozen=True)
class BacktestReport:
    trade_count: int
    gross_pnl: Decimal
    net_pnl: Decimal
    max_drawdown: Decimal
    start_equity: Decimal
    end_equity: Decimal
    external_contributions: Decimal = Decimal("0")
