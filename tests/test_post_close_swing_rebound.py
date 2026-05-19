from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from zurini.market import Bar
from zurini.post_close_swing_rebound import (
    KST,
    PostCloseSwingReboundConfig,
    post_close_swing_rebound_candidate,
)


def _bar(
    *,
    timestamp: datetime | None = None,
    open_price: str = "100",
    high: str = "105",
    low: str = "94",
    close: str = "103",
    volume: int = 2_000,
) -> Bar:
    return Bar(
        symbol="A067310",
        timestamp=timestamp or datetime(2026, 5, 15, 15, 15, tzinfo=KST),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=volume,
        value=Decimal("0"),
        source="post-close-simulation",
    )


def _prior_closes() -> list[Decimal]:
    values = [90, 90, 90, 90, 90, 100, 101, 99, 100, 98, 99, 97, 98, 96, 97, 95, 96, 94, 95]
    return [Decimal(value) for value in values]


def test_post_close_swing_rebound_accepts_late_day_reclaim_candidate() -> None:
    candidate = post_close_swing_rebound_candidate(
        bar=_bar(),
        prior_closes=_prior_closes(),
        prior_volumes=[1_000, 1_000, 1_000, 1_000, 1_000],
    )

    assert candidate is not None
    assert candidate.symbol == "A067310"
    assert candidate.reason == "post-close-swing-rebound"
    assert candidate.low_drop == Decimal("0.06")
    assert candidate.reclaim_from_low == Decimal("9") / Decimal("94")
    assert candidate.range_position == Decimal("9") / Decimal("11")
    assert candidate.volume_ratio == Decimal("2")
    assert candidate.rsi < Decimal("85")


def test_post_close_swing_rebound_rejects_outside_decision_window() -> None:
    candidate = post_close_swing_rebound_candidate(
        bar=_bar(timestamp=datetime(2026, 5, 15, 14, 59, tzinfo=KST)),
        prior_closes=_prior_closes(),
        prior_volumes=[1_000, 1_000, 1_000, 1_000, 1_000],
    )

    assert candidate is None


def test_post_close_swing_rebound_rejects_without_required_reversal_shape() -> None:
    candidate = post_close_swing_rebound_candidate(
        bar=_bar(low="99", close="100"),
        prior_closes=_prior_closes(),
        prior_volumes=[1_000, 1_000, 1_000, 1_000, 1_000],
    )

    assert candidate is None


def test_post_close_swing_rebound_rejects_without_history_or_volume_confirmation() -> None:
    assert (
        post_close_swing_rebound_candidate(
            bar=_bar(),
            prior_closes=_prior_closes()[:10],
            prior_volumes=[1_000, 1_000, 1_000, 1_000, 1_000],
        )
        is None
    )
    assert (
        post_close_swing_rebound_candidate(
            bar=_bar(volume=700),
            prior_closes=_prior_closes(),
            prior_volumes=[1_000, 1_000, 1_000, 1_000, 1_000],
        )
        is None
    )


def test_post_close_swing_rebound_serializes_config_and_candidate_for_reports() -> None:
    config_payload = PostCloseSwingReboundConfig().as_dict()
    candidate = post_close_swing_rebound_candidate(
        bar=_bar(),
        prior_closes=_prior_closes(),
        prior_volumes=[1_000, 1_000, 1_000, 1_000, 1_000],
    )

    assert config_payload["decision_start"] == "15:10"
    assert config_payload["min_intraday_low_drop"] == "0.02"
    assert candidate is not None
    assert candidate.as_dict()["close"] == "103"
    assert candidate.as_dict()["volume_ratio"] == "2"
