from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from zurini.market import Bar


class BarValidationError(ValueError):
    pass


def validate_bar(bar: Bar) -> None:
    required = {
        "symbol": bar.symbol,
        "timestamp": bar.timestamp,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "value": bar.value,
    }
    for field, value in required.items():
        if value is None or value == "":
            raise BarValidationError(f"{field} is required")

    if bar.timestamp.tzinfo is None:
        raise BarValidationError("timestamp must be timezone-aware")
    if bar.volume < 0:
        raise BarValidationError("volume must be nonnegative")
    if bar.value < Decimal("0"):
        raise BarValidationError("value must be nonnegative")
    if bar.high < bar.low:
        raise BarValidationError("high must be greater than or equal to low")
    if not (bar.low <= bar.open <= bar.high):
        raise BarValidationError("open must be within low/high")
    if not (bar.low <= bar.close <= bar.high):
        raise BarValidationError("close must be within low/high")


def validate_bars(bars: Iterable[Bar]) -> list[Bar]:
    seen: set[tuple[str, object]] = set()
    valid = list(bars)
    for bar in valid:
        validate_bar(bar)
        key = (bar.symbol, bar.timestamp)
        if key in seen:
            raise BarValidationError("duplicate symbol + timestamp")
        seen.add(key)
    return valid
