from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time
from decimal import Decimal
from typing import Any

from zurini.post_close_day_simulation import DaySimulationRecipe, default_day_simulation_recipes


REPLAY_INPUT_MODE = "analysis-only-replay"


@dataclass(frozen=True)
class PostCloseCandidateResult:
    candidate_id: str
    category: str
    evaluated_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    total_return: Decimal = Decimal("0")
    reason: str = ""

    def average_return(self) -> Decimal:
        if self.accepted_count == 0:
            return Decimal("0")
        return self.total_return / Decimal(self.accepted_count)

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["total_return"] = str(self.total_return)
        payload["average_return"] = str(self.average_return())
        return payload


@dataclass(frozen=True)
class IndexFilterComparison:
    filter_off: PostCloseCandidateResult
    filter_on: PostCloseCandidateResult
    blocked_count: int
    blocked_symbols: tuple[str, ...]
    unexpected_filter_on_symbols: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "filter_off": self.filter_off.as_dict(),
            "filter_on": self.filter_on.as_dict(),
            "blocked_count": self.blocked_count,
            "blocked_symbols": list(self.blocked_symbols),
            "unexpected_filter_on_symbols": list(self.unexpected_filter_on_symbols),
        }


@dataclass(frozen=True)
class SwingZeroDiagnostics:
    control_count: int
    rebound_count: int
    relative_strength_count: int
    rejection_reasons: dict[str, int]

    def status(self) -> str:
        if self.control_count > 0:
            return "control-produced-swing-candidates"
        if self.rebound_count or self.relative_strength_count:
            return "simulation-only-swing-candidates-found"
        return "no-swing-candidates"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status(),
            "control_count": self.control_count,
            "rebound_count": self.rebound_count,
            "relative_strength_count": self.relative_strength_count,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
        }


@dataclass(frozen=True)
class ReplayInputEvidence:
    mode: str
    path: str
    source: str
    row_count: int
    trigger_outcome_count: int
    first_observed_at: str | None
    last_observed_at: str | None
    warning: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PostCloseSimulationPlan:
    day_recipes: tuple[DaySimulationRecipe, ...]
    swing_candidates: tuple[str, ...]
    filter_candidates: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "day_recipes": [recipe.as_dict() for recipe in self.day_recipes],
            "swing_candidates": list(self.swing_candidates),
            "filter_candidates": list(self.filter_candidates),
        }


@dataclass(frozen=True)
class PostCloseSimulationReport:
    plan: PostCloseSimulationPlan
    filter_comparison: IndexFilterComparison | None = None
    replay_input: ReplayInputEvidence | None = None
    model_results: tuple[PostCloseCandidateResult, ...] = ()
    promotion_boundary: str = (
        "post-close simulation/report only; not wired into live entry, broker, order, account, or balance paths"
    )

    def as_dict(self) -> dict[str, object]:
        return {
            "plan": self.plan.as_dict(),
            "filter_comparison": self.filter_comparison.as_dict() if self.filter_comparison else None,
            "replay_input": self.replay_input.as_dict() if self.replay_input else None,
            "model_results": [item.as_dict() for item in self.model_results],
            "promotion_boundary": self.promotion_boundary,
        }


def default_post_close_simulation_plan() -> PostCloseSimulationPlan:
    return PostCloseSimulationPlan(
        day_recipes=tuple(default_day_simulation_recipes()),
        swing_candidates=(
            "post-close-swing-rebound",
            "post-close-swing-relative-strength",
        ),
        filter_candidates=("index-trend-filter",),
    )


def build_post_close_simulation_report(
    *,
    filter_off_symbols: set[str] | None = None,
    filter_on_symbols: set[str] | None = None,
    filter_off_return: Decimal = Decimal("0"),
    filter_on_return: Decimal = Decimal("0"),
    replay_payload: dict[str, Any] | None = None,
    replay_path: str | None = None,
) -> PostCloseSimulationReport:
    plan = default_post_close_simulation_plan()
    comparison = None
    if filter_off_symbols is not None or filter_on_symbols is not None:
        comparison = compare_index_filter_entries(
            filter_off_symbols=filter_off_symbols or set(),
            filter_on_symbols=filter_on_symbols or set(),
            filter_off_return=filter_off_return,
            filter_on_return=filter_on_return,
        )
    replay_input = None
    model_results: tuple[PostCloseCandidateResult, ...] = ()
    if replay_payload is not None:
        replay_input = replay_input_evidence(replay_payload, path=replay_path or "")
        model_results = tuple(
            summarize_candidate_results(
                build_model_level_replay_results(
                    replay_payload,
                    plan=plan,
                    filter_comparison=comparison,
                )
            )
        )
    return PostCloseSimulationReport(
        plan=plan,
        filter_comparison=comparison,
        replay_input=replay_input,
        model_results=model_results,
    )


def compare_index_filter_entries(
    *,
    filter_off_symbols: set[str],
    filter_on_symbols: set[str],
    filter_off_return: Decimal = Decimal("0"),
    filter_on_return: Decimal = Decimal("0"),
) -> IndexFilterComparison:
    unexpected = tuple(sorted(filter_on_symbols - filter_off_symbols))
    accepted_symbols = filter_on_symbols & filter_off_symbols
    blocked = tuple(sorted(filter_off_symbols - accepted_symbols))
    filter_off_count = len(filter_off_symbols)
    filter_on_count = len(accepted_symbols)
    blocked_count = len(blocked)
    reason = "filter-on-replay"
    if unexpected:
        reason = "filter-on-replay-with-unexpected-symbols-ignored"
    return IndexFilterComparison(
        filter_off=PostCloseCandidateResult(
            candidate_id="index-trend-filter:off",
            category="filter",
            evaluated_count=filter_off_count,
            accepted_count=filter_off_count,
            total_return=filter_off_return,
            reason="filter-off-control",
        ),
        filter_on=PostCloseCandidateResult(
            candidate_id="index-trend-filter:on",
            category="filter",
            evaluated_count=filter_off_count,
            accepted_count=filter_on_count,
            rejected_count=blocked_count,
            total_return=filter_on_return,
            reason=reason,
        ),
        blocked_count=blocked_count,
        blocked_symbols=blocked,
        unexpected_filter_on_symbols=unexpected,
    )


def summarize_candidate_results(results: list[PostCloseCandidateResult]) -> list[PostCloseCandidateResult]:
    return sorted(
        results,
        key=lambda item: (
            item.category,
            -item.accepted_count,
            -item.average_return(),
            item.candidate_id,
        ),
    )


def replay_input_evidence(payload: dict[str, Any], *, path: str) -> ReplayInputEvidence:
    validate_replay_payload(payload)
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    outcomes = payload.get("entry_trigger_outcomes") if isinstance(payload.get("entry_trigger_outcomes"), list) else []
    return ReplayInputEvidence(
        mode=REPLAY_INPUT_MODE,
        path=path,
        source=str(payload.get("source") or "unknown"),
        row_count=len(rows),
        trigger_outcome_count=len(outcomes),
        first_observed_at=_optional_text(payload.get("first_observed_at")),
        last_observed_at=_optional_text(payload.get("last_observed_at")),
        warning=(
            "fallback replay input is analysis-only and is not KIS rolling DB evidence; "
            "do not use it for field-start readiness or data-integrity promotion"
        ),
    )


def build_model_level_replay_results(
    payload: dict[str, Any],
    *,
    plan: PostCloseSimulationPlan | None = None,
    filter_comparison: IndexFilterComparison | None = None,
) -> list[PostCloseCandidateResult]:
    validate_replay_payload(payload)
    active_plan = plan or default_post_close_simulation_plan()
    rows = [item for item in payload.get("rows", []) if isinstance(item, dict)]
    outcomes_by_symbol = {
        str(item.get("symbol")): item
        for item in payload.get("entry_trigger_outcomes", [])
        if isinstance(item, dict) and item.get("symbol")
    }
    summaries_by_symbol = {
        str(item.get("symbol")): item
        for item in payload.get("symbol_summaries", [])
        if isinstance(item, dict) and item.get("symbol")
    }
    day_triggers = _passed_rows(rows, group="day")
    swing_triggers = _passed_rows(rows, group="swing")

    results: list[PostCloseCandidateResult] = []
    for recipe in active_plan.day_recipes:
        results.append(_day_recipe_result(recipe.candidate_id, day_triggers, outcomes_by_symbol))
    for candidate_id in active_plan.swing_candidates:
        results.append(_swing_candidate_result(candidate_id, swing_triggers, summaries_by_symbol, outcomes_by_symbol))
    for candidate_id in active_plan.filter_candidates:
        results.append(_filter_candidate_result(candidate_id, day_triggers, filter_comparison))
    return results


def diagnose_swing_zero(
    *,
    control_count: int,
    rebound_count: int,
    relative_strength_count: int,
    rejection_reasons: dict[str, int] | None = None,
) -> SwingZeroDiagnostics:
    return SwingZeroDiagnostics(
        control_count=control_count,
        rebound_count=rebound_count,
        relative_strength_count=relative_strength_count,
        rejection_reasons=rejection_reasons or {},
    )


def _day_recipe_result(
    candidate_id: str,
    triggers: list[dict[str, Any]],
    outcomes_by_symbol: dict[str, dict[str, Any]],
) -> PostCloseCandidateResult:
    evaluated = len(triggers)
    accepted_rows: list[dict[str, Any]] = []
    for row in triggers:
        outcome = outcomes_by_symbol.get(str(row.get("symbol")), {})
        if _day_recipe_accepts(candidate_id, row, outcome):
            accepted_rows.append(row)
    return PostCloseCandidateResult(
        candidate_id=candidate_id,
        category="day",
        evaluated_count=evaluated,
        accepted_count=len(accepted_rows),
        rejected_count=evaluated - len(accepted_rows),
        total_return=sum((_entry_return(row, outcomes_by_symbol) for row in accepted_rows), Decimal("0")),
        reason=_day_recipe_reason(candidate_id),
    )


def _swing_candidate_result(
    candidate_id: str,
    triggers: list[dict[str, Any]],
    summaries_by_symbol: dict[str, dict[str, Any]],
    outcomes_by_symbol: dict[str, dict[str, Any]],
) -> PostCloseCandidateResult:
    evaluated = len(triggers)
    accepted_rows: list[dict[str, Any]] = []
    for row in triggers:
        summary = summaries_by_symbol.get(str(row.get("symbol")), {})
        if _swing_recipe_accepts(candidate_id, row, summary):
            accepted_rows.append(row)
    return PostCloseCandidateResult(
        candidate_id=candidate_id,
        category="swing",
        evaluated_count=evaluated,
        accepted_count=len(accepted_rows),
        rejected_count=evaluated - len(accepted_rows),
        total_return=sum((_entry_return(row, outcomes_by_symbol) for row in accepted_rows), Decimal("0")),
        reason="derived from replay trigger rows and symbol movement summaries",
    )


def _filter_candidate_result(
    candidate_id: str,
    triggers: list[dict[str, Any]],
    comparison: IndexFilterComparison | None,
) -> PostCloseCandidateResult:
    if comparison is not None:
        return PostCloseCandidateResult(
            candidate_id=candidate_id,
            category="filter",
            evaluated_count=comparison.filter_on.evaluated_count,
            accepted_count=comparison.filter_on.accepted_count,
            rejected_count=comparison.filter_on.rejected_count,
            total_return=comparison.filter_on.total_return,
            reason="filter-on replay symbol list comparison",
        )
    return PostCloseCandidateResult(
        candidate_id=candidate_id,
        category="filter",
        evaluated_count=len(triggers),
        accepted_count=0,
        rejected_count=len(triggers),
        total_return=Decimal("0"),
        reason="blocked_missing_filter_inputs",
    )


def _day_recipe_accepts(candidate_id: str, row: dict[str, Any], outcome: dict[str, Any]) -> bool:
    timestamp = _time_from_iso(row.get("timestamp"))
    adverse = _decimal(outcome.get("max_adverse_pct", "0")) / Decimal("100")
    favorable = _decimal(outcome.get("max_favorable_pct", "0")) / Decimal("100")
    fade = _pct_from_row(row, "high", "close")
    if candidate_id == "day-immediate-baseline":
        return True
    if candidate_id == "day-pullback-reentry-005":
        return adverse <= Decimal("-0.005") and favorable >= Decimal("0.002")
    if candidate_id == "day-pullback-reentry-010":
        return adverse <= Decimal("-0.010") and favorable >= Decimal("0.003")
    if candidate_id == "day-pullback-reentry-015":
        return adverse <= Decimal("-0.015") and favorable >= Decimal("0.004")
    if candidate_id == "day-market-defense-filtered":
        return False
    if candidate_id == "day-spike-fade-guard":
        return fade <= Decimal("0.030")
    if candidate_id == "day-window-0930-1330":
        return timestamp is not None and time(9, 30) <= timestamp <= time(13, 30)
    if candidate_id == "day-window-1000-1400":
        return timestamp is not None and time(10, 0) <= timestamp <= time(14, 0)
    return False


def _swing_recipe_accepts(candidate_id: str, row: dict[str, Any], summary: dict[str, Any]) -> bool:
    reason = str(row.get("reason") or "")
    if candidate_id == "post-close-swing-rebound":
        return reason == "swing-support" and _decimal(summary.get("intraday_change_pct", "0")) > Decimal("0")
    if candidate_id == "post-close-swing-relative-strength":
        return (
            reason == "swing-support"
            and _decimal(summary.get("intraday_change_pct", "0")) >= Decimal("0")
            and _decimal(summary.get("intraday_max_adverse_pct", "0")) >= Decimal("-5")
        )
    return False


def _day_recipe_reason(candidate_id: str) -> str:
    if candidate_id.startswith("day-pullback-reentry"):
        return "approximated from replay entry outcome max adverse/favorable movement"
    if candidate_id == "day-spike-fade-guard":
        return "approximated from trigger bar high-to-close fade"
    if candidate_id.startswith("day-window"):
        return "evaluated against replay trigger timestamp window"
    if candidate_id == "day-market-defense-filtered":
        return "blocked_missing_index_or_breadth_inputs"
    return "current replay trigger baseline"


def validate_replay_payload(payload: dict[str, Any]) -> None:
    rows = payload.get("rows")
    outcomes = payload.get("entry_trigger_outcomes")
    summaries = payload.get("symbol_summaries")
    if not isinstance(rows, list):
        raise ValueError("replay watchlist JSON must include rows[]")
    if not isinstance(outcomes, list):
        raise ValueError("replay watchlist JSON must include entry_trigger_outcomes[]")
    if summaries is not None and not isinstance(summaries, list):
        raise ValueError("replay watchlist JSON symbol_summaries must be an array when present")
    required_row_fields = {"symbol", "timestamp", "passed", "strategy_group"}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"replay rows[{index}] must be an object")
        missing = sorted(required_row_fields - set(row))
        if missing:
            raise ValueError(f"replay rows[{index}] missing fields: {','.join(missing)}")
    for index, outcome in enumerate(outcomes, start=1):
        if not isinstance(outcome, dict):
            raise ValueError(f"replay entry_trigger_outcomes[{index}] must be an object")
        if not outcome.get("symbol"):
            raise ValueError(f"replay entry_trigger_outcomes[{index}] missing symbol")
    swing_symbols = {
        str(row.get("symbol"))
        for row in rows
        if (
            isinstance(row, dict)
            and row.get("passed") is True
            and str(row.get("strategy_group") or "") == "swing"
            and row.get("symbol")
        )
    }
    if swing_symbols:
        if not isinstance(summaries, list):
            raise ValueError("replay watchlist JSON must include symbol_summaries[] for swing replay rows")
        required_summary_fields = {"symbol", "intraday_change_pct", "intraday_max_adverse_pct"}
        summary_symbols: set[str] = set()
        for index, summary in enumerate(summaries, start=1):
            if not isinstance(summary, dict):
                raise ValueError(f"replay symbol_summaries[{index}] must be an object")
            missing = sorted(required_summary_fields - set(summary))
            if missing:
                raise ValueError(f"replay symbol_summaries[{index}] missing fields: {','.join(missing)}")
            summary_symbols.add(str(summary.get("symbol")))
        missing_symbols = sorted(swing_symbols - summary_symbols)
        if missing_symbols:
            raise ValueError(f"replay symbol_summaries[] missing swing symbols: {','.join(missing_symbols)}")


def _passed_rows(rows: list[dict[str, Any]], *, group: str) -> list[dict[str, Any]]:
    return [
        item
        for item in rows
        if item.get("passed") is True and str(item.get("strategy_group") or "") == group
    ]


def _entry_return(row: dict[str, Any], outcomes_by_symbol: dict[str, dict[str, Any]]) -> Decimal:
    outcome = outcomes_by_symbol.get(str(row.get("symbol")), {})
    entry = _decimal(outcome.get("entry_price") or row.get("close") or "0")
    latest = _decimal(outcome.get("latest_close") or row.get("close") or "0")
    if entry <= 0:
        return Decimal("0")
    return (latest - entry) / entry


def _pct_from_row(row: dict[str, Any], high_key: str, low_key: str) -> Decimal:
    high = _decimal(row.get(high_key) or "0")
    low = _decimal(row.get(low_key) or "0")
    if high <= 0:
        return Decimal("0")
    return (high - low) / high


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _time_from_iso(value: Any) -> time | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return time.fromisoformat(value.split("T", maxsplit=1)[1].split("+", maxsplit=1)[0])
    except (IndexError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
