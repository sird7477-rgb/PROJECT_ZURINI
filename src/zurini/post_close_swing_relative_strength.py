from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

from zurini.market import Bar


KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class PostCloseSwingRelativeStrengthConfig:
    candidate_id: str = "post-close-swing-relative-strength"
    decision_start: time = time(15, 10)
    decision_end: time = time(15, 35)
    min_market_down_ratio: Decimal = Decimal("0.60")
    max_symbol_return: Decimal = Decimal("0.04")
    min_relative_return_edge: Decimal = Decimal("0.03")
    max_adverse_from_open: Decimal = Decimal("0.06")
    min_recovery_from_low: Decimal = Decimal("0.01")
    min_traded_value: Decimal = Decimal("50000000000")
    max_rsi: Decimal = Decimal("75")
    min_history_closes: int = 19

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["decision_start"] = self.decision_start.isoformat(timespec="minutes")
        payload["decision_end"] = self.decision_end.isoformat(timespec="minutes")
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class PostCloseSwingRelativeStrengthCandidate:
    symbol: str
    timestamp: str
    close: Decimal
    symbol_return: Decimal
    market_return: Decimal
    relative_return_edge: Decimal
    market_down_ratio: Decimal
    adverse_from_open: Decimal
    recovery_from_low: Decimal
    traded_value: Decimal
    rsi: Decimal
    score: Decimal
    recipe_id: str
    reason: str = "post-close-swing-relative-strength"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload


def post_close_swing_relative_strength_candidate(
    *,
    bar: Bar,
    prior_close: Decimal,
    prior_closes: list[Decimal],
    market_return: Decimal,
    market_down_ratio: Decimal,
    config: PostCloseSwingRelativeStrengthConfig | None = None,
) -> PostCloseSwingRelativeStrengthCandidate | None:
    active = config or PostCloseSwingRelativeStrengthConfig()
    current_time = bar.timestamp.astimezone(KST).time()
    if current_time < active.decision_start or current_time > active.decision_end:
        return None
    if prior_close <= 0 or bar.open <= 0 or bar.low <= 0 or bar.close <= 0:
        return None
    if len(prior_closes) < active.min_history_closes:
        return None
    if market_down_ratio < active.min_market_down_ratio:
        return None

    symbol_return = (bar.close - prior_close) / prior_close
    relative_return_edge = symbol_return - market_return
    adverse_from_open = (bar.open - bar.low) / bar.open
    recovery_from_low = (bar.close - bar.low) / bar.low
    rsi = _rsi([*prior_closes[-14:], bar.close])

    if symbol_return > active.max_symbol_return:
        return None
    if relative_return_edge < active.min_relative_return_edge:
        return None
    if adverse_from_open > active.max_adverse_from_open:
        return None
    if recovery_from_low < active.min_recovery_from_low:
        return None
    if bar.value < active.min_traded_value:
        return None
    if rsi >= active.max_rsi:
        return None

    score = relative_return_edge + recovery_from_low - adverse_from_open / Decimal("2")
    return PostCloseSwingRelativeStrengthCandidate(
        symbol=bar.symbol,
        timestamp=bar.timestamp.isoformat(),
        close=bar.close,
        symbol_return=symbol_return,
        market_return=market_return,
        relative_return_edge=relative_return_edge,
        market_down_ratio=market_down_ratio,
        adverse_from_open=adverse_from_open,
        recovery_from_low=recovery_from_low,
        traded_value=bar.value,
        rsi=rsi,
        score=score,
        recipe_id=active.candidate_id,
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
