from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from zurini.market import Bar

KST = ZoneInfo("Asia/Seoul")


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def generate_dummy_bars(
    *,
    symbol: str = "ZRN001",
    seed: int = 7477,
    trading_day: str = "2026-01-05",
    minutes: int = 30,
) -> list[Bar]:
    rng = random.Random(seed)
    start = datetime.fromisoformat(f"{trading_day}T09:00:00").replace(tzinfo=KST)
    price = money("10000")
    bars: list[Bar] = []

    # Path creates impulse, first VWAP pullback, and later profit target.
    offsets = [
        Decimal("0.000"),
        Decimal("0.012"),
        Decimal("0.016"),
        Decimal("0.011"),
        Decimal("0.006"),
        Decimal("0.004"),
        Decimal("0.008"),
        Decimal("0.018"),
        Decimal("0.032"),
        Decimal("0.039"),
    ]

    for index in range(minutes):
        if index < len(offsets):
            close = money(Decimal("10000") * (Decimal("1") + offsets[index]))
        else:
            drift = Decimal(str(rng.uniform(-0.0015, 0.0025)))
            close = money(price * (Decimal("1") + drift))

        open_ = price
        spread = money(max(open_, close) * Decimal("0.0015"))
        high = money(max(open_, close) + spread)
        low = money(min(open_, close) - spread)
        volume = 1000 + index * 17 + rng.randint(0, 25)
        if index in {1, 2, 5}:
            volume *= 4
        value = money(close * Decimal(volume))
        bid_ask_ratio = Decimal("2.5") if index in {4, 5, 6} else Decimal("1.4")

        bars.append(
            Bar(
                symbol=symbol,
                timestamp=start + timedelta(minutes=index),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                value=value,
                source="dummy",
                bid_ask_ratio=bid_ask_ratio,
            )
        )
        price = close

    return bars
