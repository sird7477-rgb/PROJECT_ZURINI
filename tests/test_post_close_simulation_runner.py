from __future__ import annotations

from decimal import Decimal

from zurini.post_close_simulation_runner import (
    PostCloseCandidateResult,
    build_model_level_replay_results,
    build_post_close_simulation_report,
    compare_index_filter_entries,
    default_post_close_simulation_plan,
    diagnose_swing_zero,
    summarize_candidate_results,
)


def test_default_post_close_plan_lists_current_candidate_counts() -> None:
    plan = default_post_close_simulation_plan()

    assert len(plan.day_recipes) == 8
    assert plan.swing_candidates == (
        "post-close-swing-rebound",
        "post-close-swing-relative-strength",
    )
    assert plan.filter_candidates == ("index-trend-filter",)
    assert plan.as_dict()["day_recipes"][0]["candidate_id"] == "day-immediate-baseline"


def test_compare_index_filter_entries_reports_blocked_gap() -> None:
    comparison = compare_index_filter_entries(
        filter_off_symbols={"A005930", "A000660", "A035420"},
        filter_on_symbols={"A005930"},
        filter_off_return=Decimal("-0.09"),
        filter_on_return=Decimal("0.01"),
    )

    assert comparison.blocked_count == 2
    assert comparison.blocked_symbols == ("A000660", "A035420")
    assert comparison.filter_on.rejected_count == 2
    assert comparison.as_dict()["filter_on"]["average_return"] == "0.01"


def test_compare_index_filter_entries_ignores_unexpected_filter_on_symbols() -> None:
    comparison = compare_index_filter_entries(
        filter_off_symbols={"A005930"},
        filter_on_symbols={"A005930", "A000660"},
    )

    assert comparison.filter_on.evaluated_count == 1
    assert comparison.filter_on.accepted_count == 1
    assert comparison.filter_on.rejected_count == 0
    assert comparison.unexpected_filter_on_symbols == ("A000660",)
    assert comparison.as_dict()["unexpected_filter_on_symbols"] == ["A000660"]


def test_summarize_candidate_results_orders_by_category_count_and_return() -> None:
    ordered = summarize_candidate_results(
        [
            PostCloseCandidateResult("day-b", "day", accepted_count=2, total_return=Decimal("0.02")),
            PostCloseCandidateResult("day-a", "day", accepted_count=3, total_return=Decimal("0.00")),
            PostCloseCandidateResult("swing-a", "swing", accepted_count=1, total_return=Decimal("0.05")),
        ]
    )

    assert [item.candidate_id for item in ordered] == ["day-a", "day-b", "swing-a"]


def test_diagnose_swing_zero_distinguishes_simulation_only_candidates() -> None:
    diagnostics = diagnose_swing_zero(
        control_count=0,
        rebound_count=1,
        relative_strength_count=0,
        rejection_reasons={"entry-window": 3},
    )

    assert diagnostics.status() == "simulation-only-swing-candidates-found"
    assert diagnostics.as_dict()["rejection_reasons"] == {"entry-window": 3}


def test_build_post_close_simulation_report_formats_plan_and_filter_comparison() -> None:
    report = build_post_close_simulation_report(
        filter_off_symbols={"A005930", "A000660"},
        filter_on_symbols={"A005930"},
        filter_off_return=Decimal("-0.02"),
        filter_on_return=Decimal("0.01"),
    )

    payload = report.as_dict()
    assert payload["plan"]["day_recipes"][0]["candidate_id"] == "day-immediate-baseline"
    assert payload["filter_comparison"]["blocked_count"] == 1
    assert payload["filter_comparison"]["blocked_symbols"] == ["A000660"]
    assert "post-close simulation/report only" in str(payload["promotion_boundary"])


def test_build_model_level_replay_results_reports_all_candidate_models() -> None:
    payload = {
        "source": "watchlist-replay-fixture",
        "first_observed_at": "2026-05-15T10:00:00+09:00",
        "last_observed_at": "2026-05-15T15:30:00+09:00",
        "rows": [
            {
                "symbol": "A005930",
                "timestamp": "2026-05-15T10:10:00+09:00",
                "passed": True,
                "strategy_group": "day",
                "close": "100",
                "high": "103",
                "reason": "intraday-momentum-continuation",
            },
            {
                "symbol": "A000660",
                "timestamp": "2026-05-15T15:15:00+09:00",
                "passed": True,
                "strategy_group": "swing",
                "close": "50",
                "high": "51",
                "reason": "swing-support",
            },
        ],
        "entry_trigger_outcomes": [
            {
                "symbol": "A005930",
                "entry_price": "100",
                "latest_close": "104",
                "max_adverse_pct": "-1.2",
                "max_favorable_pct": "4.0",
            },
            {
                "symbol": "A000660",
                "entry_price": "50",
                "latest_close": "52",
                "max_adverse_pct": "-2.0",
                "max_favorable_pct": "6.0",
            },
        ],
        "symbol_summaries": [
            {
                "symbol": "A000660",
                "intraday_change_pct": "2.0",
                "intraday_max_adverse_pct": "-1.0",
            }
        ],
    }

    results = build_model_level_replay_results(payload)
    by_id = {item.candidate_id: item for item in results}

    assert len(results) == 11
    assert by_id["day-immediate-baseline"].evaluated_count == 1
    assert by_id["day-pullback-reentry-010"].accepted_count == 1
    assert by_id["day-pullback-reentry-015"].rejected_count == 1
    assert by_id["day-market-defense-filtered"].accepted_count == 0
    assert by_id["day-market-defense-filtered"].rejected_count == 1
    assert by_id["day-market-defense-filtered"].reason == "blocked_missing_index_or_breadth_inputs"
    assert by_id["post-close-swing-rebound"].accepted_count == 1
    assert by_id["post-close-swing-relative-strength"].accepted_count == 1
    assert by_id["index-trend-filter"].category == "filter"
    assert by_id["index-trend-filter"].accepted_count == 0
    assert by_id["index-trend-filter"].reason == "blocked_missing_filter_inputs"


def test_build_model_level_replay_results_rejects_malformed_swing_summaries() -> None:
    payload = {
        "rows": [
            {
                "symbol": "A000660",
                "timestamp": "2026-05-15T15:15:00+09:00",
                "passed": True,
                "strategy_group": "swing",
                "close": "50",
                "high": "51",
                "reason": "swing-support",
            }
        ],
        "entry_trigger_outcomes": [{"symbol": "A000660"}],
        "symbol_summaries": {"A000660": {"intraday_change_pct": "0"}},
    }

    try:
        build_model_level_replay_results(payload)
    except ValueError as exc:
        assert "symbol_summaries" in str(exc)
    else:
        raise AssertionError("malformed swing replay summaries should fail closed")


def test_build_model_level_replay_results_requires_swing_summary_fields() -> None:
    payload = {
        "rows": [
            {
                "symbol": "A000660",
                "timestamp": "2026-05-15T15:15:00+09:00",
                "passed": True,
                "strategy_group": "swing",
                "close": "50",
                "high": "51",
                "reason": "swing-support",
            }
        ],
        "entry_trigger_outcomes": [{"symbol": "A000660"}],
        "symbol_summaries": [{"symbol": "A000660", "intraday_change_pct": "0"}],
    }

    try:
        build_model_level_replay_results(payload)
    except ValueError as exc:
        assert "intraday_max_adverse_pct" in str(exc)
    else:
        raise AssertionError("incomplete swing replay summaries should fail closed")
