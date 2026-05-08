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


@dataclass(frozen=True)
class BacktestReport:
    trade_count: int
    gross_pnl: Decimal
    net_pnl: Decimal
    max_drawdown: Decimal
    start_equity: Decimal
    end_equity: Decimal
