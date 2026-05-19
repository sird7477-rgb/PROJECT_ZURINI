from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from zurini.market import Bar
from zurini.post_close_swing_relative_strength import (
    KST,
    PostCloseSwingRelativeStrengthConfig,
    post_close_swing_relative_strength_candidate,
)


def _bar(
    *,
    close: str = "101",
    low: str = "97",
    value: str = "60000000000",
    timestamp: datetime | None = None,
) -> Bar:
    return Bar(
        symbol="A322000",
        timestamp=timestamp or datetime(2026, 5, 12, 15, 20, tzinfo=KST),
        open=Decimal("100"),
        high=Decimal("103"),
        low=Decimal(low),
        close=Decimal(close),
        volume=1_000_000,
        value=Decimal(value),
        source="post-close-simulation",
    )


def _prior_closes() -> list[Decimal]:
    values = [90, 90, 90, 90, 90, 100, 101, 99, 100, 98, 99, 97, 98, 96, 97, 95, 96, 94, 95]
    return [Decimal(value) for value in values]


def test_relative_strength_candidate_accepts_resilient_name_in_weak_market() -> None:
    candidate = post_close_swing_relative_strength_candidate(
        bar=_bar(),
        prior_close=Decimal("100"),
        prior_closes=_prior_closes(),
        market_return=Decimal("-0.04"),
        market_down_ratio=Decimal("0.75"),
    )

    assert candidate is not None
    assert candidate.symbol == "A322000"
    assert candidate.reason == "post-close-swing-relative-strength"
    assert candidate.symbol_return == Decimal("0.01")
    assert candidate.relative_return_edge == Decimal("0.05")
    assert candidate.market_down_ratio == Decimal("0.75")
    assert candidate.rsi < Decimal("75")


def test_relative_strength_candidate_rejects_when_market_is_not_broadly_weak() -> None:
    candidate = post_close_swing_relative_strength_candidate(
        bar=_bar(),
        prior_close=Decimal("100"),
        prior_closes=_prior_closes(),
        market_return=Decimal("-0.01"),
        market_down_ratio=Decimal("0.40"),
    )

    assert candidate is None


def test_relative_strength_candidate_rejects_spike_or_deep_adverse_case() -> None:
    assert (
        post_close_swing_relative_strength_candidate(
            bar=_bar(close="108"),
            prior_close=Decimal("100"),
            prior_closes=_prior_closes(),
            market_return=Decimal("-0.04"),
            market_down_ratio=Decimal("0.75"),
        )
        is None
    )
    assert (
        post_close_swing_relative_strength_candidate(
            bar=_bar(low="92"),
            prior_close=Decimal("100"),
            prior_closes=_prior_closes(),
            market_return=Decimal("-0.04"),
            market_down_ratio=Decimal("0.75"),
        )
        is None
    )


def test_relative_strength_candidate_rejects_weak_liquidity_or_outside_window() -> None:
    assert (
        post_close_swing_relative_strength_candidate(
            bar=_bar(value="10000000000"),
            prior_close=Decimal("100"),
            prior_closes=_prior_closes(),
            market_return=Decimal("-0.04"),
            market_down_ratio=Decimal("0.75"),
        )
        is None
    )
    assert (
        post_close_swing_relative_strength_candidate(
            bar=_bar(timestamp=datetime(2026, 5, 12, 14, 59, tzinfo=KST)),
            prior_close=Decimal("100"),
            prior_closes=_prior_closes(),
            market_return=Decimal("-0.04"),
            market_down_ratio=Decimal("0.75"),
        )
        is None
    )


def test_relative_strength_candidate_serializes_for_reports() -> None:
    config = PostCloseSwingRelativeStrengthConfig()
    candidate = post_close_swing_relative_strength_candidate(
        bar=_bar(),
        prior_close=Decimal("100"),
        prior_closes=_prior_closes(),
        market_return=Decimal("-0.04"),
        market_down_ratio=Decimal("0.75"),
    )

    assert config.as_dict()["candidate_id"] == "post-close-swing-relative-strength"
    assert config.as_dict()["min_market_down_ratio"] == "0.60"
    assert candidate is not None
    assert candidate.as_dict()["symbol_return"] == "0.01"
    assert candidate.as_dict()["market_return"] == "-0.04"
