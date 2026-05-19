from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

from zurini.market import Bar


KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class PostCloseSwingReboundConfig:
    decision_start: time = time(15, 10)
    decision_end: time = time(15, 35)
    min_intraday_low_drop: Decimal = Decimal("0.02")
    min_reclaim_from_low: Decimal = Decimal("0.01")
    min_range_position: Decimal = Decimal("0.45")
    min_volume_ratio: Decimal = Decimal("0.80")
    max_rsi: Decimal = Decimal("85")
    min_history_closes: int = 19
    volume_window: int = 5

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["decision_start"] = self.decision_start.isoformat(timespec="minutes")
        payload["decision_end"] = self.decision_end.isoformat(timespec="minutes")
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class PostCloseSwingReboundCandidate:
    symbol: str
    timestamp: str
    close: Decimal
    low_drop: Decimal
    reclaim_from_low: Decimal
    range_position: Decimal
    volume_ratio: Decimal
    rsi: Decimal
    score: Decimal
    reason: str = "post-close-swing-rebound"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload


def post_close_swing_rebound_candidate(
    *,
    bar: Bar,
    prior_closes: list[Decimal],
    prior_volumes: list[int],
    config: PostCloseSwingReboundConfig | None = None,
) -> PostCloseSwingReboundCandidate | None:
    active = config or PostCloseSwingReboundConfig()
    current_time = bar.timestamp.astimezone(KST).time()
    if current_time < active.decision_start or current_time > active.decision_end:
        return None
    if len(prior_closes) < active.min_history_closes:
        return None
    if len(prior_volumes) < active.volume_window:
        return None
    if bar.open <= 0 or bar.low <= 0 or bar.high <= bar.low:
        return None

    close = bar.close
    low_drop = (bar.open - bar.low) / bar.open
    reclaim_from_low = (close - bar.low) / bar.low
    range_position = (close - bar.low) / (bar.high - bar.low)
    average_volume = Decimal(sum(prior_volumes[-active.volume_window :])) / Decimal(active.volume_window)
    volume_ratio = Decimal(bar.volume) / average_volume if average_volume else Decimal("999")
    rsi = _rsi([*prior_closes[-14:], close])

    if low_drop < active.min_intraday_low_drop:
        return None
    if reclaim_from_low < active.min_reclaim_from_low:
        return None
    if range_position < active.min_range_position:
        return None
    if volume_ratio < active.min_volume_ratio:
        return None
    if rsi >= active.max_rsi:
        return None

    score = reclaim_from_low + range_position / Decimal("10") + min(volume_ratio, Decimal("5")) / Decimal("100")
    return PostCloseSwingReboundCandidate(
        symbol=bar.symbol,
        timestamp=bar.timestamp.isoformat(),
        close=close,
        low_drop=low_drop,
        reclaim_from_low=reclaim_from_low,
        range_position=range_position,
        volume_ratio=volume_ratio,
        rsi=rsi,
        score=score,
    )


def _rsi(closes: list[Decimal]) -> Decimal:
    if len(closes) < 15:
        return Decimal("100")
    gains = Decimal("0")
    losses = Decimal("0")
    for previous, current in zip(closes, closes[1:]):
        change = current - previous
        if change >= 0:
            gains += change
        else:
            losses += abs(change)
    if losses == 0:
        return Decimal("100")
    relative_strength = gains / losses
    return Decimal("100") - (Decimal("100") / (Decimal("1") + relative_strength))
