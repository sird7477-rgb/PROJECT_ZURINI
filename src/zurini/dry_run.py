from __future__ import annotations

import json
import inspect
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from zurini.api_budget import FieldApiBudgetPolicy, normalize_to_kst
from zurini.blacklist import AsyncBlacklistSnapshot
from zurini.market import Bar, SignalIntent
from zurini.strategies.baseline import IntradayMomentumSwingSupportPortfolioStrategy, RiskState


PLAN_A_PACKAGE_ID = "plan-a-idmom-d3-fsup-u1s1"
PLAN_B_PACKAGE_ID = "plan-b-idmom-d3-fsup-u1s1"
DRY_RUN_FEE_RATE = Decimal("0.00030")
DRY_RUN_SLIPPAGE_RATE = Decimal("0.00100")


@dataclass(frozen=True)
class StrategyPackage:
    package_id: str
    day_strategy: str
    swing_strategy: str
    day_max_slots: int
    swing_max_slots: int
    total_max_slots: int
    slot_capital_cap: Decimal
    operating_ceiling: Decimal
    weekly_contribution: Decimal
    fallback_package_id: str = ""


@dataclass(frozen=True)
class CapitalComparisonCase:
    case_id: str
    day_weight: Decimal | None
    swing_weight: Decimal | None
    required: bool
    purpose: str
    production_interpretation: str


@dataclass(frozen=True)
class DryRunSession:
    session_id: str
    trading_date: date
    package_id: str
    mode: str = "no-order"
    order_hard_block: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class UniverseSnapshot:
    universe_id: str
    included_symbols: tuple[str, ...]
    excluded_symbols: tuple[str, ...] = ()
    exclusion_reasons: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ScouterCandidate:
    timestamp: datetime
    symbol: str
    strategy_group: str
    score: Decimal
    passed: bool
    reason: str
    rank: int | None = None


@dataclass(frozen=True)
class ScouterDecisionSnapshot:
    timestamp: datetime
    symbol: str
    strategy_group: str
    action: str
    score: Decimal
    rank: int | None
    passed: bool
    reason: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    traded_value: Decimal
    bid_ask_ratio: Decimal
    source: str
    input_flags: tuple[str, ...] = ()
    storage_tier: str = "decision-snapshot"
    raw_response_persisted: bool = False


@dataclass(frozen=True)
class InterlockEvent:
    timestamp: datetime
    symbol: str
    event_type: str
    source_strategy: str
    blocked_strategy: str
    reason: str
    cooldown_expiry: date | None = None


@dataclass(frozen=True)
class VirtualOrder:
    timestamp: datetime
    symbol: str
    strategy_group: str
    side: str
    quantity: Decimal
    intended_price: Decimal
    reason_code: str
    hard_blocked: bool = True
    affordability_status: str = "not_cash_reconciled"
    affordability_note: str = "observation-only virtual order; not an executable intended position"
    strategy_id: str = ""
    entry_rule: str = ""
    exit_policy: str = ""
    cost_model: str = ""
    applied_profit_target: Decimal | None = None
    applied_hard_stop: Decimal | None = None
    applied_max_holding_minutes: int | None = None
    applied_day_end_exit: bool | None = None


@dataclass(frozen=True)
class VirtualFill:
    timestamp: datetime
    symbol: str
    expected_price: Decimal
    simulated_price: Decimal
    slippage_assumption: Decimal
    partial_fill: bool = False


@dataclass(frozen=True)
class VirtualPosition:
    position_id: str
    symbol: str
    strategy_group: str
    quantity: Decimal
    entry_price: Decimal
    slot_id: str
    sleeve_id: str
    exit_policy: str
    profit_target: Decimal | None = None
    hard_stop: Decimal | None = None
    max_holding_minutes: int | None = None
    day_end_exit: bool = False
    entry_time: datetime | None = None
    affordability_status: str = "not_cash_reconciled"
    affordability_note: str = "observation-only virtual position; cash feasibility is reported separately"
    strategy_id: str = ""
    entry_rule: str = ""
    cost_model: str = ""


@dataclass(frozen=True)
class VirtualPositionClose:
    position_id: str
    symbol: str
    strategy_group: str
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    exit_time: datetime
    realized_pnl: Decimal
    reason: str
    fee_rate: Decimal = DRY_RUN_FEE_RATE
    slippage_rate: Decimal = DRY_RUN_SLIPPAGE_RATE
    total_fees: Decimal = Decimal("0")
    strategy_id: str = ""
    entry_rule: str = ""
    exit_policy: str = ""
    slot_id: str = ""
    sleeve_id: str = ""
    cost_model: str = ""
    applied_profit_target: Decimal | None = None
    applied_hard_stop: Decimal | None = None
    applied_max_holding_minutes: int | None = None
    applied_day_end_exit: bool | None = None


@dataclass(frozen=True)
class RiskEvent:
    timestamp: datetime
    event_type: str
    severity: str
    message: str
    buy_blocked: bool = False


@dataclass(frozen=True)
class CapitalFeasibility:
    starting_seed: Decimal
    case_id: str
    day_slot_budget: Decimal
    swing_slot_budget: Decimal
    whole_share_reject_count: int
    insufficient_cash_count: int
    simultaneous_day_swing_feasible: bool
    note: str = ""


@dataclass(frozen=True)
class DailyReconciliation:
    trading_day: date
    virtual_order_count: int
    virtual_fill_count: int
    virtual_position_count: int
    day_position_count: int
    swing_position_count: int
    interlock_event_count: int
    risk_event_count: int
    unreconciled: bool = False
    note: str = ""


@dataclass(frozen=True)
class PlanBFallbackState:
    active: bool
    reason: str
    fallback_package_id: str
    activated_at: datetime | None = None


@dataclass(frozen=True)
class OpeningSurvivalCheck:
    trading_day: date
    checked_positions: int
    survived_positions: int
    failed_positions: int
    note: str = ""


@dataclass(frozen=True)
class DryRunCashReconciliation:
    trading_day: date
    starting_cash: Decimal
    external_contribution: Decimal
    virtual_buy_notional: Decimal
    virtual_sell_notional: Decimal
    day_exposure: Decimal
    swing_exposure: Decimal
    reserved_cash: Decimal
    idle_cash: Decimal
    ending_cash: Decimal
    blocked_deployment: bool
    cash_after_virtual_trades: Decimal = Decimal("0")
    available_cash_after_reserved_exposure: Decimal = Decimal("0")
    note: str = ""


@dataclass(frozen=True)
class DryRunPnlSnapshot:
    trading_day: date
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    gross_exposure: Decimal
    day_exposure: Decimal
    swing_exposure: Decimal
    open_position_count: int
    closed_position_count: int
    note: str = ""


@dataclass(frozen=True)
class DryRunPortfolioState:
    trading_day: date
    cash: Decimal
    reserved_cash: Decimal
    day_slots_used: int
    swing_slots_used: int
    total_slots_used: int
    day_exposure: Decimal
    swing_exposure: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    source: str = "local-dry-run"


@dataclass(frozen=True)
class DryRunStorageGuardrailCheck:
    trading_day: date
    free_space_gb: Decimal
    db_log_soft_cap_gb: Decimal
    raw_burst_enabled: bool
    raw_burst_hard_cap_mb: int
    raw_burst_ttl_days: int
    action: str
    within_guardrail: bool
    note: str = ""


@dataclass(frozen=True)
class DryRunCheckpointEvent:
    trigger_id: str
    trading_day: date
    category: str
    severity: str
    message: str
    required_action: str
    deployment_blocked: bool = False


@dataclass(frozen=True)
class DryRunApiRateLimitCheck:
    trading_day: date
    provider: str
    limit_per_second: int
    operating_limit_per_second: int
    estimated_calls: int
    estimated_peak_per_second: int
    within_limit: bool
    data_source: str
    note: str = ""


@dataclass(frozen=True)
class DryRunReport:
    session: DryRunSession
    strategy_package: StrategyPackage
    capital_cases: tuple[CapitalComparisonCase, ...]
    observed_trading_days: tuple[date, ...] = ()
    universe_snapshots: tuple[UniverseSnapshot, ...] = ()
    scouter_decision_snapshots: tuple[ScouterDecisionSnapshot, ...] = ()
    scouter_candidates: tuple[ScouterCandidate, ...] = ()
    interlock_events: tuple[InterlockEvent, ...] = ()
    virtual_orders: tuple[VirtualOrder, ...] = ()
    virtual_fills: tuple[VirtualFill, ...] = ()
    virtual_positions: tuple[VirtualPosition, ...] = ()
    virtual_position_closes: tuple[VirtualPositionClose, ...] = ()
    risk_events: tuple[RiskEvent, ...] = ()
    capital_feasibility: tuple[CapitalFeasibility, ...] = ()
    daily_reconciliation: tuple[DailyReconciliation, ...] = ()
    open_positions: tuple[VirtualPosition, ...] = ()
    plan_b_fallback: PlanBFallbackState | None = None
    opening_survival_checks: tuple[OpeningSurvivalCheck, ...] = ()
    cash_reconciliation: tuple[DryRunCashReconciliation, ...] = ()
    pnl_snapshots: tuple[DryRunPnlSnapshot, ...] = ()
    portfolio_states: tuple[DryRunPortfolioState, ...] = ()
    storage_guardrail_checks: tuple[DryRunStorageGuardrailCheck, ...] = ()
    checkpoint_events: tuple[DryRunCheckpointEvent, ...] = ()
    api_rate_limit_checks: tuple[DryRunApiRateLimitCheck, ...] = ()

    def summary(self) -> dict[str, Any]:
        required_cases = [case.case_id for case in self.capital_cases if case.required]
        optional_cases = [case.case_id for case in self.capital_cases if not case.required]
        blocked_orders = sum(1 for order in self.virtual_orders if order.hard_blocked)
        unblocked_orders = len(self.virtual_orders) - blocked_orders
        return {
            "mode": self.session.mode,
            "order_hard_block": self.session.order_hard_block,
            "trading_day_count": len(self.observed_trading_days),
            "required_capital_cases": required_cases,
            "optional_capital_cases": optional_cases,
            "universe_snapshot_count": len(self.universe_snapshots),
            "scouter_decision_snapshot_count": len(self.scouter_decision_snapshots),
            "scouter_candidate_count": len(self.scouter_candidates),
            "interlock_event_count": len(self.interlock_events),
            "virtual_order_count": len(self.virtual_orders),
            "virtual_order_hard_blocked_count": blocked_orders,
            "virtual_order_unblocked_count": unblocked_orders,
            "virtual_position_count": len(self.virtual_positions),
            "virtual_position_close_count": len(self.virtual_position_closes),
            "risk_event_count": len(self.risk_events),
            "capital_feasibility_count": len(self.capital_feasibility),
            "daily_reconciliation_count": len(self.daily_reconciliation),
            "open_position_count": len(self.open_positions),
            "plan_b_fallback_active": self.plan_b_fallback.active if self.plan_b_fallback else False,
            "opening_survival_check_count": len(self.opening_survival_checks),
            "cash_reconciliation_count": len(self.cash_reconciliation),
            "pnl_snapshot_count": len(self.pnl_snapshots),
            "portfolio_state_count": len(self.portfolio_states),
            "storage_guardrail_check_count": len(self.storage_guardrail_checks),
            "checkpoint_event_count": len(self.checkpoint_events),
            "api_rate_limit_check_count": len(self.api_rate_limit_checks),
            "ready_for_broker_or_order_transmission": False,
        }


@dataclass(frozen=True)
class PlanASensitivityCase:
    case_id: str
    strategy_group: str
    parameter: str
    baseline_value: str
    tested_values: tuple[str, ...]
    decision: str
    rationale: str


@dataclass(frozen=True)
class PlanASensitivityDecision:
    decision_id: str
    baseline_package_id: str
    status: str
    default_action: str
    candidate_b_action: str
    cases: tuple[PlanASensitivityCase, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class DryRunMultiSessionReport:
    run_id: str
    strategy_package: StrategyPackage
    starting_seed: Decimal
    weekly_contribution: Decimal
    sessions: tuple[DryRunReport, ...]
    cash_reconciliation: tuple[DryRunCashReconciliation, ...]
    pnl_snapshots: tuple[DryRunPnlSnapshot, ...]
    portfolio_states: tuple[DryRunPortfolioState, ...]
    storage_guardrail_checks: tuple[DryRunStorageGuardrailCheck, ...]
    checkpoint_events: tuple[DryRunCheckpointEvent, ...]
    api_rate_limit_checks: tuple[DryRunApiRateLimitCheck, ...]

    def summary(self) -> dict[str, Any]:
        blocked_orders = sum(
            report.summary()["virtual_order_hard_blocked_count"] for report in self.sessions
        )
        unblocked_orders = sum(
            report.summary()["virtual_order_unblocked_count"] for report in self.sessions
        )
        return {
            "run_id": self.run_id,
            "mode": "no-order",
            "order_hard_block": all(report.session.order_hard_block for report in self.sessions),
            "session_count": len(self.sessions),
            "trading_day_count": len({day for report in self.sessions for day in report.observed_trading_days}),
            "scouter_decision_snapshot_count": sum(
                report.summary()["scouter_decision_snapshot_count"] for report in self.sessions
            ),
            "virtual_order_hard_blocked_count": blocked_orders,
            "virtual_order_unblocked_count": unblocked_orders,
            "cash_reconciliation_count": len(self.cash_reconciliation),
            "pnl_snapshot_count": len(self.pnl_snapshots),
            "portfolio_state_count": len(self.portfolio_states),
            "storage_guardrail_check_count": len(self.storage_guardrail_checks),
            "storage_guardrail_breach_count": sum(
                1 for item in self.storage_guardrail_checks if not item.within_guardrail
            ),
            "checkpoint_event_count": len(self.checkpoint_events),
            "api_rate_limit_check_count": len(self.api_rate_limit_checks),
            "api_rate_limit_breach_count": sum(1 for item in self.api_rate_limit_checks if not item.within_limit),
            "ready_for_broker_or_order_transmission": False,
        }


def build_plan_a_strategy_package() -> StrategyPackage:
    return StrategyPackage(
        package_id=PLAN_A_PACKAGE_ID,
        day_strategy="C-IDMOM-D3-U1-S1",
        swing_strategy="F-SUP-U1-S1",
        day_max_slots=2,
        swing_max_slots=5,
        total_max_slots=7,
        slot_capital_cap=Decimal("10000000"),
        operating_ceiling=Decimal("70000000"),
        weekly_contribution=Decimal("100000"),
        fallback_package_id=PLAN_B_PACKAGE_ID,
    )


def _strategy_id_for_group(group: str, package: StrategyPackage | None = None) -> str:
    selected = package or build_plan_a_strategy_package()
    if group == "day":
        return selected.day_strategy
    if group == "swing":
        return selected.swing_strategy
    return ""


def _dry_run_cost_model() -> str:
    return f"fee_rate={DRY_RUN_FEE_RATE};slippage_rate={DRY_RUN_SLIPPAGE_RATE}"


def build_plan_a_capital_cases() -> tuple[CapitalComparisonCase, ...]:
    return (
        CapitalComparisonCase(
            case_id="shared-slot-plan-a",
            day_weight=None,
            swing_weight=None,
            required=True,
            purpose="Preserve validated Plan A shared-slot contract with day=2 and swing=5 caps.",
            production_interpretation="Baseline because this is the validated backtest contract.",
        ),
        CapitalComparisonCase(
            case_id="sleeve-40-60",
            day_weight=Decimal("0.40"),
            swing_weight=Decimal("0.60"),
            required=True,
            purpose="Test archived day/swing capital allocation intent.",
            production_interpretation="Candidate field operating model only if it avoids cash starvation.",
        ),
        CapitalComparisonCase(
            case_id="sleeve-30-70",
            day_weight=Decimal("0.30"),
            swing_weight=Decimal("0.70"),
            required=False,
            purpose="Sensitivity check for swing-heavy small-seed fragility.",
            production_interpretation="Sensitivity only; not optimizer-selected production value.",
        ),
        CapitalComparisonCase(
            case_id="sleeve-50-50",
            day_weight=Decimal("0.50"),
            swing_weight=Decimal("0.50"),
            required=False,
            purpose="Sensitivity check for simple equal split feasibility.",
            production_interpretation="Sensitivity only; not optimizer-selected production value.",
        ),
    )


def build_empty_plan_a_dry_run_report(
    *,
    trading_date: date,
    session_id: str | None = None,
) -> DryRunReport:
    if session_id is None:
        session_id = f"plan-a-dry-run-{trading_date.isoformat()}"
    return DryRunReport(
        session=DryRunSession(
            session_id=session_id,
            trading_date=trading_date,
            package_id=PLAN_A_PACKAGE_ID,
        ),
        strategy_package=build_plan_a_strategy_package(),
        capital_cases=build_plan_a_capital_cases(),
        plan_b_fallback=_inactive_plan_b_fallback(build_plan_a_strategy_package()),
    )


def build_plan_a_limited_sensitivity_decision() -> PlanASensitivityDecision:
    package = build_plan_a_strategy_package()
    return PlanASensitivityDecision(
        decision_id="plan-a-limited-sensitivity-v1",
        baseline_package_id=package.package_id,
        status="baseline-kept",
        default_action="Keep Plan A defaults as the primary dry-run baseline.",
        candidate_b_action="Promote no candidate B without fresh robustness evidence; carry future winners automatically as observation-only.",
        cases=(
            PlanASensitivityCase(
                case_id="day-profit-target",
                strategy_group="day",
                parameter="profit_target",
                baseline_value="0.08",
                tested_values=("0.06", "0.08", "0.10"),
                decision="keep-default",
                rationale="Existing survivor uses the wider target and passes 2x cost; no existing narrower perturbation improves robustness.",
            ),
            PlanASensitivityCase(
                case_id="day-hard-stop",
                strategy_group="day",
                parameter="hard_stop",
                baseline_value="-0.018",
                tested_values=("-0.015", "-0.018", "-0.02"),
                decision="keep-default",
                rationale="Keep the validated stop until a bounded rerun proves lower drawdown without trade collapse or field-alignment loss.",
            ),
            PlanASensitivityCase(
                case_id="day-holding-minutes",
                strategy_group="day",
                parameter="max_holding_minutes",
                baseline_value="180",
                tested_values=("120", "180", "240"),
                decision="keep-default",
                rationale="Existing D3 hold-180 survivor is the only day variant with acceptable base and 2x cost evidence.",
            ),
            PlanASensitivityCase(
                case_id="swing-support-band",
                strategy_group="swing",
                parameter="support_band",
                baseline_value="0.018",
                tested_values=("0.015", "0.018", "0.02"),
                decision="keep-default",
                rationale="Existing F-SUP-U1-S1 passes base and 2x cost; do not alter without dry-run observation evidence.",
            ),
            PlanASensitivityCase(
                case_id="swing-rsi-cap",
                strategy_group="swing",
                parameter="max_rsi",
                baseline_value="58",
                tested_values=("50", "58", "62"),
                decision="keep-default",
                rationale="RSI cap changes are plausible but not yet supported by a superior robustness artifact.",
            ),
            PlanASensitivityCase(
                case_id="portfolio-group-caps",
                strategy_group="portfolio",
                parameter="signal_group_max_open_positions",
                baseline_value="day=2,swing=5,total=7",
                tested_values=("day=1,swing=5,total=6", "day=2,swing=5,total=7"),
                decision="keep-default",
                rationale="Plan A exact day=2 plus swing=5 portfolio passed; day=1 remains Plan B fallback rather than replacement.",
            ),
        ),
        notes=(
            "This is a bounded sensitivity decision record, not a broad optimizer result.",
            "Future perturbations that improve robustness without worsening cost, continuity, risk, or field alignment may be carried as candidate B without additional user approval.",
            "UI implementation remains out of scope for this dry-run ledger stage.",
        ),
    )


def write_plan_a_sensitivity_decision(decision: PlanASensitivityDecision, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(_json_safe(asdict(decision)), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_plan_a_historical_dry_run(
    bars: list[Bar],
    *,
    trading_date: date | None = None,
    session_id: str | None = None,
    max_trading_days: int | None = None,
    starting_seeds: tuple[Decimal, ...] = (Decimal("1000000"), Decimal("2000000")),
    strategy_factory: Callable[[], Any] | None = None,
    prior_open_swing_positions: tuple[VirtualPosition, ...] = (),
    api_rate_limit_per_second: int = 5,
    local_free_space_gb: Decimal = Decimal("38"),
    raw_burst_enabled: bool = False,
    blacklist_snapshot: AsyncBlacklistSnapshot | None = None,
    strategies_by_symbol: dict[Any, Any] | None = None,
    strategy_scope: str = "",
) -> DryRunReport:
    if api_rate_limit_per_second <= 0:
        raise ValueError("api_rate_limit_per_second must be positive")
    if local_free_space_gb < 0:
        raise ValueError("local_free_space_gb must be non-negative")
    if not bars:
        if trading_date is None:
            raise ValueError("trading_date is required when dry-run bars are empty")
        return build_empty_plan_a_dry_run_report(trading_date=trading_date, session_id=session_id)

    selected_bars = _limit_bars_by_trading_day(bars, max_trading_days=max_trading_days)
    first_date = trading_date or _session_date(min(bar.timestamp for bar in selected_bars))
    session = DryRunSession(
        session_id=session_id or f"plan-a-dry-run-{first_date.isoformat()}",
        trading_date=first_date,
        package_id=PLAN_A_PACKAGE_ID,
    )
    package = build_plan_a_strategy_package()
    capital_cases = build_plan_a_capital_cases()
    state = _DryRunState(package=package)
    strategy_factory = strategy_factory or IntradayMomentumSwingSupportPortfolioStrategy
    strategies = strategies_by_symbol if strategies_by_symbol is not None else {}
    for symbol in sorted({bar.symbol for bar in selected_bars}):
        strategy_key = (strategy_scope, symbol) if strategy_scope else symbol
        strategies.setdefault(strategy_key, strategy_factory())

    bars_by_timestamp: dict[datetime, list[Bar]] = {}
    for bar in sorted(selected_bars, key=lambda item: (item.timestamp, item.symbol)):
        bars_by_timestamp.setdefault(bar.timestamp, []).append(bar)
    first_timestamp = min(bars_by_timestamp)
    first_blacklist_evaluation = (
        blacklist_snapshot.evaluation(now=first_timestamp)
        if blacklist_snapshot is not None
        else None
    )
    if first_blacklist_evaluation is not None and first_blacklist_evaluation.flags:
        state.risk_events.append(
            RiskEvent(
                timestamp=first_timestamp,
                event_type="async-blacklist",
                severity="block" if first_blacklist_evaluation.stale else "warn",
                message=",".join(first_blacklist_evaluation.flags),
            )
        )
    _seed_prior_open_swing_positions(
        state=state,
        positions=prior_open_swing_positions,
        entry_time=first_timestamp,
    )

    for timestamp, timestamp_bars in sorted(bars_by_timestamp.items()):
        blacklist_evaluation = (
            blacklist_snapshot.evaluation(now=timestamp)
            if blacklist_snapshot is not None
            else None
        )
        risk_state = _risk_state_from_blacklist_evaluation(blacklist_evaluation, timestamp=timestamp)
        if _is_lock_step_window(timestamp):
            state.risk_events.append(
                RiskEvent(
                    timestamp=timestamp,
                    event_type="lock-step-window",
                    severity="info",
                    message="15:15 day/swing state mutation is sequenced in no-order dry-run",
                )
            )
        entry_candidates: list[tuple[Bar, SignalIntent]] = []
        for bar in sorted(timestamp_bars, key=lambda item: item.symbol):
            state.latest_prices[bar.symbol] = bar.close
            position = state.positions.get(bar.symbol)
            if position is not None:
                close_reason = _position_close_reason(
                    position,
                    bar,
                )
                if close_reason is not None:
                    state.virtual_position_closes.append(_position_close(position, bar, reason=close_reason))
                    del state.positions[bar.symbol]
                    state.scouter_decision_snapshots.append(
                        _scouter_decision_snapshot(
                            bar=bar,
                            signal=SignalIntent(action="hold", reason="closed-position-same-bar-cooldown", group=position.strategy_group),
                            rank=None,
                            passed=False,
                            reason="closed-position-same-bar-cooldown",
                        )
                    )
                    state.interlock_events.append(
                        InterlockEvent(
                            timestamp=timestamp,
                            symbol=bar.symbol,
                            event_type="closed-symbol-skip",
                            source_strategy=position.strategy_group,
                            blocked_strategy=position.strategy_group,
                            reason="same-bar-close-reentry-cooldown",
                        )
                    )
                    continue
                strategy_key = (strategy_scope, bar.symbol) if strategy_scope else bar.symbol
                signal = _strategy_on_bar(strategies[strategy_key], bar, risk_state)
                state.scouter_decision_snapshots.append(
                    _scouter_decision_snapshot(
                        bar=bar,
                        signal=signal,
                        rank=None,
                        passed=False,
                        reason=(
                            "held-symbol-interlock"
                            if signal.action == "buy"
                            else signal.reason or "no-buy-signal"
                        ),
                    )
                )
                if signal.action == "buy":
                    event_type = "held-symbol-skip"
                    if _is_lock_step_window(timestamp) and signal.group == "swing":
                        event_type = "same-symbol-1515-cooldown"
                    state.interlock_events.append(
                        InterlockEvent(
                            timestamp=timestamp,
                            symbol=bar.symbol,
                            event_type=event_type,
                            source_strategy=position.strategy_group,
                            blocked_strategy=signal.group or "unknown",
                            reason="first-in-first-served-held-symbol-interlock",
                            cooldown_expiry=_next_session_date(timestamp) if event_type == "same-symbol-1515-cooldown" else None,
                        )
                    )
                continue

            if blacklist_evaluation is not None and blacklist_evaluation.blocks_symbol(bar.symbol):
                reason = blacklist_evaluation.block_reason(bar.symbol)
                state.scouter_decision_snapshots.append(
                    _scouter_decision_snapshot(
                        bar=bar,
                        signal=SignalIntent(action="hold", reason=reason),
                        rank=None,
                        passed=False,
                        reason=reason,
                    )
                )
                continue

            strategy_key = (strategy_scope, bar.symbol) if strategy_scope else bar.symbol
            signal = _strategy_on_bar(strategies[strategy_key], bar, risk_state)
            if signal.action == "buy" and signal.weight > 0:
                entry_candidates.append((bar, signal))
            else:
                state.scouter_decision_snapshots.append(
                    _scouter_decision_snapshot(
                        bar=bar,
                        signal=signal,
                        rank=None,
                        passed=False,
                        reason=signal.reason or "no-buy-signal",
                    )
                )

        ranked_candidates = sorted(entry_candidates, key=lambda item: (-item[1].score, item[0].symbol))
        for rank, (bar, signal) in enumerate(ranked_candidates, start=1):
            state.scouter_decision_snapshots.append(
                _scouter_decision_snapshot(
                    bar=bar,
                    signal=signal,
                    rank=rank,
                    passed=True,
                    reason=signal.reason,
                )
            )
            state.scouter_candidates.append(
                ScouterCandidate(
                    timestamp=timestamp,
                    symbol=bar.symbol,
                    strategy_group=signal.group or "unknown",
                    score=signal.score,
                    passed=True,
                    reason=signal.reason,
                    rank=rank,
                )
            )
            if bar.symbol in state.positions:
                continue
            if not state.has_slot(signal.group):
                state.interlock_events.append(
                    InterlockEvent(
                        timestamp=bar.timestamp,
                        symbol=bar.symbol,
                        event_type="group-cap-skip",
                        source_strategy=signal.group or "unknown",
                        blocked_strategy=signal.group or "unknown",
                        reason="dry-run-group-or-total-slot-cap-reached",
                    )
                )
                continue
            intended_price = bar.close
            simulated_entry_price = _entry_price_with_slippage(intended_price)
            quantity = Decimal("1")
            strategy_group = signal.group or "unknown"
            strategy_id = _strategy_id_for_group(strategy_group, package)
            exit_policy = _exit_policy_name(signal)
            order = VirtualOrder(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                strategy_group=strategy_group,
                side="buy",
                quantity=quantity,
                intended_price=intended_price,
                reason_code=signal.reason,
                hard_blocked=True,
                strategy_id=strategy_id,
                entry_rule=signal.reason,
                exit_policy=exit_policy,
                cost_model=_dry_run_cost_model(),
                applied_profit_target=signal.profit_target,
                applied_hard_stop=signal.hard_stop,
                applied_max_holding_minutes=signal.max_holding_minutes,
                applied_day_end_exit=signal.day_end_exit,
            )
            state.virtual_orders.append(order)
            state.virtual_fills.append(
                VirtualFill(
                    timestamp=bar.timestamp,
                    symbol=bar.symbol,
                    expected_price=intended_price,
                    simulated_price=simulated_entry_price,
                    slippage_assumption=DRY_RUN_SLIPPAGE_RATE,
                )
            )
            position = VirtualPosition(
                position_id=f"{bar.symbol}-{bar.timestamp.isoformat()}",
                symbol=bar.symbol,
                strategy_group=strategy_group,
                quantity=quantity,
                entry_price=simulated_entry_price,
                slot_id=f"{signal.group or 'unknown'}-{state.group_count(signal.group) + 1}",
                sleeve_id=strategy_group,
                exit_policy=exit_policy,
                profit_target=signal.profit_target,
                hard_stop=signal.hard_stop,
                max_holding_minutes=signal.max_holding_minutes,
                day_end_exit=bool(signal.day_end_exit),
                entry_time=bar.timestamp,
                strategy_id=strategy_id,
                entry_rule=signal.reason,
                cost_model=_dry_run_cost_model(),
            )
            state.positions[bar.symbol] = _OpenDryRunPosition(
                position=position,
                entry_time=bar.timestamp,
                profit_target=signal.profit_target,
                hard_stop=signal.hard_stop,
                max_holding_minutes=signal.max_holding_minutes,
                day_end_exit=bool(signal.day_end_exit),
            )
            state.virtual_positions.append(position)

    observed_days = tuple(sorted({_session_date(bar.timestamp) for bar in selected_bars}))
    open_state_positions = tuple(state.positions.values())
    pnl_snapshots = _pnl_snapshots(
        trading_days=observed_days,
        open_positions=open_state_positions,
        closes=tuple(state.virtual_position_closes),
        latest_prices=state.latest_prices,
    )
    storage_guardrail_checks = _storage_guardrail_checks(
        observed_days,
        local_free_space_gb=local_free_space_gb,
        raw_burst_enabled=raw_burst_enabled,
    )
    report = DryRunReport(
        session=session,
        strategy_package=package,
        capital_cases=capital_cases,
        observed_trading_days=observed_days,
        universe_snapshots=(
            UniverseSnapshot(
                universe_id=f"observed-{first_date.isoformat()}",
                included_symbols=tuple(sorted({bar.symbol for bar in selected_bars})),
            ),
        ),
        scouter_decision_snapshots=tuple(state.scouter_decision_snapshots),
        scouter_candidates=tuple(state.scouter_candidates),
        interlock_events=tuple(state.interlock_events),
        virtual_orders=tuple(state.virtual_orders),
        virtual_fills=tuple(state.virtual_fills),
        virtual_positions=tuple(state.virtual_positions),
        virtual_position_closes=tuple(state.virtual_position_closes),
        risk_events=tuple(state.risk_events),
        capital_feasibility=_capital_feasibility(
            package=package,
            capital_cases=capital_cases,
            starting_seeds=starting_seeds,
            orders=tuple(state.virtual_orders),
        ),
        daily_reconciliation=_daily_reconciliation(
            trading_days=observed_days,
            orders=tuple(state.virtual_orders),
            fills=tuple(state.virtual_fills),
            positions=tuple(state.virtual_positions),
            closes=tuple(state.virtual_position_closes),
            interlocks=tuple(state.interlock_events),
            risk_events=tuple(state.risk_events),
        ),
        open_positions=tuple(open_position.position for open_position in open_state_positions),
        plan_b_fallback=_plan_b_fallback(package=package, state=state),
        opening_survival_checks=_opening_survival_checks(
            observed_days,
            prior_open_swing_positions=prior_open_swing_positions,
        ),
        api_rate_limit_checks=_api_rate_limit_checks(
            observed_days,
            api_rate_limit_per_second=api_rate_limit_per_second,
            estimated_peak_per_second=_dry_run_estimated_peak_per_second(
                selected_bars,
                api_rate_limit_per_second=api_rate_limit_per_second,
            ),
            timestamps=tuple(bar.timestamp for bar in selected_bars),
            data_source=_dry_run_data_source(selected_bars),
        ),
        pnl_snapshots=pnl_snapshots,
        portfolio_states=(),
        storage_guardrail_checks=storage_guardrail_checks,
    )
    validate_no_order_report(report)
    return report


def run_plan_a_multi_session_dry_run(
    bars: list[Bar],
    *,
    run_id: str,
    starting_seed: Decimal = Decimal("1000000"),
    max_trading_days: int | None = None,
    api_rate_limit_per_second: int = 5,
    local_free_space_gb: Decimal = Decimal("38"),
    raw_burst_enabled: bool = False,
    strategy_factory: Callable[[], Any] | None = None,
    blacklist_snapshot: AsyncBlacklistSnapshot | None = None,
) -> DryRunMultiSessionReport:
    if not bars:
        raise ValueError("multi-session dry-run requires at least one bar")
    if starting_seed <= 0:
        raise ValueError("starting_seed must be positive")
    if api_rate_limit_per_second <= 0:
        raise ValueError("api_rate_limit_per_second must be positive")
    if local_free_space_gb < 0:
        raise ValueError("local_free_space_gb must be non-negative")

    selected_bars = _limit_bars_by_trading_day(bars, max_trading_days=max_trading_days)
    bars_by_day: dict[date, list[Bar]] = {}
    for bar in selected_bars:
        bars_by_day.setdefault(_session_date(bar.timestamp), []).append(bar)

    package = build_plan_a_strategy_package()
    sessions: list[DryRunReport] = []
    cash_rows: list[DryRunCashReconciliation] = []
    pnl_rows: list[DryRunPnlSnapshot] = []
    portfolio_states: list[DryRunPortfolioState] = []
    storage_checks: list[DryRunStorageGuardrailCheck] = []
    checkpoint_events: list[DryRunCheckpointEvent] = []
    api_checks: list[DryRunApiRateLimitCheck] = []
    open_swing_positions: tuple[VirtualPosition, ...] = ()
    cash = starting_seed
    previous_week: tuple[int, int] | None = None
    strategies_by_symbol: dict[Any, Any] = {}

    for day_index, trading_day in enumerate(sorted(bars_by_day), start=1):
        week = _iso_week(trading_day)
        contribution = Decimal("0")
        if previous_week is not None and week != previous_week:
            contribution = package.weekly_contribution
            cash += contribution
        previous_week = week

        report = run_plan_a_historical_dry_run(
            bars_by_day[trading_day],
            trading_date=trading_day,
            session_id=f"{run_id}-{trading_day.isoformat()}",
            starting_seeds=(starting_seed,),
            strategy_factory=strategy_factory,
            prior_open_swing_positions=open_swing_positions,
            api_rate_limit_per_second=api_rate_limit_per_second,
            local_free_space_gb=local_free_space_gb,
            raw_burst_enabled=raw_burst_enabled,
            blacklist_snapshot=blacklist_snapshot,
            strategies_by_symbol=strategies_by_symbol,
            strategy_scope=run_id,
        )
        pnl_snapshot = report.pnl_snapshots[0] if report.pnl_snapshots else _empty_pnl_snapshot(trading_day)
        cash_row = _cash_reconciliation(
            trading_day=trading_day,
            starting_cash=cash - contribution,
            external_contribution=contribution,
            orders=report.virtual_orders,
            closes=report.virtual_position_closes,
            open_positions=report.open_positions,
            package=package,
        )
        cash = cash_row.ending_cash
        portfolio_state = _portfolio_state(
            trading_day=trading_day,
            cash_row=cash_row,
            pnl_snapshot=pnl_snapshot,
            open_positions=report.open_positions,
        )
        day_checkpoints = _checkpoint_events(
            trading_day=trading_day,
            day_index=day_index,
            cash_row=cash_row,
            pnl_snapshot=pnl_snapshot,
            report=report,
            package=package,
        )
        report = replace(
            report,
            cash_reconciliation=(cash_row,),
            pnl_snapshots=(pnl_snapshot,),
            portfolio_states=(portfolio_state,),
            checkpoint_events=day_checkpoints,
        )
        sessions.append(report)
        cash_rows.append(cash_row)
        pnl_rows.append(pnl_snapshot)
        portfolio_states.append(portfolio_state)
        storage_checks.extend(report.storage_guardrail_checks)
        checkpoint_events.extend(day_checkpoints)
        api_checks.extend(report.api_rate_limit_checks)
        open_swing_positions = tuple(
            position for position in report.open_positions if position.strategy_group == "swing"
        )

    multi_report = DryRunMultiSessionReport(
        run_id=run_id,
        strategy_package=package,
        starting_seed=starting_seed,
        weekly_contribution=package.weekly_contribution,
        sessions=tuple(sessions),
        cash_reconciliation=tuple(cash_rows),
        pnl_snapshots=tuple(pnl_rows),
        portfolio_states=tuple(portfolio_states),
        storage_guardrail_checks=tuple(storage_checks),
        checkpoint_events=tuple(checkpoint_events),
        api_rate_limit_checks=tuple(api_checks),
    )
    validate_no_order_multi_session_report(multi_report)
    return multi_report


def validate_no_order_report(report: DryRunReport) -> None:
    if report.session.mode != "no-order":
        raise ValueError("dry-run session mode must be no-order")
    if not report.session.order_hard_block:
        raise ValueError("dry-run session must hard-block order transmission")
    unblocked = [order for order in report.virtual_orders if not order.hard_blocked]
    if unblocked:
        raise ValueError("dry-run report contains virtual orders without hard-block evidence")
    if report.summary()["ready_for_broker_or_order_transmission"]:
        raise ValueError("dry-run report must never be ready for broker or order transmission")


def validate_no_order_multi_session_report(report: DryRunMultiSessionReport) -> None:
    if report.summary()["ready_for_broker_or_order_transmission"]:
        raise ValueError("multi-session dry-run report must never be ready for broker or order transmission")
    for session in report.sessions:
        validate_no_order_report(session)


def write_dry_run_report(report: DryRunReport, output: Path) -> None:
    validate_no_order_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": report.summary(),
        "report": _json_safe(asdict(report)),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_multi_session_dry_run_report(report: DryRunMultiSessionReport, output: Path) -> None:
    validate_no_order_multi_session_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": report.summary(),
        "report": _json_safe(asdict(report)),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dry_run_ledger_events(report: DryRunReport) -> tuple[dict[str, Any], ...]:
    validate_no_order_report(report)
    events: list[dict[str, Any]] = []

    def append_event(
        event_type: str,
        payload: dict[str, Any],
        *,
        event_time: datetime | None = None,
        symbol: str = "",
        strategy_group: str = "",
    ) -> None:
        events.append(
            {
                "sequence": len(events) + 1,
                "event_type": event_type,
                "event_time": event_time,
                "symbol": symbol,
                "strategy_group": strategy_group,
                "payload": payload,
            }
        )

    append_event("session-summary", report.summary())
    for item in report.universe_snapshots:
        append_event("universe-snapshot", asdict(item))
    for item in report.opening_survival_checks:
        append_event("opening-survival-check", asdict(item))
    for item in report.scouter_decision_snapshots:
        append_event(
            "scouter-decision-snapshot",
            asdict(item),
            event_time=item.timestamp,
            symbol=item.symbol,
            strategy_group=item.strategy_group,
        )
    for item in report.scouter_candidates:
        append_event("scouter-candidate", asdict(item), event_time=item.timestamp, symbol=item.symbol, strategy_group=item.strategy_group)
    for item in report.virtual_orders:
        append_event("virtual-order", asdict(item), event_time=item.timestamp, symbol=item.symbol, strategy_group=item.strategy_group)
    for item in report.virtual_fills:
        append_event("virtual-fill", asdict(item), event_time=item.timestamp, symbol=item.symbol)
    for item in report.virtual_positions:
        append_event("virtual-position", asdict(item), symbol=item.symbol, strategy_group=item.strategy_group)
    for item in report.virtual_position_closes:
        append_event(
            "virtual-position-close",
            asdict(item),
            event_time=item.exit_time,
            symbol=item.symbol,
            strategy_group=item.strategy_group,
        )
    for item in report.interlock_events:
        append_event("interlock-event", asdict(item), event_time=item.timestamp, symbol=item.symbol)
    for item in report.risk_events:
        append_event("risk-event", asdict(item), event_time=item.timestamp)
    for item in report.capital_feasibility:
        append_event("capital-feasibility", asdict(item))
    for item in report.daily_reconciliation:
        append_event("daily-reconciliation", asdict(item))
    for item in report.open_positions:
        append_event("open-position", asdict(item), symbol=item.symbol, strategy_group=item.strategy_group)
    for item in report.cash_reconciliation:
        append_event("cash-reconciliation", asdict(item))
    for item in report.pnl_snapshots:
        append_event("pnl-snapshot", asdict(item))
    for item in report.portfolio_states:
        append_event("portfolio-state", asdict(item))
    for item in report.storage_guardrail_checks:
        append_event("storage-guardrail-check", asdict(item))
    for item in report.api_rate_limit_checks:
        append_event("api-rate-limit-check", asdict(item))
    for item in report.checkpoint_events:
        append_event("checkpoint-event", asdict(item))
    if report.plan_b_fallback is not None:
        append_event("plan-b-fallback-state", asdict(report.plan_b_fallback), event_time=report.plan_b_fallback.activated_at)
    return tuple(events)


def persist_dry_run_report(report: DryRunReport) -> int:
    from zurini.data import db

    validate_no_order_report(report)
    return db.insert_dry_run_ledger(
        session_id=report.session.session_id,
        trading_date=report.session.trading_date,
        package_id=report.session.package_id,
        mode=report.session.mode,
        order_hard_block=report.session.order_hard_block,
        summary=report.summary(),
        events=dry_run_ledger_events(report),
    )


def persist_multi_session_dry_run_report(report: DryRunMultiSessionReport) -> int:
    from zurini.data import db

    validate_no_order_multi_session_report(report)
    return db.insert_dry_run_ledgers(
        {
            "session_id": session.session.session_id,
            "trading_date": session.session.trading_date,
            "package_id": session.session.package_id,
            "mode": session.session.mode,
            "order_hard_block": session.session.order_hard_block,
            "summary": session.summary(),
            "events": dry_run_ledger_events(session),
        }
        for session in report.sessions
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class _OpenDryRunPosition:
    position: VirtualPosition
    entry_time: datetime
    profit_target: Decimal | None
    hard_stop: Decimal | None
    max_holding_minutes: int | None
    day_end_exit: bool

    @property
    def symbol(self) -> str:
        return self.position.symbol

    @property
    def strategy_group(self) -> str:
        return self.position.strategy_group


@dataclass
class _DryRunState:
    package: StrategyPackage
    positions: dict[str, _OpenDryRunPosition] = field(default_factory=dict)
    latest_prices: dict[str, Decimal] = field(default_factory=dict)
    scouter_decision_snapshots: list[ScouterDecisionSnapshot] = field(default_factory=list)
    scouter_candidates: list[ScouterCandidate] = field(default_factory=list)
    interlock_events: list[InterlockEvent] = field(default_factory=list)
    virtual_orders: list[VirtualOrder] = field(default_factory=list)
    virtual_fills: list[VirtualFill] = field(default_factory=list)
    virtual_positions: list[VirtualPosition] = field(default_factory=list)
    virtual_position_closes: list[VirtualPositionClose] = field(default_factory=list)
    risk_events: list[RiskEvent] = field(default_factory=list)

    def group_count(self, group: str) -> int:
        return sum(1 for position in self.positions.values() if position.strategy_group == group)

    def has_slot(self, group: str) -> bool:
        if len(self.positions) >= self.package.total_max_slots:
            return False
        if group == "day":
            return self.group_count(group) < self.package.day_max_slots
        if group == "swing":
            return self.group_count(group) < self.package.swing_max_slots
        return True


def _seed_prior_open_swing_positions(
    *,
    state: _DryRunState,
    positions: tuple[VirtualPosition, ...],
    entry_time: datetime,
) -> None:
    for position in positions:
        if position.strategy_group != "swing":
            continue
        state.positions[position.symbol] = _OpenDryRunPosition(
            position=position,
            entry_time=position.entry_time or entry_time,
            profit_target=position.profit_target,
            hard_stop=position.hard_stop,
            max_holding_minutes=position.max_holding_minutes,
            day_end_exit=position.day_end_exit,
        )


def _limit_bars_by_trading_day(bars: list[Bar], *, max_trading_days: int | None) -> list[Bar]:
    if max_trading_days is None:
        return list(bars)
    if max_trading_days <= 0:
        raise ValueError("max_trading_days must be positive")
    allowed_days = sorted({_session_date(bar.timestamp) for bar in bars})[:max_trading_days]
    allowed = set(allowed_days)
    return [bar for bar in bars if _session_date(bar.timestamp) in allowed]


def _risk_state_from_blacklist_evaluation(
    blacklist_evaluation: Any | None,
    *,
    timestamp: datetime,
) -> RiskState:
    if blacklist_evaluation is None:
        return RiskState(blacklist_updated_at=timestamp)
    active_symbols = set(str(symbol) for symbol in blacklist_evaluation.active_symbols)
    active_symbols.update(f"A{symbol}" for symbol in blacklist_evaluation.active_symbols)
    return RiskState(
        blacklist_updated_at=timestamp if not blacklist_evaluation.stale else timestamp - timedelta(minutes=6),
        blacklisted_symbols=frozenset(active_symbols),
    )


def _strategy_on_bar(strategy: Any, bar: Bar, risk: RiskState) -> SignalIntent:
    parameters = inspect.signature(strategy.on_bar).parameters
    if len(parameters) >= 2:
        return strategy.on_bar(bar, risk)
    return strategy.on_bar(bar)


def _session_date(timestamp: datetime) -> date:
    return _as_kst(timestamp).date()


def _next_session_date(timestamp: datetime) -> date:
    return _session_date(timestamp) + timedelta(days=1)


def _is_lock_step_window(timestamp: datetime) -> bool:
    current = _as_kst(timestamp).time()
    return time(15, 10) <= current <= time(15, 20)


def _is_execution_decision_window(timestamp: datetime) -> bool:
    current = _as_kst(timestamp).time()
    return time(15, 15) <= current <= time(15, 20)


def _as_kst(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return timestamp.astimezone(ZoneInfo("Asia/Seoul"))


def _position_close_reason(position: _OpenDryRunPosition, bar: Bar) -> str | None:
    pnl_ratio = (bar.close - position.position.entry_price) / position.position.entry_price
    if position.profit_target is not None and pnl_ratio >= position.profit_target:
        return "profit-target"
    if position.hard_stop is not None and pnl_ratio <= position.hard_stop:
        return "hard-stop"
    if (
        position.max_holding_minutes is not None
        and int((bar.timestamp - position.entry_time).total_seconds() // 60) >= position.max_holding_minutes
    ):
        return "max-holding-minutes"
    if position.day_end_exit and _is_execution_decision_window(bar.timestamp):
        return "day-end-exit"
    return None


def _position_close(position: _OpenDryRunPosition, bar: Bar, *, reason: str) -> VirtualPositionClose:
    exit_price = _exit_price_with_slippage(bar.close)
    total_fees = _round_money(
        (position.position.entry_price + exit_price)
        * position.position.quantity
        * DRY_RUN_FEE_RATE
    )
    realized_pnl = _round_money(
        (exit_price - position.position.entry_price) * position.position.quantity
        - total_fees
    )
    return VirtualPositionClose(
        position_id=position.position.position_id,
        symbol=position.symbol,
        strategy_group=position.strategy_group,
        quantity=position.position.quantity,
        entry_price=position.position.entry_price,
        exit_price=exit_price,
        exit_time=bar.timestamp,
        realized_pnl=realized_pnl,
        reason=reason,
        fee_rate=DRY_RUN_FEE_RATE,
        slippage_rate=DRY_RUN_SLIPPAGE_RATE,
        total_fees=total_fees,
        strategy_id=position.position.strategy_id,
        entry_rule=position.position.entry_rule,
        exit_policy=position.position.exit_policy,
        slot_id=position.position.slot_id,
        sleeve_id=position.position.sleeve_id,
        cost_model=position.position.cost_model,
        applied_profit_target=position.position.profit_target,
        applied_hard_stop=position.position.hard_stop,
        applied_max_holding_minutes=position.position.max_holding_minutes,
        applied_day_end_exit=position.position.day_end_exit,
    )


def _entry_price_with_slippage(price: Decimal) -> Decimal:
    return _round_money(price * (Decimal("1") + DRY_RUN_SLIPPAGE_RATE))


def _exit_price_with_slippage(price: Decimal) -> Decimal:
    return _round_money(price * (Decimal("1") - DRY_RUN_SLIPPAGE_RATE))


def _cash_buy_outflow(price: Decimal, quantity: Decimal) -> Decimal:
    return _round_money(price * quantity * (Decimal("1") + DRY_RUN_FEE_RATE))


def _cash_sell_inflow(price: Decimal, quantity: Decimal) -> Decimal:
    return _round_money(price * quantity * (Decimal("1") - DRY_RUN_FEE_RATE))


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


def _scouter_decision_snapshot(
    *,
    bar: Bar,
    signal: SignalIntent,
    rank: int | None,
    passed: bool,
    reason: str,
) -> ScouterDecisionSnapshot:
    return ScouterDecisionSnapshot(
        timestamp=bar.timestamp,
        symbol=bar.symbol,
        strategy_group=signal.group or "unknown",
        action=signal.action,
        score=signal.score,
        rank=rank,
        passed=passed,
        reason=reason,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        traded_value=bar.value,
        bid_ask_ratio=bar.bid_ask_ratio,
        source=bar.source,
        input_flags=_bar_input_flags(bar),
    )


def _bar_input_flags(bar: Bar) -> tuple[str, ...]:
    flags: list[str] = []
    if bar.source.startswith("kis-readonly-report:") and bar.open == bar.high == bar.low == bar.close:
        flags.append("ohlc_fallback")
    if bar.volume <= 0:
        flags.append("volume_missing")
    if bar.value <= 0:
        flags.append("traded_value_missing")
    if bar.source.startswith("kis-readonly-report:") and bar.bid_ask_ratio == Decimal("2.0"):
        flags.append("bid_ask_placeholder")
    if bar.source.startswith("watchlist-replay:"):
        flags.append("watchlist_replay")
    return tuple(flags)


def _exit_policy_name(signal: SignalIntent) -> str:
    parts = []
    if signal.profit_target is not None:
        parts.append(f"target={signal.profit_target}")
    if signal.hard_stop is not None:
        parts.append(f"stop={signal.hard_stop}")
    if signal.max_holding_minutes is not None:
        parts.append(f"max_minutes={signal.max_holding_minutes}")
    if signal.day_end_exit:
        parts.append("day_end_exit")
    return ";".join(parts) or "default"


def _capital_feasibility(
    *,
    package: StrategyPackage,
    capital_cases: tuple[CapitalComparisonCase, ...],
    starting_seeds: tuple[Decimal, ...],
    orders: tuple[VirtualOrder, ...],
) -> tuple[CapitalFeasibility, ...]:
    results: list[CapitalFeasibility] = []
    for seed in starting_seeds:
        for case in capital_cases:
            day_budget, swing_budget = _slot_budgets(package=package, case=case, seed=seed)
            whole_share_rejects = 0
            insufficient_cash = 0
            day_order_prices = [order.intended_price for order in orders if order.strategy_group == "day"]
            swing_order_prices = [order.intended_price for order in orders if order.strategy_group == "swing"]
            for order in orders:
                budget = day_budget if order.strategy_group == "day" else swing_budget
                if budget <= 0:
                    insufficient_cash += 1
                    continue
                if (budget / order.intended_price).to_integral_value(rounding=ROUND_FLOOR) < 1:
                    whole_share_rejects += 1
            has_day_and_swing_evidence = bool(day_order_prices) and bool(swing_order_prices)
            can_buy_min_day = bool(day_order_prices) and day_budget >= min(day_order_prices)
            can_buy_min_swing = bool(swing_order_prices) and swing_budget >= min(swing_order_prices)
            results.append(
                CapitalFeasibility(
                    starting_seed=seed,
                    case_id=case.case_id,
                    day_slot_budget=day_budget,
                    swing_slot_budget=swing_budget,
                    whole_share_reject_count=whole_share_rejects,
                    insufficient_cash_count=insufficient_cash,
                    simultaneous_day_swing_feasible=(
                        has_day_and_swing_evidence
                        and can_buy_min_day
                        and can_buy_min_swing
                        and whole_share_rejects == 0
                        and insufficient_cash == 0
                    ),
                    note="sizing-only feasibility; excludes occupancy, contributions, reserved cash, and opportunity loss",
                )
            )
    return tuple(results)


def _daily_reconciliation(
    *,
    trading_days: tuple[date, ...],
    orders: tuple[VirtualOrder, ...],
    fills: tuple[VirtualFill, ...],
    positions: tuple[VirtualPosition, ...],
    closes: tuple[VirtualPositionClose, ...],
    interlocks: tuple[InterlockEvent, ...],
    risk_events: tuple[RiskEvent, ...],
) -> tuple[DailyReconciliation, ...]:
    rows: list[DailyReconciliation] = []
    for trading_day in trading_days:
        day_orders = [order for order in orders if _session_date(order.timestamp) == trading_day]
        day_fills = [fill for fill in fills if _session_date(fill.timestamp) == trading_day]
        day_closes = [close for close in closes if _session_date(close.exit_time) == trading_day]
        day_interlocks = [event for event in interlocks if _session_date(event.timestamp) == trading_day]
        day_risk_events = [event for event in risk_events if _session_date(event.timestamp) == trading_day]
        day_positions = [
            position
            for position in positions
            if any(order.symbol == position.symbol and _session_date(order.timestamp) == trading_day for order in day_orders)
        ]
        rows.append(
            DailyReconciliation(
                trading_day=trading_day,
                virtual_order_count=len(day_orders),
                virtual_fill_count=len(day_fills),
                virtual_position_count=len(day_positions),
                day_position_count=sum(1 for position in day_positions if position.strategy_group == "day"),
                swing_position_count=sum(1 for position in day_positions if position.strategy_group == "swing"),
                interlock_event_count=len(day_interlocks),
                risk_event_count=len(day_risk_events),
                unreconciled=len(day_orders) != len(day_fills),
                note=f"no-order reconciliation with {len(day_closes)} virtual closes",
            )
        )
    return tuple(rows)


def _inactive_plan_b_fallback(package: StrategyPackage) -> PlanBFallbackState:
    return PlanBFallbackState(
        active=False,
        reason="Plan A constraints not breached in this dry-run report",
        fallback_package_id=package.fallback_package_id,
    )


def _plan_b_fallback(*, package: StrategyPackage, state: _DryRunState) -> PlanBFallbackState:
    breached = any(event.event_type == "group-cap-skip" for event in state.interlock_events)
    if not breached:
        return _inactive_plan_b_fallback(package)
    first_breach = next(event for event in state.interlock_events if event.event_type == "group-cap-skip")
    return PlanBFallbackState(
        active=True,
        reason="Plan A group or total slot cap was breached by a candidate",
        fallback_package_id=package.fallback_package_id,
        activated_at=first_breach.timestamp,
    )


def _cash_reconciliation(
    *,
    trading_day: date,
    starting_cash: Decimal,
    external_contribution: Decimal,
    orders: tuple[VirtualOrder, ...],
    closes: tuple[VirtualPositionClose, ...],
    open_positions: tuple[VirtualPosition, ...],
    package: StrategyPackage,
) -> DryRunCashReconciliation:
    available_cash = starting_cash + external_contribution
    virtual_buy_notional = sum(
        _cash_buy_outflow(_entry_price_with_slippage(order.intended_price), order.quantity)
        for order in orders
    )
    virtual_sell_notional = sum(_cash_sell_inflow(close.exit_price, close.quantity) for close in closes)
    day_exposure = sum(
        position.quantity * position.entry_price for position in open_positions if position.strategy_group == "day"
    )
    swing_exposure = sum(
        position.quantity * position.entry_price for position in open_positions if position.strategy_group == "swing"
    )
    open_notional = day_exposure + swing_exposure
    ending_cash = max(Decimal("0"), available_cash - virtual_buy_notional + virtual_sell_notional)
    reserved_cash = open_notional
    return DryRunCashReconciliation(
        trading_day=trading_day,
        starting_cash=starting_cash,
        external_contribution=external_contribution,
        virtual_buy_notional=virtual_buy_notional,
        virtual_sell_notional=virtual_sell_notional,
        day_exposure=day_exposure,
        swing_exposure=swing_exposure,
        reserved_cash=reserved_cash,
        idle_cash=ending_cash,
        ending_cash=ending_cash,
        blocked_deployment=available_cash > package.operating_ceiling,
        cash_after_virtual_trades=ending_cash,
        available_cash_after_reserved_exposure=ending_cash,
        note=(
            "virtual no-order cash view; ending_cash/cash_after_virtual_trades already subtract virtual buys "
            "and add virtual sells; reserved_cash reports open virtual exposure separately and must not be "
            "subtracted again when reading available cash; no broker balance, real fill, or account state was read"
        ),
    )


def _checkpoint_events(
    *,
    trading_day: date,
    day_index: int,
    cash_row: DryRunCashReconciliation,
    pnl_snapshot: DryRunPnlSnapshot,
    report: DryRunReport,
    package: StrategyPackage,
) -> tuple[DryRunCheckpointEvent, ...]:
    events = [
        DryRunCheckpointEvent(
            trigger_id=f"order-hard-block-{trading_day.isoformat()}",
            trading_day=trading_day,
            category="safety",
            severity="info",
            message="No-order dry-run session preserved order hard block",
            required_action="continue no-order observation",
            deployment_blocked=True,
        )
    ]
    if day_index in {10, 20}:
        events.append(
            DryRunCheckpointEvent(
                trigger_id=f"dry-run-day-{day_index}",
                trading_day=trading_day,
                category="time",
                severity="review",
                message=f"No-order dry-run reached trading day {day_index}",
                required_action="review dry-run evidence before any field-start decision",
                deployment_blocked=True,
            )
        )
    if cash_row.blocked_deployment:
        events.append(
            DryRunCheckpointEvent(
                trigger_id="operating-ceiling-block",
                trading_day=trading_day,
                category="capital",
                severity="block",
                message=f"Virtual cash exceeds Plan A operating ceiling {package.operating_ceiling}",
                required_action="keep excess capital idle until a new strategy passes validation",
                deployment_blocked=True,
            )
        )
    net_virtual_deployment = max(Decimal("0"), cash_row.virtual_buy_notional - cash_row.virtual_sell_notional)
    if net_virtual_deployment > cash_row.starting_cash + cash_row.external_contribution:
        events.append(
            DryRunCheckpointEvent(
                trigger_id=f"cash-starvation-{trading_day.isoformat()}",
                trading_day=trading_day,
                category="capital",
                severity="warn",
                message="Virtual intended buys exceed available dry-run cash",
                required_action="treat sizing as observation-only until capital contract is feasible",
                deployment_blocked=True,
            )
        )
    if report.plan_b_fallback is not None and report.plan_b_fallback.active:
        events.append(
            DryRunCheckpointEvent(
                trigger_id=f"plan-b-fallback-{trading_day.isoformat()}",
                trading_day=trading_day,
                category="fallback",
                severity="review",
                message=report.plan_b_fallback.reason,
                required_action="review Plan A constraint breach and compare Plan B continuation",
                deployment_blocked=True,
            )
        )
    if pnl_snapshot.realized_pnl < Decimal("0"):
        events.append(
            DryRunCheckpointEvent(
                trigger_id=f"realized-loss-review-{trading_day.isoformat()}",
                trading_day=trading_day,
                category="risk",
                severity="review",
                message=f"Virtual realized PnL is negative: {pnl_snapshot.realized_pnl}",
                required_action="review execution-quality and risk-fuse evidence before promotion",
                deployment_blocked=True,
            )
        )
    for item in report.api_rate_limit_checks:
        if not item.within_limit:
            events.append(
                DryRunCheckpointEvent(
                    trigger_id=f"api-rate-limit-{trading_day.isoformat()}",
                    trading_day=trading_day,
                    category="api-rate-limit",
                    severity="block",
                    message="Estimated field API calls exceed the configured per-second limit",
                    required_action="throttle or batch field API reads before dry-run promotion",
                    deployment_blocked=True,
                )
            )
    for item in report.storage_guardrail_checks:
        if item.action == "storage-warning":
            events.append(
                DryRunCheckpointEvent(
                    trigger_id=f"storage-warning-{trading_day.isoformat()}",
                    trading_day=trading_day,
                    category="storage",
                    severity="warn",
                    message="Local C: free space is below 20 GB",
                    required_action="monitor dry-run DB/log growth and keep full raw polling disabled",
                    deployment_blocked=True,
                )
            )
        elif item.action == "raw-burst-disabled":
            events.append(
                DryRunCheckpointEvent(
                    trigger_id=f"raw-burst-disabled-{trading_day.isoformat()}",
                    trading_day=trading_day,
                    category="storage",
                    severity="block",
                    message="Local C: free space is below 10 GB; raw burst capture must be disabled",
                    required_action="continue only decision snapshots and summary logs",
                    deployment_blocked=True,
                )
            )
        elif item.action == "protective-mode":
            events.append(
                DryRunCheckpointEvent(
                    trigger_id=f"storage-protective-mode-{trading_day.isoformat()}",
                    trading_day=trading_day,
                    category="storage",
                    severity="block",
                    message="Local C: free space is below 5 GB",
                    required_action="block nonessential capture and preserve shutdown/reconciliation evidence",
                    deployment_blocked=True,
                )
            )
    return tuple(events)


def _empty_pnl_snapshot(trading_day: date) -> DryRunPnlSnapshot:
    return DryRunPnlSnapshot(
        trading_day=trading_day,
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        gross_exposure=Decimal("0"),
        day_exposure=Decimal("0"),
        swing_exposure=Decimal("0"),
        open_position_count=0,
        closed_position_count=0,
        note="no virtual position evidence",
    )


def _pnl_snapshots(
    *,
    trading_days: tuple[date, ...],
    open_positions: tuple[_OpenDryRunPosition, ...],
    closes: tuple[VirtualPositionClose, ...],
    latest_prices: dict[str, Decimal],
) -> tuple[DryRunPnlSnapshot, ...]:
    snapshots: list[DryRunPnlSnapshot] = []
    for trading_day in trading_days:
        day_closes = [close for close in closes if _session_date(close.exit_time) == trading_day]
        realized_pnl = sum(close.realized_pnl for close in day_closes)
        unrealized_pnl = sum(
            _cash_sell_inflow(_exit_price_with_slippage(latest_prices.get(position.symbol, position.position.entry_price)), position.position.quantity)
            - _cash_buy_outflow(position.position.entry_price, position.position.quantity)
            for position in open_positions
        )
        day_exposure = sum(
            position.position.entry_price * position.position.quantity
            for position in open_positions
            if position.strategy_group == "day"
        )
        swing_exposure = sum(
            position.position.entry_price * position.position.quantity
            for position in open_positions
            if position.strategy_group == "swing"
        )
        snapshots.append(
            DryRunPnlSnapshot(
                trading_day=trading_day,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                gross_exposure=day_exposure + swing_exposure,
                day_exposure=day_exposure,
                swing_exposure=swing_exposure,
                open_position_count=len(open_positions),
                closed_position_count=len(day_closes),
                note=(
                    "virtual PnL applies conservative dry-run fee_rate=0.00030 and "
                    "slippage_rate=0.00100 assumptions; no broker fill, account, or tax evidence"
                ),
            )
        )
    return tuple(snapshots)


def _portfolio_state(
    *,
    trading_day: date,
    cash_row: DryRunCashReconciliation,
    pnl_snapshot: DryRunPnlSnapshot,
    open_positions: tuple[VirtualPosition, ...],
) -> DryRunPortfolioState:
    day_slots_used = sum(1 for position in open_positions if position.strategy_group == "day")
    swing_slots_used = sum(1 for position in open_positions if position.strategy_group == "swing")
    return DryRunPortfolioState(
        trading_day=trading_day,
        cash=cash_row.ending_cash,
        reserved_cash=cash_row.reserved_cash,
        day_slots_used=day_slots_used,
        swing_slots_used=swing_slots_used,
        total_slots_used=len(open_positions),
        day_exposure=cash_row.day_exposure,
        swing_exposure=cash_row.swing_exposure,
        realized_pnl=pnl_snapshot.realized_pnl,
        unrealized_pnl=pnl_snapshot.unrealized_pnl,
    )


def _portfolio_states(
    *,
    trading_days: tuple[date, ...],
    cash: Decimal,
    cash_reconciliation: tuple[DryRunCashReconciliation, ...],
    pnl_snapshots: tuple[DryRunPnlSnapshot, ...],
    open_positions: tuple[_OpenDryRunPosition, ...],
) -> tuple[DryRunPortfolioState, ...]:
    rows: list[DryRunPortfolioState] = []
    for trading_day in trading_days:
        cash_row = next(
            (row for row in cash_reconciliation if row.trading_day == trading_day),
            DryRunCashReconciliation(
                trading_day=trading_day,
                starting_cash=cash,
                external_contribution=Decimal("0"),
                virtual_buy_notional=Decimal("0"),
                virtual_sell_notional=Decimal("0"),
                day_exposure=Decimal("0"),
                swing_exposure=Decimal("0"),
                reserved_cash=Decimal("0"),
                idle_cash=cash,
                ending_cash=cash,
                blocked_deployment=False,
                note="single-session state before multi-session cash reconciliation",
            ),
        )
        pnl_snapshot = next(
            (row for row in pnl_snapshots if row.trading_day == trading_day),
            _empty_pnl_snapshot(trading_day),
        )
        rows.append(
            _portfolio_state(
                trading_day=trading_day,
                cash_row=cash_row,
                pnl_snapshot=pnl_snapshot,
                open_positions=tuple(position.position for position in open_positions),
            )
        )
    return tuple(rows)


def _api_rate_limit_checks(
    trading_days: tuple[date, ...],
    *,
    api_rate_limit_per_second: int,
    estimated_peak_per_second: int,
    timestamps: tuple[datetime, ...] = (),
    data_source: str,
) -> tuple[DryRunApiRateLimitCheck, ...]:
    policy = FieldApiBudgetPolicy(provider_limit_per_second=api_rate_limit_per_second)
    return tuple(
        _api_rate_limit_check_for_day(
            trading_day=trading_day,
            api_rate_limit_per_second=api_rate_limit_per_second,
            estimated_peak_per_second=estimated_peak_per_second,
            timestamps=tuple(timestamp for timestamp in timestamps if normalize_to_kst(timestamp).date() == trading_day),
            data_source=data_source,
            policy=policy,
        )
        for trading_day in trading_days
    )


def _api_rate_limit_check_for_day(
    *,
    trading_day: date,
    api_rate_limit_per_second: int,
    estimated_peak_per_second: int,
    timestamps: tuple[datetime, ...],
    data_source: str,
    policy: FieldApiBudgetPolicy,
) -> DryRunApiRateLimitCheck:
    observed_timestamps = () if data_source == "local-csv" else timestamps
    operating_limit = policy.minimum_total_limit_for(list(observed_timestamps))
    estimated_calls = 0 if data_source == "local-csv" else len(observed_timestamps)
    return DryRunApiRateLimitCheck(
        trading_day=trading_day,
        provider="field-api-placeholder",
        limit_per_second=api_rate_limit_per_second,
        operating_limit_per_second=operating_limit,
        estimated_calls=estimated_calls,
        estimated_peak_per_second=estimated_peak_per_second,
        within_limit=estimated_peak_per_second <= operating_limit,
        data_source=data_source,
        note=(
            "local CSV dry-run made no API calls; estimated_peak_per_second is the configured planned field polling budget"
            if data_source == "local-csv"
            else "read-only field API pressure is estimated from observed snapshot cadence"
        ),
    )


def _estimated_field_api_peak_per_second(bars: list[Bar]) -> int:
    counts: dict[datetime, int] = {}
    for bar in bars:
        counts[bar.timestamp.replace(microsecond=0)] = counts.get(bar.timestamp.replace(microsecond=0), 0) + 1
    return max(counts.values(), default=0)


def _dry_run_data_source(bars: list[Bar]) -> str:
    if any(str(bar.source).startswith("kis-readonly-report:") for bar in bars):
        return "kis-readonly-report"
    return "local-csv"


def _dry_run_estimated_peak_per_second(
    bars: list[Bar],
    *,
    api_rate_limit_per_second: int,
) -> int:
    if _dry_run_data_source(bars) == "local-csv":
        return _planned_local_csv_peak_per_second(api_rate_limit_per_second)
    return _estimated_field_api_peak_per_second(bars)


def _planned_local_csv_peak_per_second(api_rate_limit_per_second: int) -> int:
    return min(api_rate_limit_per_second, 1)


def _storage_guardrail_checks(
    trading_days: tuple[date, ...],
    *,
    local_free_space_gb: Decimal,
    raw_burst_enabled: bool,
) -> tuple[DryRunStorageGuardrailCheck, ...]:
    action = "normal"
    within_guardrail = True
    note = "snapshot and decision-ledger retention only; full raw polling is disabled"
    if local_free_space_gb < Decimal("5"):
        action = "protective-mode"
        within_guardrail = False
        note = "block nonessential capture; keep shutdown and reconciliation evidence only"
    elif local_free_space_gb < Decimal("10"):
        action = "raw-burst-disabled"
        note = "disable raw burst capture and keep snapshot/summary logs only"
    elif local_free_space_gb < Decimal("20"):
        action = "storage-warning"
        note = "raise storage warning; monitor DB and log growth"
    if raw_burst_enabled and local_free_space_gb < Decimal("10"):
        raw_burst_enabled = False
    return tuple(
        DryRunStorageGuardrailCheck(
            trading_day=trading_day,
            free_space_gb=local_free_space_gb,
            db_log_soft_cap_gb=Decimal("5"),
            raw_burst_enabled=raw_burst_enabled,
            raw_burst_hard_cap_mb=1000,
            raw_burst_ttl_days=3,
            action=action,
            within_guardrail=within_guardrail,
            note=note,
        )
        for trading_day in trading_days
    )


def _opening_survival_checks(
    trading_days: tuple[date, ...],
    *,
    prior_open_swing_positions: tuple[VirtualPosition, ...] = (),
) -> tuple[OpeningSurvivalCheck, ...]:
    checked_positions = len(prior_open_swing_positions)
    return tuple(
        OpeningSurvivalCheck(
            trading_day=trading_day,
            checked_positions=checked_positions,
            survived_positions=checked_positions,
            failed_positions=0,
            note=(
                "prior virtual swing positions checked from previous dry-run session"
                if checked_positions
                else "no prior open swing ledger position available in this local dry-run slice"
            ),
        )
        for trading_day in trading_days
    )


def _iso_week(trading_day: date) -> tuple[int, int]:
    calendar = trading_day.isocalendar()
    return calendar.year, calendar.week


def _slot_budgets(
    *,
    package: StrategyPackage,
    case: CapitalComparisonCase,
    seed: Decimal,
) -> tuple[Decimal, Decimal]:
    if case.case_id == "shared-slot-plan-a":
        shared_budget = min(package.slot_capital_cap, seed / Decimal(package.total_max_slots))
        return shared_budget, shared_budget
    day_weight = case.day_weight or Decimal("0")
    swing_weight = case.swing_weight or Decimal("0")
    day_budget = seed * day_weight / Decimal(package.day_max_slots)
    swing_budget = seed * swing_weight / Decimal(package.swing_max_slots)
    return day_budget, swing_budget
