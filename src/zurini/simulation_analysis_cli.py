from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from zurini.api_budget import normalize_to_kst
from zurini.bulk_db_import import BulkImportOptions
from zurini.bulk_db_import import run_bulk_historical_import
from zurini.data import db
from zurini.post_close_simulation_runner import build_post_close_simulation_report, diagnose_swing_zero
from zurini.post_close_simulation_runner import validate_replay_payload
from zurini.research_minute_dataset import normalize_research_minute_row
from zurini.universe_recall_audit import SignalObservation, audit_universe_recall


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "research-minute-import":
        return run_research_minute_import_command(args)
    if args.command == "research-minute-retention":
        return run_research_minute_retention_command(args)
    if args.command == "historical-db-import":
        return run_historical_db_import_command(args)
    if args.command == "kis-rolling-integrity":
        return run_kis_rolling_integrity_command(args)
    if args.command == "post-close-simulation-report":
        return run_post_close_simulation_report_command(args)
    if args.command == "universe-recall-audit":
        return run_universe_recall_audit_command(args)
    if args.command == "swing-zero-diagnostics":
        return run_swing_zero_diagnostics_command(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zurini-analysis")
    subparsers = parser.add_subparsers(dest="command")

    research_minute_import = subparsers.add_parser(
        "research-minute-import",
        help="import analysis-only research minute bars into rolling raw/canonical tables",
    )
    research_minute_import.add_argument("--path", type=Path, required=True, help="CSV path with symbol,timestamp,open,high,low,close,volume,value")
    research_minute_import.add_argument("--source", default="legacy-daishin")
    research_minute_import.add_argument("--vendor", default="daishin")
    research_minute_import.add_argument("--source-run-id", default="manual-import")
    research_minute_import.add_argument("--import-batch-id", help="stable batch id; default uses UTC timestamp")
    research_minute_import.add_argument("--schema-version", default="research-minute-v1")
    research_minute_import.add_argument("--retention-days", type=int, default=730)
    research_minute_import.add_argument(
        "--apply-retention",
        action="store_true",
        help="apply rolling retention after import (default is dry-run report only)",
    )
    research_minute_import.add_argument("--output", type=Path, default=Path("reports/phase2/research-minute-import.json"))

    research_minute_retention = subparsers.add_parser(
        "research-minute-retention",
        help="report or apply rolling retention for research minute tables",
    )
    research_minute_retention.add_argument("--retention-days", type=int, default=730)
    research_minute_retention.add_argument("--latest-timestamp", help="override reference timestamp (ISO-8601); default uses DB max timestamp")
    research_minute_retention.add_argument("--apply", action="store_true", help="apply deletes; default is dry-run")
    research_minute_retention.add_argument("--output", type=Path, default=Path("reports/phase2/research-minute-retention.json"))

    historical_import = subparsers.add_parser(
        "historical-db-import",
        help="bulk load analysis-only historical CSV artifacts into research/universe/index DB tables",
    )
    historical_import.add_argument(
        "--include",
        default="minute,daily,index",
        help="comma-separated artifact classes to include: minute,daily,index",
    )
    historical_import.add_argument("--minute-root", type=Path, default=Path("data/raw/daishin/minute-bars"))
    historical_import.add_argument("--daily-root", type=Path, default=Path("data/derived/daishin/daily-bars"))
    historical_import.add_argument("--index-root", type=Path, default=Path("data/raw/daishin/index-bars"))
    historical_import.add_argument("--source-run-id", default="bulk-historical-artifact-import")
    historical_import.add_argument("--import-batch-id", default=None)
    historical_import.add_argument("--schema-version", default="historical-artifact-csv-v1")
    historical_import.add_argument("--batch-size", type=int, default=5_000)
    historical_import.add_argument("--limit-files", type=int, help="select at most this many files per included artifact class")
    historical_import.add_argument("--dry-run", action="store_true", help="count/profile paths and rows without inserting")
    historical_import.add_argument(
        "--apply",
        action="store_true",
        help="insert rows into the local DB; requires --limit-files until the full storage plan is accepted",
    )
    historical_import.add_argument("--output", type=Path, default=Path("reports/phase2/historical-db-import.json"))

    kis_integrity = subparsers.add_parser(
        "kis-rolling-integrity",
        help="fail-closed report for required KIS rolling research-minute DB evidence",
    )
    kis_integrity.add_argument("--min-raw-rows", type=int, default=1_000)
    kis_integrity.add_argument("--min-canonical-rows", type=int, default=1_000)
    kis_integrity.add_argument("--min-symbols", type=int, default=1)
    kis_integrity.add_argument("--min-span-minutes", type=int, default=60)
    kis_integrity.add_argument("--output", type=Path, default=Path("reports/phase2/kis-rolling-integrity.json"))

    post_close_simulation = subparsers.add_parser(
        "post-close-simulation-report",
        help="write analysis-only post-close simulation plan/report scaffold",
    )
    post_close_simulation.add_argument("--filter-off-symbol-list", type=Path, action="append", default=[])
    post_close_simulation.add_argument("--filter-on-symbol-list", type=Path, action="append", default=[])
    post_close_simulation.add_argument("--filter-off-return", default="0")
    post_close_simulation.add_argument("--filter-on-return", default="0")
    post_close_simulation.add_argument(
        "--replay-watchlist",
        type=Path,
        help="analysis-only watchlist-full JSON replay input; not KIS rolling DB evidence",
    )
    post_close_simulation.add_argument("--output", type=Path, default=Path("reports/phase2/post-close-simulation-report.json"))

    universe_recall = subparsers.add_parser(
        "universe-recall-audit",
        help="write analysis-only universe recall audit report from universe/signal files",
    )
    universe_recall.add_argument("--universe-id", required=True)
    universe_recall.add_argument("--universe-symbol-list", type=Path, action="append", default=[])
    universe_recall.add_argument("--signal-observations", type=Path, required=True, help="CSV/JSON file with symbol,timestamp,candidate_id[,score]")
    universe_recall.add_argument("--output", type=Path, default=Path("reports/phase2/universe-recall-audit.json"))

    swing_zero = subparsers.add_parser(
        "swing-zero-diagnostics",
        help="write analysis-only swing-zero diagnostic report from supplied counts/reasons",
    )
    swing_zero.add_argument("--control-count", type=int, required=True)
    swing_zero.add_argument("--rebound-count", type=int, required=True)
    swing_zero.add_argument("--relative-strength-count", type=int, required=True)
    swing_zero.add_argument("--rejection-reasons", type=Path, help="JSON object or list with reason/count fields")
    swing_zero.add_argument("--output", type=Path, default=Path("reports/phase2/swing-zero-diagnostics.json"))

    return parser


def run_research_minute_import_command(args: argparse.Namespace) -> int:
    rows = _load_research_minute_rows_from_csv(
        args.path,
        source=args.source,
        vendor=args.vendor,
        source_run_id=args.source_run_id,
        import_batch_id=args.import_batch_id or f"research-minute-import-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        schema_version=args.schema_version,
    )
    db.apply_schema()
    result = db.insert_research_minute_rows(rows)
    retention_report = None
    if args.apply_retention:
        retention_report = db.apply_research_minute_rolling_retention(
            retention_days=args.retention_days,
            dry_run=False,
        )
    payload = {
        "status": "ok",
        "mode": "analysis-only-no-order",
        "command": "research-minute-import",
        "input_path": str(args.path),
        "inserted_raw_rows": result.inserted_raw_rows,
        "canonical_rows_refreshed": result.canonical_rows_refreshed,
        "distinct_key_count": result.distinct_key_count,
        "duplicate_input_rows": result.duplicate_input_rows,
        "retention": _retention_report_payload(retention_report),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status={payload['status']}")
    print(f"inserted_raw_rows={result.inserted_raw_rows}")
    print(f"canonical_rows_refreshed={result.canonical_rows_refreshed}")
    print(f"report={args.output}")
    return 0


def run_research_minute_retention_command(args: argparse.Namespace) -> int:
    db.apply_schema()
    latest = _parse_cli_datetime(args.latest_timestamp) if args.latest_timestamp else None
    report = db.apply_research_minute_rolling_retention(
        latest_timestamp=latest,
        retention_days=args.retention_days,
        dry_run=not args.apply,
    )
    payload = {
        "status": "ok",
        "mode": "analysis-only-no-order",
        "command": "research-minute-retention",
        "retention": _retention_report_payload(report),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status={payload['status']}")
    print(f"dry_run={str(report.dry_run).lower()}")
    print(f"raw_rows_eligible={report.raw_rows_eligible}")
    print(f"raw_rows_deleted={report.raw_rows_deleted}")
    print(f"report={args.output}")
    return 0


def run_historical_db_import_command(args: argparse.Namespace) -> int:
    if args.apply and args.dry_run:
        raise ValueError("historical-db-import cannot combine --apply and --dry-run")
    if args.apply and args.limit_files is None:
        raise ValueError("historical-db-import --apply requires --limit-files until the full storage plan is accepted")
    dry_run = not args.apply
    import_batch_id = args.import_batch_id or f"historical-db-import-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    payload = {
        "command": "historical-db-import",
        **run_bulk_historical_import(
            BulkImportOptions(
                minute_root=args.minute_root,
                daily_root=args.daily_root,
                index_root=args.index_root,
                include=tuple(item.strip() for item in args.include.split(",")),
                dry_run=dry_run,
                limit_files=args.limit_files,
                source_run_id=args.source_run_id,
                import_batch_id=import_batch_id,
                schema_version=args.schema_version,
                batch_size=args.batch_size,
            )
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"status={payload['status']}")
    print(f"dry_run={str(payload['dry_run']).lower()}")
    print(f"limit_files={payload['limit_files']}")
    print(f"rows_read={payload['totals']['rows_read']}")
    print(f"rows_inserted_or_updated={payload['totals']['rows_inserted_or_updated']}")
    print(f"report={args.output}")
    return 0


def run_kis_rolling_integrity_command(args: argparse.Namespace) -> int:
    try:
        db.apply_schema()
        report = collect_kis_rolling_integrity(
            min_raw_rows=args.min_raw_rows,
            min_canonical_rows=args.min_canonical_rows,
            min_symbols=args.min_symbols,
            min_span_minutes=args.min_span_minutes,
        )
    except Exception as exc:
        report = {
            "status": "blocked",
            "blockers": ["db_connection_or_schema_failed"],
            "thresholds": {
                "min_raw_rows": args.min_raw_rows,
                "min_canonical_rows": args.min_canonical_rows,
                "min_symbols": args.min_symbols,
                "min_span_minutes": args.min_span_minutes,
            },
            "raw": _empty_research_minute_summary("research_minute_raw"),
            "canonical": _empty_research_minute_summary("research_minute_canonical"),
            "error": str(exc),
            "data_contract": (
                "required rolling KIS minute data could not be verified; fail closed and do not "
                "substitute replay artifacts or cached assumptions"
            ),
        }
    payload = {
        "status": report["status"],
        "mode": "analysis-only-no-order",
        "command": "kis-rolling-integrity",
        "report": report,
        "promotion_boundary": "blocks rolling KIS simulation evidence when status is blocked; no broker/order/account/balance behavior",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"status={payload['status']}")
    print(f"raw_rows={report['raw']['row_count']}")
    print(f"canonical_rows={report['canonical']['row_count']}")
    print(f"kis_raw_rows={report['raw']['kis_row_count']}")
    print(f"kis_canonical_rows={report['canonical']['kis_row_count']}")
    print(f"report={args.output}")
    return 0 if payload["status"] == "passed" else 1


def run_post_close_simulation_report_command(args: argparse.Namespace) -> int:
    filter_off_symbols = set(_read_symbol_lists(args.filter_off_symbol_list))
    filter_on_symbols = set(_read_symbol_lists(args.filter_on_symbol_list))
    has_filter_inputs = bool(filter_off_symbols or filter_on_symbols)
    replay_payload = _load_json_object(args.replay_watchlist) if args.replay_watchlist else None
    if replay_payload is not None:
        validate_replay_payload(replay_payload)
    report = build_post_close_simulation_report(
        filter_off_symbols=filter_off_symbols if has_filter_inputs else None,
        filter_on_symbols=filter_on_symbols if has_filter_inputs else None,
        filter_off_return=_decimal(args.filter_off_return),
        filter_on_return=_decimal(args.filter_on_return),
        replay_payload=replay_payload,
        replay_path=str(args.replay_watchlist) if args.replay_watchlist else None,
    )
    payload = {
        "status": "ok",
        "mode": "analysis-only-no-order",
        "command": "post-close-simulation-report",
        **report.as_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status={payload['status']}")
    print(f"day_candidate_count={len(report.plan.day_recipes)}")
    print(f"swing_candidate_count={len(report.plan.swing_candidates)}")
    print(f"model_result_count={len(report.model_results)}")
    print(f"report={args.output}")
    return 0


def run_universe_recall_audit_command(args: argparse.Namespace) -> int:
    universe_symbols = set(_read_symbol_lists(args.universe_symbol_list))
    observations = _load_signal_observations(args.signal_observations)
    report = audit_universe_recall(
        universe_id=args.universe_id,
        universe_symbols=universe_symbols,
        observations=observations,
    )
    payload = {
        "status": "ok",
        "mode": "analysis-only-no-order",
        "command": "universe-recall-audit",
        "report": report.as_dict(),
        "promotion_boundary": "post-close/weekend audit only; no live market-wide scanner behavior",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status={payload['status']}")
    print(f"signal_count={report.signal_count}")
    print(f"missed_count={report.missed_count}")
    print(f"report={args.output}")
    return 0


def run_swing_zero_diagnostics_command(args: argparse.Namespace) -> int:
    rejection_reasons = _load_rejection_reason_counts(args.rejection_reasons) if args.rejection_reasons else {}
    diagnostics = diagnose_swing_zero(
        control_count=args.control_count,
        rebound_count=args.rebound_count,
        relative_strength_count=args.relative_strength_count,
        rejection_reasons=rejection_reasons,
    )
    payload = {
        "status": "ok",
        "mode": "analysis-only-no-order",
        "command": "swing-zero-diagnostics",
        "diagnostics": diagnostics.as_dict(),
        "promotion_boundary": "analysis report only; no live strategy/entry wiring",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status={payload['status']}")
    print(f"swing_zero_status={diagnostics.status()}")
    print(f"report={args.output}")
    return 0


def _read_symbol_lists(paths: list[Path]) -> list[str]:
    symbols: list[str] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            symbol = line.strip()
            if symbol and not symbol.startswith("#"):
                symbols.append(symbol)
    return symbols


def collect_kis_rolling_integrity(
    *,
    min_raw_rows: int,
    min_canonical_rows: int,
    min_symbols: int,
    min_span_minutes: int,
) -> dict[str, object]:
    raw = _research_minute_table_summary("research_minute_raw")
    canonical = _research_minute_table_summary("research_minute_canonical")
    blockers: list[str] = []
    if raw["kis_row_count"] < min_raw_rows:
        blockers.append("raw_kis_rows_below_minimum")
    if canonical["kis_row_count"] < min_canonical_rows:
        blockers.append("canonical_kis_rows_below_minimum")
    if raw["kis_row_count"] == 0:
        blockers.append("raw_kis_rows_missing")
    if canonical["kis_row_count"] == 0:
        blockers.append("canonical_kis_rows_missing")
    if canonical["kis_symbol_count"] < min_symbols:
        blockers.append("canonical_kis_symbols_below_minimum")
    if canonical["kis_span_minutes"] < min_span_minutes:
        blockers.append("canonical_kis_time_range_below_minimum")
    return {
        "status": "passed" if not blockers else "blocked",
        "blockers": blockers,
        "thresholds": {
            "min_raw_rows": min_raw_rows,
            "min_canonical_rows": min_canonical_rows,
            "min_symbols": min_symbols,
            "min_span_minutes": min_span_minutes,
        },
        "raw": raw,
        "canonical": canonical,
        "data_contract": (
            "required rolling KIS minute data must be present in research_minute_raw and "
            "research_minute_canonical with source/vendor evidence; replay artifacts are excluded"
        ),
    }


def _research_minute_table_summary(table: str) -> dict[str, object]:
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*),
                    COUNT(DISTINCT symbol),
                    MIN(timestamp),
                    MAX(timestamp),
                    COUNT(*) FILTER (WHERE lower(vendor) = 'kis' OR lower(source) LIKE '%kis%'),
                    COUNT(DISTINCT symbol) FILTER (WHERE lower(vendor) = 'kis' OR lower(source) LIKE '%kis%'),
                    MIN(timestamp) FILTER (WHERE lower(vendor) = 'kis' OR lower(source) LIKE '%kis%'),
                    MAX(timestamp) FILTER (WHERE lower(vendor) = 'kis' OR lower(source) LIKE '%kis%')
                FROM {table}
                """
            )
            row = cur.fetchone()
            cur.execute(
                f"""
                SELECT vendor, source, COUNT(*), MIN(timestamp), MAX(timestamp)
                FROM {table}
                GROUP BY vendor, source
                ORDER BY vendor, source
                """
            )
            source_rows = cur.fetchall()
    first = row[2]
    last = row[3]
    kis_first = row[6]
    kis_last = row[7]
    span_minutes = int((last - first).total_seconds() // 60) if first and last else 0
    kis_span_minutes = int((kis_last - kis_first).total_seconds() // 60) if kis_first and kis_last else 0
    return {
        "table": table,
        "row_count": int(row[0]),
        "symbol_count": int(row[1]),
        "first_timestamp": first.isoformat() if first else None,
        "last_timestamp": last.isoformat() if last else None,
        "span_minutes": span_minutes,
        "kis_row_count": int(row[4]),
        "kis_symbol_count": int(row[5]),
        "kis_first_timestamp": kis_first.isoformat() if kis_first else None,
        "kis_last_timestamp": kis_last.isoformat() if kis_last else None,
        "kis_span_minutes": kis_span_minutes,
        "sources": [
            {
                "vendor": vendor,
                "source": source,
                "row_count": int(count),
                "first_timestamp": first_ts.isoformat() if first_ts else None,
                "last_timestamp": last_ts.isoformat() if last_ts else None,
            }
            for vendor, source, count, first_ts, last_ts in source_rows
        ],
    }


def _empty_research_minute_summary(table: str) -> dict[str, object]:
    return {
        "table": table,
        "row_count": 0,
        "symbol_count": 0,
        "first_timestamp": None,
        "last_timestamp": None,
        "span_minutes": 0,
        "kis_row_count": 0,
        "kis_symbol_count": 0,
        "kis_first_timestamp": None,
        "kis_last_timestamp": None,
        "kis_span_minutes": 0,
        "sources": [],
    }


def _load_research_minute_rows_from_csv(
    path: Path,
    *,
    source: str,
    vendor: str,
    source_run_id: str,
    import_batch_id: str,
    schema_version: str,
) -> list:
    required_columns = {"symbol", "timestamp", "open", "high", "low", "close"}
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("research minute CSV must include a header")
        missing = sorted(required_columns - set(reader.fieldnames))
        if missing:
            raise ValueError(f"research minute CSV missing columns: {','.join(missing)}")
        for index, item in enumerate(reader, start=2):
            symbol = str(item.get("symbol") or "").strip()
            if not symbol:
                raise ValueError(f"research minute CSV row {index} has empty symbol")
            timestamp_text = str(item.get("timestamp") or "").strip()
            if not timestamp_text:
                raise ValueError(f"research minute CSV row {index} has empty timestamp")
            timestamp = _parse_cli_datetime(timestamp_text)
            volume_text = str(item.get("volume") or "").strip()
            value_text = str(item.get("value") or "").strip()
            input_flags_text = str(item.get("input_flags") or "").strip()
            rows.append(
                normalize_research_minute_row(
                    symbol=symbol,
                    timestamp=timestamp,
                    open_price=_decimal(item["open"]),
                    high=_decimal(item["high"]),
                    low=_decimal(item["low"]),
                    close=_decimal(item["close"]),
                    volume=int(Decimal(volume_text)) if volume_text else None,
                    value=_decimal(value_text) if value_text else None,
                    bid_ask_ratio=_optional_decimal(item.get("bid_ask_ratio")),
                    traded_value=_optional_decimal(item.get("traded_value") or item.get("value")),
                    action=_optional_text(item.get("action")),
                    passed=_optional_bool(item.get("passed")),
                    rank=_optional_int(item.get("rank")),
                    reason=_optional_text(item.get("reason")),
                    score=_optional_decimal(item.get("score")),
                    strategy_group=_optional_text(item.get("strategy_group")),
                    input_flags=tuple(flag for flag in input_flags_text.split("|") if flag),
                    data_origin=_optional_text(item.get("data_origin")) or (
                        "legacy-minute-backfill" if source.startswith("legacy") else "field-observation"
                    ),
                    raw_payload={key: value for key, value in item.items() if value not in (None, "")},
                    source=source,
                    vendor=vendor,
                    source_run_id=source_run_id,
                    import_batch_id=import_batch_id,
                    schema_version=schema_version,
                )
            )
    if not rows:
        raise ValueError("research minute CSV contained no rows")
    return rows


def _retention_report_payload(report) -> dict[str, object] | None:
    if report is None:
        return None
    return {
        "reference_timestamp": report.reference_timestamp.isoformat(),
        "cutoff_timestamp": report.cutoff_timestamp.isoformat(),
        "retention_days": report.retention_days,
        "dry_run": report.dry_run,
        "canonical_rows_eligible": report.canonical_rows_eligible,
        "raw_rows_eligible": report.raw_rows_eligible,
        "canonical_rows_deleted": report.canonical_rows_deleted,
        "raw_rows_deleted": report.raw_rows_deleted,
    }


def _load_signal_observations(path: Path) -> list[SignalObservation]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _load_signal_observations_csv(path)
    if suffix == ".json":
        return _load_signal_observations_json(path)
    raise ValueError("signal observations file must be .csv or .json")


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("replay watchlist JSON must be an object")
    return payload


def _load_signal_observations_csv(path: Path) -> list[SignalObservation]:
    observations: list[SignalObservation] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("signal observations CSV must include a header")
        required = {"symbol", "timestamp", "candidate_id"}
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ValueError(f"signal observations CSV missing columns: {','.join(missing)}")
        for index, item in enumerate(reader, start=2):
            symbol = str(item.get("symbol") or "").strip()
            timestamp = str(item.get("timestamp") or "").strip()
            candidate_id = str(item.get("candidate_id") or "").strip()
            if not symbol or not timestamp or not candidate_id:
                raise ValueError(f"signal observations CSV row {index} has empty required fields")
            score = _decimal(item.get("score") or "0")
            observations.append(
                SignalObservation(
                    symbol=symbol,
                    timestamp=_parse_cli_datetime(timestamp),
                    candidate_id=candidate_id,
                    score=score,
                )
            )
    return observations


def _load_signal_observations_json(path: Path) -> list[SignalObservation]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("observations") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("signal observations JSON must be a list or an object with observations[]")
    observations: list[SignalObservation] = []
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"signal observations JSON row {index} must be an object")
        symbol = str(item.get("symbol") or "").strip()
        timestamp = str(item.get("timestamp") or "").strip()
        candidate_id = str(item.get("candidate_id") or "").strip()
        if not symbol or not timestamp or not candidate_id:
            raise ValueError(f"signal observations JSON row {index} has empty required fields")
        observations.append(
            SignalObservation(
                symbol=symbol,
                timestamp=_parse_cli_datetime(timestamp),
                candidate_id=candidate_id,
                score=_decimal(item.get("score") or "0"),
            )
        )
    return observations


def _load_rejection_reason_counts(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return {str(key): int(value) for key, value in payload.items()}
    if isinstance(payload, list):
        counts: dict[str, int] = {}
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"rejection reasons row {index} must be an object")
            reason = str(item.get("reason") or "").strip()
            if not reason:
                raise ValueError(f"rejection reasons row {index} has empty reason")
            count = int(item.get("count") or 0)
            counts[reason] = counts.get(reason, 0) + count
        return counts
    raise ValueError("rejection reasons JSON must be an object or list")


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(Decimal(str(value)))


def _optional_bool(value: object) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_cli_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return normalize_to_kst(parsed)


if __name__ == "__main__":
    raise SystemExit(main())
