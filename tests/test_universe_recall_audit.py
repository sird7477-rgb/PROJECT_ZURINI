from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from zurini.universe_recall_audit import SignalObservation, audit_universe_recall, compare_universe_recalls


KST = ZoneInfo("Asia/Seoul")


def _observation(symbol: str) -> SignalObservation:
    return SignalObservation(
        symbol=symbol,
        timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=KST),
        candidate_id="day-pullback-reentry-010",
        score=Decimal("1.5"),
    )


def test_audit_universe_recall_classifies_captured_and_missed_symbols() -> None:
    report = audit_universe_recall(
        universe_id="U80-current",
        universe_symbols={"A005930", "A000660"},
        observations=[_observation("A005930"), _observation("A035420")],
    )

    assert report.signal_count == 2
    assert report.captured_symbols == ("A005930",)
    assert report.missed_symbols == ("A035420",)
    assert report.recall_ratio() == Decimal("0.5")
    assert report.as_dict()["recall_ratio"] == "0.5"


def test_compare_universe_recalls_sorts_by_recall_then_size() -> None:
    wide = audit_universe_recall(
        universe_id="U100-wide",
        universe_symbols={"A005930", "A000660", "A035420"},
        observations=[_observation("A005930"), _observation("A035420")],
    )
    tight = audit_universe_recall(
        universe_id="U30-tight",
        universe_symbols={"A005930"},
        observations=[_observation("A005930"), _observation("A035420")],
    )

    assert [report.universe_id for report in compare_universe_recalls([tight, wide])] == [
        "U100-wide",
        "U30-tight",
    ]
