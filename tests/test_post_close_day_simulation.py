from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from zurini.market import Bar
from zurini.post_close_day_simulation import (
    DayPullbackReentryConfig,
    KST,
    day_pullback_reentry_candidate,
    default_day_simulation_recipes,
)


def _bar(
    *,
    minute: int,
    symbol: str = "A058610",
    open_price: str = "100",
    high: str = "101",
    low: str = "100",
    close: str = "100",
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 5, 15, 10, minute, tzinfo=KST),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=1_000,
        value=Decimal("100000"),
        source="post-close-day-simulation",
    )


def test_default_day_simulation_recipes_keep_control_and_candidate_variants() -> None:
    recipes = default_day_simulation_recipes()
    recipe_ids = {recipe.candidate_id for recipe in recipes}

    assert "day-immediate-baseline" in recipe_ids
    assert "day-pullback-reentry-005" in recipe_ids
    assert "day-pullback-reentry-010" in recipe_ids
    assert "day-pullback-reentry-015" in recipe_ids
    assert "day-market-defense-filtered" in recipe_ids
    assert "day-spike-fade-guard" in recipe_ids
    assert all(recipe.promotion_boundary == "post-close-simulation-only" for recipe in recipes)


def test_day_pullback_reentry_waits_for_pullback_and_rebound() -> None:
    trigger = _bar(minute=1, close="100")
    candidate = day_pullback_reentry_candidate(
        trigger_bar=trigger,
        following_bars=[
            _bar(minute=2, low="99.50", close="99.60"),
            _bar(minute=3, low="98.80", close="98.90"),
            _bar(minute=4, low="98.80", close="99.20"),
        ],
    )

    assert candidate is not None
    assert candidate.symbol == "A058610"
    assert candidate.entry_timestamp == datetime(2026, 5, 15, 10, 4, tzinfo=KST).isoformat()
    assert candidate.pullback_from_trigger == Decimal("0.012")
    assert candidate.rebound_from_pullback_low == Decimal("0.4") / Decimal("98.8")


def test_day_pullback_reentry_rejects_without_rebound_confirmation() -> None:
    trigger = _bar(minute=1, close="100")
    candidate = day_pullback_reentry_candidate(
        trigger_bar=trigger,
        following_bars=[
            _bar(minute=2, low="98.80", close="98.90"),
            _bar(minute=3, low="98.70", close="98.80"),
        ],
    )

    assert candidate is None


def test_day_pullback_reentry_rejects_late_or_wrong_symbol_bars() -> None:
    trigger = _bar(minute=1, close="100")
    candidate = day_pullback_reentry_candidate(
        trigger_bar=trigger,
        following_bars=[
            _bar(minute=2, symbol="A178320", low="98.80", close="99.30"),
            Bar(
                symbol="A058610",
                timestamp=datetime(2026, 5, 15, 13, 31, tzinfo=KST),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("98.80"),
                close=Decimal("99.30"),
                volume=1_000,
                value=Decimal("100000"),
                source="post-close-day-simulation",
            ),
        ],
    )

    assert candidate is None


def test_day_pullback_reentry_serializes_config_and_candidate_for_reports() -> None:
    config = DayPullbackReentryConfig(required_pullback=Decimal("0.005"))
    candidate = day_pullback_reentry_candidate(
        trigger_bar=_bar(minute=1, close="100"),
        following_bars=[_bar(minute=2, low="99.40", close="99.80")],
        config=config,
    )

    assert config.as_dict()["required_pullback"] == "0.005"
    assert config.as_dict()["entry_end"] == "13:30"
    assert candidate is not None
    assert candidate.as_dict()["trigger_price"] == "100"
    assert candidate.as_dict()["entry_price"] == "99.80"
