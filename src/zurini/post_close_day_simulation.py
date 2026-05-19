from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

from zurini.market import Bar


KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class DayPullbackReentryConfig:
    candidate_id: str = "day-pullback-reentry-010"
    entry_start: time = time(10, 0)
    entry_end: time = time(13, 30)
    required_pullback: Decimal = Decimal("0.010")
    min_rebound_from_pullback_low: Decimal = Decimal("0.003")
    max_entry_above_trigger: Decimal = Decimal("0.002")
    profit_target: Decimal = Decimal("0.030")
    hard_stop: Decimal = Decimal("-0.018")
    max_holding_minutes: int = 180
    day_end_exit: bool = True

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["entry_start"] = self.entry_start.isoformat(timespec="minutes")
        payload["entry_end"] = self.entry_end.isoformat(timespec="minutes")
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class DaySimulationRecipe:
    candidate_id: str
    purpose: str
    entry_window: str
    entry_rule: str
    risk_filter: str
    exit_rule: str
    promotion_boundary: str = "post-close-simulation-only"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DayPullbackReentryCandidate:
    symbol: str
    trigger_timestamp: str
    trigger_price: Decimal
    entry_timestamp: str
    entry_price: Decimal
    pullback_from_trigger: Decimal
    rebound_from_pullback_low: Decimal
    recipe_id: str
    reason: str = "day-pullback-reentry-simulation"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
        return payload


def default_day_simulation_recipes() -> list[DaySimulationRecipe]:
    return [
        DaySimulationRecipe(
            candidate_id="day-immediate-baseline",
            purpose="Replay the current intraday momentum trigger as the control case.",
            entry_window="10:00-13:30",
            entry_rule="enter at first accepted intraday-momentum-continuation trigger",
            risk_filter="current Plan A filters only",
            exit_rule="current day leg target/stop/max-hold/day-end policy",
        ),
        DaySimulationRecipe(
            candidate_id="day-pullback-reentry-005",
            purpose="Test whether a shallow pullback after the trigger reduces chase entries.",
            entry_window="10:00-13:30",
            entry_rule="after trigger, wait for -0.5% pullback and at least +0.2% rebound from pullback low",
            risk_filter="current Plan A filters plus optional index/breadth replay",
            exit_rule="same-day target/stop/max-hold/day-end simulation",
        ),
        DaySimulationRecipe(
            candidate_id="day-pullback-reentry-010",
            purpose="Test the main rollback idea discussed after the 2026-05-15 dry-run.",
            entry_window="10:00-13:30",
            entry_rule="after trigger, wait for -1.0% pullback and at least +0.3% rebound from pullback low",
            risk_filter="current Plan A filters plus optional index/breadth replay",
            exit_rule="same-day target/stop/max-hold/day-end simulation",
        ),
        DaySimulationRecipe(
            candidate_id="day-pullback-reentry-015",
            purpose="Stress-test deeper rollback entry against missed-winner risk.",
            entry_window="10:00-13:30",
            entry_rule="after trigger, wait for -1.5% pullback and at least +0.4% rebound from pullback low",
            risk_filter="current Plan A filters plus optional index/breadth replay",
            exit_rule="same-day target/stop/max-hold/day-end simulation",
        ),
        DaySimulationRecipe(
            candidate_id="day-market-defense-filtered",
            purpose="Replay triggers only when index trend and monitored-universe breadth are not bearish.",
            entry_window="10:00-13:30",
            entry_rule="current trigger timing",
            risk_filter="block when KOSPI/KOSDAQ trend or broad monitored breadth is bearish",
            exit_rule="same-day target/stop/max-hold/day-end simulation",
        ),
        DaySimulationRecipe(
            candidate_id="day-spike-fade-guard",
            purpose="Avoid trigger names that already show large spike-and-fade structure.",
            entry_window="10:00-13:30",
            entry_rule="current trigger timing, skipped if post-spike retracement exceeds guard threshold",
            risk_filter="current Plan A filters plus spike/fade exclusion",
            exit_rule="same-day target/stop/max-hold/day-end simulation",
        ),
        DaySimulationRecipe(
            candidate_id="day-window-0930-1330",
            purpose="Check whether earlier entry access improves or worsens the day leg.",
            entry_window="09:30-13:30",
            entry_rule="current trigger timing inside expanded morning window",
            risk_filter="current Plan A filters plus optional index/breadth replay",
            exit_rule="same-day target/stop/max-hold/day-end simulation",
        ),
        DaySimulationRecipe(
            candidate_id="day-window-1000-1400",
            purpose="Check whether late pre-afternoon continuation adds value or just adds fade risk.",
            entry_window="10:00-14:00",
            entry_rule="current trigger timing inside expanded end window",
            risk_filter="current Plan A filters plus optional index/breadth replay",
            exit_rule="same-day target/stop/max-hold/day-end simulation",
        ),
    ]


def day_pullback_reentry_candidate(
    *,
    trigger_bar: Bar,
    following_bars: list[Bar],
    config: DayPullbackReentryConfig | None = None,
) -> DayPullbackReentryCandidate | None:
    active = config or DayPullbackReentryConfig()
    trigger_price = trigger_bar.close
    if trigger_price <= 0:
        return None

    pullback_low: Decimal | None = None
    required_low = trigger_price * (Decimal("1") - active.required_pullback)
    max_entry_price = trigger_price * (Decimal("1") + active.max_entry_above_trigger)

    for bar in sorted(following_bars, key=lambda item: item.timestamp):
        if bar.symbol != trigger_bar.symbol:
            continue
        if bar.timestamp <= trigger_bar.timestamp:
            continue
        if not _within_window(bar, active.entry_start, active.entry_end):
            continue
        if bar.low <= 0 or bar.close <= 0:
            continue

        if bar.low <= required_low:
            pullback_low = bar.low if pullback_low is None else min(pullback_low, bar.low)
        if pullback_low is None:
            continue

        rebound_from_low = (bar.close - pullback_low) / pullback_low
        if rebound_from_low < active.min_rebound_from_pullback_low:
            continue
        if bar.close > max_entry_price:
            continue

        pullback_from_trigger = (trigger_price - pullback_low) / trigger_price
        return DayPullbackReentryCandidate(
            symbol=bar.symbol,
            trigger_timestamp=trigger_bar.timestamp.isoformat(),
            trigger_price=trigger_price,
            entry_timestamp=bar.timestamp.isoformat(),
            entry_price=bar.close,
            pullback_from_trigger=pullback_from_trigger,
            rebound_from_pullback_low=rebound_from_low,
            recipe_id=active.candidate_id,
        )
    return None


def _within_window(bar: Bar, start: time, end: time) -> bool:
    current = bar.timestamp.astimezone(KST).time()
    return start <= current <= end
