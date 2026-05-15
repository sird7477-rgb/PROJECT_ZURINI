from __future__ import annotations

from datetime import date
from decimal import Decimal

from zurini.field_monitor import _movement_leaders, _rank_watchlist_rows, _watchlist_symbol_summaries


def test_intraday_movement_leaders_rank_positive_change_before_negative_crash():
    rows = [
        {"symbol": "A111111", "timestamp": "2026-05-14T10:00:00+09:00", "close": "100", "passed": False, "reason": "seed"},
        {"symbol": "A111111", "timestamp": "2026-05-14T10:01:00+09:00", "close": "105", "passed": False, "reason": "up"},
        {"symbol": "A222222", "timestamp": "2026-05-14T10:00:00+09:00", "close": "100", "passed": False, "reason": "seed"},
        {"symbol": "A222222", "timestamp": "2026-05-14T10:01:00+09:00", "close": "90", "passed": False, "reason": "down"},
    ]

    summaries = _watchlist_symbol_summaries(rows, date(2026, 5, 14))

    assert [item["symbol"] for item in _movement_leaders(summaries)] == ["A111111", "A222222"]


def test_watchlist_candidate_proxy_ranks_intraday_gain_before_score_when_passed_ties():
    ranked = _rank_watchlist_rows(
        [
            {
                "symbol": "A111111",
                "passed": True,
                "score": Decimal("1"),
                "intraday_change_pct": Decimal("5"),
                "traded_value": Decimal("1000"),
            },
            {
                "symbol": "A222222",
                "passed": True,
                "score": Decimal("99"),
                "intraday_change_pct": Decimal("-10"),
                "traded_value": Decimal("1000"),
            },
        ]
    )

    assert [item["symbol"] for item in ranked] == ["A111111", "A222222"]
