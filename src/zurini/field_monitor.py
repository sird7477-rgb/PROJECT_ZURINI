from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from zurini.dry_run import DryRunMultiSessionReport
from zurini.market import Bar


@dataclass(frozen=True)
class FieldDryRunScenario:
    scenario_id: str
    role: str
    strategy_package_id: str
    starting_seed: Decimal
    weekly_contribution: Decimal
    purpose: str
    production_use: str


@dataclass(frozen=True)
class FieldMarketSnapshotContract:
    source: str
    provider: str
    snapshot_count: int
    symbol_count: int
    read_call_count: int
    observed_latency_ms: int | None
    raw_response_persisted: bool
    note: str


@dataclass(frozen=True)
class FieldDryRunScenarioResult:
    scenario_id: str
    role: str
    report_path: str | None
    session_count: int
    virtual_order_count: int
    open_position_count: int
    api_rate_limit_breach_count: int
    storage_guardrail_breach_count: int
    ready_for_broker_or_order_transmission: bool


@dataclass(frozen=True)
class FieldDryRunMonitorStatus:
    run_id: str
    mode: str
    status: str
    generated_at: datetime
    order_hard_block: bool
    ready_for_broker_or_order_transmission: bool
    watch_contract_enabled: bool
    market_schedule: str
    snapshot_contract: FieldMarketSnapshotContract
    scenarios: tuple[FieldDryRunScenario, ...]
    scenario_results: tuple[FieldDryRunScenarioResult, ...]
    flags: tuple[str, ...]
    next_operator_review: str


def build_default_field_dry_run_scenarios() -> tuple[FieldDryRunScenario, ...]:
    return (
        FieldDryRunScenario(
            scenario_id="primary-current-seed-1m",
            role="primary",
            strategy_package_id="plan-a-idmom-d3-fsup-u1s1",
            starting_seed=Decimal("1000000"),
            weekly_contribution=Decimal("100000"),
            purpose="Actual small-seed operating baseline.",
            production_use="Field continuation decisions use this scenario only.",
        ),
        FieldDryRunScenario(
            scenario_id="shadow-current-seed-2m",
            role="shadow",
            strategy_package_id="plan-a-idmom-d3-fsup-u1s1",
            starting_seed=Decimal("2000000"),
            weekly_contribution=Decimal("100000"),
            purpose="Check whether a larger initial seed reduces whole-share and sleeve fragility.",
            production_use="Observation only; may support a later minimum-viable-capital decision.",
        ),
        FieldDryRunScenario(
            scenario_id="shadow-future-seed-50m",
            role="shadow",
            strategy_package_id="plan-a-idmom-d3-fsup-u1s1",
            starting_seed=Decimal("50000000"),
            weekly_contribution=Decimal("100000"),
            purpose="Observe the Plan A conservative capacity checkpoint.",
            production_use="Observation only; not a Plan B validation artifact.",
        ),
        FieldDryRunScenario(
            scenario_id="shadow-future-seed-70m",
            role="shadow",
            strategy_package_id="plan-a-idmom-d3-fsup-u1s1",
            starting_seed=Decimal("70000000"),
            weekly_contribution=Decimal("100000"),
            purpose="Observe Plan A validated ceiling behavior under the same market snapshots.",
            production_use="Observation only; capital above validated capacity remains blocked.",
        ),
        FieldDryRunScenario(
            scenario_id="shadow-slippage-stress-70m",
            role="shadow",
            strategy_package_id="plan-a-idmom-d3-fsup-u1s1",
            starting_seed=Decimal("70000000"),
            weekly_contribution=Decimal("100000"),
            purpose="Reserve a parallel lane for read-only slippage proxy stress once quote depth is available.",
            production_use="Observation only; cannot prove real fills without an approved order stage.",
        ),
    )


def build_field_monitor_status(
    *,
    run_id: str,
    bars: list[Bar],
    reports: dict[str, tuple[DryRunMultiSessionReport, Path]],
    output_dir: Path,
    watch: bool,
    source: str,
    flags: tuple[str, ...] = (),
    api_reports: tuple[dict[str, Any], ...] = (),
) -> FieldDryRunMonitorStatus:
    api_snapshot = _api_snapshot_contract(api_reports)
    snapshot_contract = FieldMarketSnapshotContract(
        source=source,
        provider=api_snapshot["provider"] if api_snapshot else "local-csv" if bars else "pending-read-only-market-api",
        snapshot_count=len(bars),
        symbol_count=len({bar.symbol for bar in bars}),
        read_call_count=int(api_snapshot["read_call_count"]) if api_snapshot else 0,
        observed_latency_ms=api_snapshot["observed_latency_ms"] if api_snapshot else 0 if bars else None,
        raw_response_persisted=False,
        note=(
            str(api_snapshot["note"])
            if api_snapshot
            else
            "single local snapshot stream is fanned out to primary and shadow engines"
            if bars
            else "waiting for approved read-only market-data adapter; no broker/order/account calls"
        ),
    )
    scenario_results = tuple(
        _scenario_result(scenario_id=scenario_id, report=report, path=path)
        for scenario_id, (report, path) in reports.items()
    )
    if api_snapshot and api_snapshot["within_budget"] is False:
        flags = tuple(dict.fromkeys((*flags, "rate_limit_risk")))
    if any(result.api_rate_limit_breach_count for result in scenario_results):
        flags = tuple(dict.fromkeys((*flags, "rate_limit_risk")))
    if any(result.storage_guardrail_breach_count for result in scenario_results):
        flags = tuple(dict.fromkeys((*flags, "storage_warning")))
    status = _monitor_status_for(
        has_bars=bool(bars),
        watch=watch,
        flags=flags,
    )

    return FieldDryRunMonitorStatus(
        run_id=run_id,
        mode="no-order",
        status=status,
        generated_at=datetime.now(timezone.utc),
        order_hard_block=True,
        ready_for_broker_or_order_transmission=False,
        watch_contract_enabled=watch,
        market_schedule="Korea regular session: pre-open checks, 09:00-15:15 monitor, post-close review",
        snapshot_contract=snapshot_contract,
        scenarios=build_default_field_dry_run_scenarios(),
        scenario_results=scenario_results,
        flags=flags,
        next_operator_review="post-close daily review; shadow scenarios are not order authority",
    )


def _api_snapshot_contract(api_reports: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
    if not api_reports:
        return None
    read_calls = 0
    latency_ms: int | None = None
    providers: list[str] = []
    within_budget = True
    for payload in api_reports:
        top_level_calls = int(payload.get("read_call_count") or 0)
        read_calls += top_level_calls
        evidence = payload.get("budget_evidence") or {}
        if evidence:
            providers.append(str(evidence.get("provider") or "KIS"))
            within_budget = within_budget and bool(evidence.get("within_budget"))
            bucket = str(evidence.get("latency_bucket") or "unknown")
            if bucket == "le_250ms":
                latency_ms = max(latency_ms or 0, 250)
            elif bucket == "le_1000ms":
                latency_ms = max(latency_ms or 0, 1000)
            elif bucket == "gt_1000ms":
                latency_ms = max(latency_ms or 0, 1001)
        if top_level_calls or evidence:
            continue
        for probe in payload.get("probes", []):
            probe_name = str(probe.get("name") or "")
            if not probe_name.startswith("kis-") or probe.get("status") == "skipped":
                continue
            read_calls += 1
            providers.append("KIS")
            diagnostics = probe.get("diagnostics") or {}
            flags = tuple(str(flag) for flag in diagnostics.get("flags", ()))
            within_budget = within_budget and "api_rate_limit_risk" not in flags
    provider = ",".join(dict.fromkeys(providers)) if providers else "KIS-read-only"
    return {
        "provider": provider,
        "read_call_count": read_calls,
        "observed_latency_ms": latency_ms,
        "within_budget": within_budget,
        "note": (
            "read-only API budget evidence is within operating budget"
            if within_budget
            else "read-only API budget evidence is degraded or over budget"
        ),
    }


def _monitor_status_for(*, has_bars: bool, watch: bool, flags: tuple[str, ...]) -> str:
    if "market_session_closed" in flags:
        return "session_closed"
    has_api = any(flag.startswith("api_") or flag == "rate_limit_risk" for flag in flags)
    has_risk_feed = any(flag.startswith("blacklist_") or flag.startswith("news_") for flag in flags)
    has_input_contract = any(
        flag == "input_contract_degraded"
        or flag == "bid_ask_placeholder"
        or flag.startswith("field_data_incomplete:")
        or flag.startswith("invalid_market_timestamp")
        for flag in flags
    )
    has_storage = "storage_warning" in flags
    if has_api and has_risk_feed:
        return "api_and_risk_degraded"
    if has_api:
        return "api_degraded"
    if has_risk_feed:
        return "risk_feed_degraded"
    if has_input_contract:
        return "input_degraded"
    if has_storage:
        return "storage_degraded"
    if not has_bars:
        return "waiting_for_market_data"
    return "running" if watch else "session_complete"


def write_field_monitor_status(status: FieldDryRunMonitorStatus, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_json_safe(asdict(status)), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_terminal_field_monitor_status(
    *,
    output: Path,
    run_id: str,
    watch: bool,
    source: str,
    flags: tuple[str, ...] = ("market_session_closed",),
    api_reports: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Mark the monitor terminal without rewriting review/watchlist artifacts."""

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        payload = json.loads(output.read_text(encoding="utf-8"))
    else:
        status = build_field_monitor_status(
            run_id=run_id,
            bars=[],
            reports={},
            output_dir=output.parent,
            watch=watch,
            source=source,
            flags=flags,
            api_reports=api_reports,
        )
        payload = _json_safe(asdict(status))

    existing_flags = tuple(str(flag) for flag in payload.get("flags", ()))
    terminal_flags = list(dict.fromkeys((*flags, *existing_flags)))
    payload.update(
        {
            "run_id": payload.get("run_id") or run_id,
            "mode": "no-order",
            "status": (
                "session_closed"
                if "market_session_closed" in terminal_flags
                else payload.get("status", "session_closed")
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "order_hard_block": True,
            "ready_for_broker_or_order_transmission": False,
            "watch_contract_enabled": bool(payload.get("watch_contract_enabled", watch)),
            "flags": terminal_flags,
        }
    )
    payload.setdefault("scenarios", _json_safe([asdict(item) for item in build_default_field_dry_run_scenarios()]))
    payload.setdefault("scenario_results", [])
    payload.setdefault(
        "snapshot_contract",
        _json_safe(
            asdict(
                FieldMarketSnapshotContract(
                    source=source,
                    provider="pending-read-only-market-api",
                    snapshot_count=0,
                    symbol_count=0,
                    read_call_count=0,
                    observed_latency_ms=None,
                    raw_response_persisted=False,
                    note="waiting for approved read-only market-data adapter; no broker/order/account calls",
                )
            )
        ),
    )
    payload.setdefault(
        "market_schedule",
        "Korea regular session: pre-open checks, 09:00-15:15 monitor, post-close review",
    )
    payload.setdefault("next_operator_review", "post-close daily review; shadow scenarios are not order authority")
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_field_daily_review(status: FieldDryRunMonitorStatus, output_dir: Path, *, trading_day: date | None = None) -> Path:
    review_day = trading_day or datetime.now().date()
    output = output_dir / "daily-review" / f"{review_day.isoformat()}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Field Dry-Run Daily Review - {review_day.isoformat()}",
        "",
        f"- run_id: `{status.run_id}`",
        f"- mode: `{status.mode}`",
        f"- status: `{status.status}`",
        f"- order_hard_block: `{status.order_hard_block}`",
        f"- ready_for_broker_or_order_transmission: `{status.ready_for_broker_or_order_transmission}`",
        f"- market_snapshot_source: `{status.snapshot_contract.provider}`",
        f"- snapshot_count: `{status.snapshot_contract.snapshot_count}`",
        f"- flags: `{', '.join(status.flags) if status.flags else 'none'}`",
        "",
        "## Scenario Results",
    ]
    if status.scenario_results:
        for result in status.scenario_results:
            lines.append(
                "- "
                f"`{result.scenario_id}` ({result.role}): "
                f"sessions={result.session_count}, "
                f"virtual_orders={result.virtual_order_count}, "
                f"open_positions={result.open_position_count}, "
                f"api_breaches={result.api_rate_limit_breach_count}, "
                f"storage_breaches={result.storage_guardrail_breach_count}"
            )
    else:
        lines.append("- no scenario engine result yet")
    lines.extend(
        [
            "",
            "## Review Boundary",
            "",
            "Primary results may inform no-order field continuation. Shadow results are observation-only and cannot enable broker/order/account actions.",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def write_watchlist_full_report(
    report: DryRunMultiSessionReport,
    output_dir: Path,
    *,
    trading_day: date | None = None,
) -> tuple[Path, Path]:
    review_day = trading_day or datetime.now().date()
    json_path = output_dir / "watchlist" / f"watchlist-full-{review_day.isoformat()}.json"
    md_path = output_dir / "watchlist" / f"watchlist-summary-{review_day.isoformat()}.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    snapshots = [
        snapshot
        for session in report.sessions
        for snapshot in session.scouter_decision_snapshots
    ]
    current_rows = [
        {
            "symbol": snapshot.symbol,
            "timestamp": _timestamp_text(snapshot.timestamp),
            "strategy_group": snapshot.strategy_group,
            "action": snapshot.action,
            "score": snapshot.score,
            "rank": snapshot.rank,
            "passed": snapshot.passed,
            "reason": snapshot.reason,
            "open": snapshot.open,
            "high": snapshot.high,
            "low": snapshot.low,
            "close": snapshot.close,
            "volume": snapshot.volume,
            "traded_value": snapshot.traded_value,
            "bid_ask_ratio": snapshot.bid_ask_ratio,
            "source": snapshot.source,
            "input_flags": snapshot.input_flags,
        }
        for snapshot in snapshots
    ]
    prior_rows = _load_prior_watchlist_rows(json_path)
    rows = _dedupe_watchlist_rows((*prior_rows, *current_rows))
    latest_rows = _latest_watchlist_rows(rows)
    symbol_summaries = _watchlist_symbol_summaries(rows, review_day)
    ranked_latest = _rank_watchlist_rows(_enrich_latest_rows(latest_rows, symbol_summaries))
    triggered = _watchlist_trigger_outcomes(rows)
    reason_counts: dict[str, int] = {}
    for item in rows:
        reason = str(item["reason"] or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    strategy_warmup = _strategy_warmup_diagnostics(rows, review_day)

    payload = {
        "trading_day": review_day,
        "source": "primary-current-seed-1m scouter decision snapshots",
        "scored_symbol_count": len(latest_rows),
        "observation_count": len(rows),
        "first_observed_at": min((_timestamp_text(item["timestamp"]) for item in rows), default=None),
        "last_observed_at": max((_timestamp_text(item["timestamp"]) for item in rows), default=None),
        "passed_count": sum(1 for item in rows if item["passed"]),
        "top_cutoffs": {
            "top10": [str(item["symbol"]) for item in ranked_latest[:10]],
            "top20": [str(item["symbol"]) for item in ranked_latest[:20]],
            "top30": [str(item["symbol"]) for item in ranked_latest[:30]],
            "top50": [str(item["symbol"]) for item in ranked_latest[:50]],
        },
        "reason_counts": reason_counts,
        "strategy_warmup_diagnostics": strategy_warmup,
        "input_flag_counts": _input_flag_counts(rows),
        "symbol_summaries": symbol_summaries,
        "entry_trigger_outcomes": triggered,
        "rows": rows,
    }
    json_path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        f"# Watchlist Summary - {review_day.isoformat()}",
        "",
        f"- scored_symbols_latest: `{len(latest_rows)}`",
        f"- observations: `{len(rows)}`",
        f"- passed_candidates: `{payload['passed_count']}`",
        f"- entry_triggers: `{len(triggered)}`",
        "- top_n_policy: `not selected yet; collect this week and compare top10/top20/top30/top50 on weekend`",
        "",
        "## Latest Top 30 Candidate Proxy",
        "",
        "| Rank | Symbol | Score | Passed | Close | Intraday Change % | Traded Value | Reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, item in enumerate(ranked_latest[:30], start=1):
        lines.append(
            f"| {index} | `{item['symbol']}` | `{item['score']}` | `{item['passed']}` | `{item['close']}` | `{item.get('intraday_change_pct', '0')}` | `{item.get('traded_value', '0')}` | `{item['reason']}` |"
        )
    lines.extend(["", "## Intraday Movement Leaders", "", "| Rank | Symbol | Observations | Last Close | Intraday Change % | Max Favorable % | Max Adverse % | Latest Reason |", "| --- | --- | --- | --- | --- | --- | --- | --- |"])
    for index, item in enumerate(_movement_leaders(symbol_summaries)[:20], start=1):
        lines.append(
            f"| {index} | `{item['symbol']}` | `{item['observation_count']}` | `{item['last_close']}` | `{item['intraday_change_pct']}` | `{item['intraday_max_favorable_pct']}` | `{item['intraday_max_adverse_pct']}` | `{item['latest_reason']}` |"
        )
    lines.extend(["", "## Entry Trigger Outcomes", ""])
    if triggered:
        lines.extend(["| Symbol | Trigger Time | Entry Price | Latest Close | Max Favorable % | Max Adverse % | Would TP | Would SL |", "| --- | --- | --- | --- | --- | --- | --- | --- |"])
        for item in triggered:
            lines.append(
                f"| `{item['symbol']}` | `{item['trigger_time']}` | `{item['entry_price']}` | `{item['latest_close']}` | `{item['max_favorable_pct']}` | `{item['max_adverse_pct']}` | `{item['would_take_profit']}` | `{item['would_stop_loss']}` |"
            )
    else:
        lines.append("- no entry trigger yet")
    lines.extend(["", "## Reason Counts", ""])
    if reason_counts:
        for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{reason}`: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Strategy Warmup Diagnostics", ""])
    lines.append(f"- status: `{strategy_warmup['status']}`")
    lines.append(f"- required_prior_sessions: `{strategy_warmup['required_prior_sessions']}`")
    lines.append(f"- symbols_with_required_prior_sessions: `{strategy_warmup['symbols_with_required_prior_sessions']}`")
    lines.append(f"- max_prior_sessions: `{strategy_warmup['max_prior_sessions']}`")
    if strategy_warmup["flags"]:
        lines.append(f"- flags: `{', '.join(strategy_warmup['flags'])}`")
    else:
        lines.append("- flags: `none`")
    input_flag_counts = payload["input_flag_counts"]
    lines.extend(["", "## Input Quality Flags", ""])
    if input_flag_counts:
        for flag, count in sorted(input_flag_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{flag}`: {count}")
    else:
        lines.append("- none")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def _load_prior_watchlist_rows(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def _dedupe_watchlist_rows(rows: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        row = {**row, "timestamp": _timestamp_text(row.get("timestamp"))}
        key = (
            str(row["timestamp"] or ""),
            str(row.get("symbol") or ""),
            str(row.get("strategy_group") or ""),
        )
        if not key[0] or not key[1]:
            continue
        by_key[key] = row
    return sorted(by_key.values(), key=lambda item: (str(item.get("timestamp")), str(item.get("symbol"))))


def _timestamp_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _latest_watchlist_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest[str(row["symbol"])] = row
    return list(latest.values())


def _enrich_latest_rows(
    rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    summary_by_symbol = {str(item["symbol"]): item for item in summaries}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        summary = summary_by_symbol.get(str(row.get("symbol"))) or {}
        enriched.append(
            {
                **row,
                "observation_count": summary.get("observation_count", 1),
                "change_pct": summary.get("change_pct", Decimal("0")),
                "intraday_change_pct": summary.get("intraday_change_pct", Decimal("0")),
                "max_favorable_pct": summary.get("max_favorable_pct", Decimal("0")),
                "max_adverse_pct": summary.get("max_adverse_pct", Decimal("0")),
            }
        )
    return enriched


def _rank_watchlist_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda item: (
            not bool(item.get("passed")),
            -_to_decimal(item.get("intraday_change_pct")),
            -_to_decimal(item.get("score")),
            -_to_decimal(item.get("traded_value")),
            str(item.get("symbol")),
        ),
    )


def _watchlist_symbol_summaries(rows: list[dict[str, Any]], trading_day: date) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)
    summaries: list[dict[str, Any]] = []
    for symbol, symbol_rows in by_symbol.items():
        ordered = sorted(symbol_rows, key=lambda item: str(item.get("timestamp")))
        first = ordered[0]
        latest = ordered[-1]
        first_close = _to_decimal(first.get("close"))
        latest_close = _to_decimal(latest.get("close"))
        closes = [_to_decimal(item.get("close")) for item in ordered]
        max_close = max(closes) if closes else Decimal("0")
        min_close = min(closes) if closes else Decimal("0")
        intraday_rows = [
            item for item in ordered
            if (timestamp := _parse_watchlist_timestamp(item.get("timestamp"))) is not None
            and timestamp.date() == trading_day
        ]
        intraday_first = intraday_rows[0] if intraday_rows else latest
        intraday_first_close = _to_decimal(intraday_first.get("close"))
        intraday_closes = [_to_decimal(item.get("close")) for item in intraday_rows] or [latest_close]
        intraday_max_close = max(intraday_closes)
        intraday_min_close = min(intraday_closes)
        summaries.append(
            {
                "symbol": symbol,
                "observation_count": len(ordered),
                "first_observed_at": first.get("timestamp"),
                "last_observed_at": latest.get("timestamp"),
                "first_close": first_close,
                "last_close": latest_close,
                "change_pct": _pct(latest_close - first_close, first_close),
                "max_favorable_pct": _pct(max_close - first_close, first_close),
                "max_adverse_pct": _pct(min_close - first_close, first_close),
                "intraday_first_observed_at": intraday_first.get("timestamp"),
                "intraday_first_close": intraday_first_close,
                "intraday_change_pct": _pct(latest_close - intraday_first_close, intraday_first_close),
                "intraday_max_favorable_pct": _pct(intraday_max_close - intraday_first_close, intraday_first_close),
                "intraday_max_adverse_pct": _pct(intraday_min_close - intraday_first_close, intraday_first_close),
                "passed_count": sum(1 for item in ordered if item.get("passed")),
                "first_passed_at": next((item.get("timestamp") for item in ordered if item.get("passed")), None),
                "latest_score": latest.get("score"),
                "latest_reason": latest.get("reason"),
            }
        )
    return sorted(summaries, key=lambda item: (-_to_decimal(item["intraday_change_pct"]), str(item["symbol"])))


def _strategy_warmup_diagnostics(
    rows: list[dict[str, Any]],
    trading_day: date,
    *,
    required_prior_sessions: int = 5,
) -> dict[str, Any]:
    prior_sessions_by_symbol: dict[str, set[date]] = {}
    latest_reasons: dict[str, str] = {}
    passed_count = 0
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        timestamp = _parse_watchlist_timestamp(row.get("timestamp"))
        if timestamp is not None and timestamp.date() < trading_day:
            prior_sessions_by_symbol.setdefault(symbol, set()).add(timestamp.date())
        latest_reasons[symbol] = str(row.get("reason") or "")
        if row.get("passed"):
            passed_count += 1

    prior_counts = {symbol: len(sessions) for symbol, sessions in prior_sessions_by_symbol.items()}
    symbols = set(latest_reasons) | set(prior_counts)
    symbols_with_required = sum(1 for symbol in symbols if prior_counts.get(symbol, 0) >= required_prior_sessions)
    max_prior_sessions = max(prior_counts.values(), default=0)
    universe_filter_latest = sum(1 for reason in latest_reasons.values() if "universe-filter" in reason)
    warming_up_latest = sum(1 for reason in latest_reasons.values() if "warming-up" in reason or "warmup" in reason)
    flags: list[str] = []
    status = "ready"
    if rows and passed_count == 0 and symbols_with_required == 0 and warming_up_latest > 0:
        status = "insufficient"
        flags.append("strategy_warmup_insufficient")
    return {
        "status": status,
        "required_prior_sessions": required_prior_sessions,
        "symbols_with_required_prior_sessions": symbols_with_required,
        "symbol_count": len(symbols),
        "max_prior_sessions": max_prior_sessions,
        "universe_filter_latest_count": universe_filter_latest,
        "warming_up_latest_count": warming_up_latest,
        "flags": flags,
    }


def _parse_watchlist_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _watchlist_trigger_outcomes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)
    outcomes: list[dict[str, Any]] = []
    for symbol, symbol_rows in by_symbol.items():
        ordered = sorted(symbol_rows, key=lambda item: str(item.get("timestamp")))
        trigger_index = next((index for index, item in enumerate(ordered) if item.get("passed")), None)
        if trigger_index is None:
            continue
        trigger = ordered[trigger_index]
        after = ordered[trigger_index:]
        entry = _to_decimal(trigger.get("close"))
        closes = [_to_decimal(item.get("close")) for item in after]
        latest = closes[-1] if closes else entry
        max_favorable = _pct(max(closes) - entry, entry) if closes else Decimal("0")
        max_adverse = _pct(min(closes) - entry, entry) if closes else Decimal("0")
        outcomes.append(
            {
                "symbol": symbol,
                "trigger_time": trigger.get("timestamp"),
                "entry_price": entry,
                "latest_close": latest,
                "max_favorable_pct": max_favorable,
                "max_adverse_pct": max_adverse,
                "would_take_profit": max_favorable >= Decimal("0.8"),
                "would_stop_loss": max_adverse <= Decimal("-1.0"),
            }
        )
    return sorted(outcomes, key=lambda item: str(item["trigger_time"]))


def _input_flag_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        flags = row.get("input_flags") or ()
        if isinstance(flags, str):
            flags = (flags,)
        for flag in flags:
            flag_text = str(flag)
            if not flag_text:
                continue
            counts[flag_text] = counts.get(flag_text, 0) + 1
    return counts


def _movement_leaders(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(summaries, key=lambda item: (-_to_decimal(item["intraday_change_pct"]), str(item["symbol"])))


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return (numerator / denominator * Decimal("100")).quantize(Decimal("0.000001"))


def _scenario_result(
    *,
    scenario_id: str,
    report: DryRunMultiSessionReport,
    path: Path,
) -> FieldDryRunScenarioResult:
    summary = report.summary()
    return FieldDryRunScenarioResult(
        scenario_id=scenario_id,
        role="primary" if scenario_id.startswith("primary-") else "shadow",
        report_path=str(path),
        session_count=int(summary["session_count"]),
        virtual_order_count=(
            int(summary["virtual_order_hard_blocked_count"])
            + int(summary["virtual_order_unblocked_count"])
        ),
        open_position_count=sum(session.summary()["open_position_count"] for session in report.sessions),
        api_rate_limit_breach_count=int(summary["api_rate_limit_breach_count"]),
        storage_guardrail_breach_count=int(summary["storage_guardrail_breach_count"]),
        ready_for_broker_or_order_transmission=False,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value
