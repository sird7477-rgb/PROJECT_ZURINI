from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from zurini.data import db
from zurini.simulation_analysis_cli import main


KST = ZoneInfo("Asia/Seoul")


def test_research_minute_import_command_writes_analysis_only_report(tmp_path, monkeypatch) -> None:
    csv_path = tmp_path / "minute.csv"
    csv_path.write_text(
        "symbol,timestamp,open,high,low,close,volume,value\n"
        "A005930,2026-05-15T09:01:00+09:00,100,101,99,100,1000,100000\n"
        "A005930,2026-05-15T09:02:00+09:00,101,102,100,101,,\n",
        encoding="utf-8",
    )
    output = tmp_path / "import-report.json"

    monkeypatch.setattr("zurini.simulation_analysis_cli.db.apply_schema", lambda: None)
    monkeypatch.setattr(
        "zurini.simulation_analysis_cli.db.insert_research_minute_rows",
        lambda rows: db.ResearchMinuteImportResult(
            inserted_raw_rows=len(rows),
            canonical_rows_refreshed=2,
            distinct_key_count=2,
            duplicate_input_rows=0,
        ),
    )
    monkeypatch.setattr(
        "zurini.simulation_analysis_cli.db.apply_research_minute_rolling_retention",
        lambda **_: db.ResearchMinuteRetentionReport(
            reference_timestamp=datetime(2026, 5, 15, 9, 2, tzinfo=KST),
            cutoff_timestamp=datetime(2024, 5, 16, 9, 2, tzinfo=KST),
            retention_days=730,
            dry_run=False,
            canonical_rows_eligible=10,
            raw_rows_eligible=12,
            canonical_rows_deleted=10,
            raw_rows_deleted=12,
        ),
    )

    exit_code = main(
        [
            "research-minute-import",
            "--path",
            str(csv_path),
            "--apply-retention",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "analysis-only-no-order"
    assert payload["inserted_raw_rows"] == 2
    assert payload["retention"]["dry_run"] is False


def test_research_minute_import_accepts_missing_optional_volume_value_columns(tmp_path, monkeypatch) -> None:
    csv_path = tmp_path / "minute.csv"
    csv_path.write_text(
        "symbol,timestamp,open,high,low,close\n"
        "A005930,2026-05-15T09:01:00+09:00,100,101,99,100\n",
        encoding="utf-8",
    )
    output = tmp_path / "import-report.json"
    captured: dict[str, object] = {}

    monkeypatch.setattr("zurini.simulation_analysis_cli.db.apply_schema", lambda: None)

    def _fake_insert(rows):
        captured["rows"] = rows
        return db.ResearchMinuteImportResult(
            inserted_raw_rows=len(rows),
            canonical_rows_refreshed=1,
            distinct_key_count=1,
            duplicate_input_rows=0,
        )

    monkeypatch.setattr("zurini.simulation_analysis_cli.db.insert_research_minute_rows", _fake_insert)

    exit_code = main(
        [
            "research-minute-import",
            "--path",
            str(csv_path),
            "--output",
            str(output),
        ]
    )

    rows = captured["rows"]
    assert exit_code == 0
    assert rows[0].volume is None
    assert rows[0].value is None
    assert rows[0].quality_flags == (
        "volume_missing",
        "value_missing",
        "bid_ask_ratio_missing",
        "legacy_operating_field_missing",
    )


def test_research_minute_retention_command_defaults_to_dry_run(tmp_path, monkeypatch) -> None:
    output = tmp_path / "retention-report.json"
    calls: dict[str, object] = {}

    monkeypatch.setattr("zurini.simulation_analysis_cli.db.apply_schema", lambda: None)

    def _fake_retention(**kwargs):
        calls.update(kwargs)
        return db.ResearchMinuteRetentionReport(
            reference_timestamp=datetime(2026, 5, 15, 9, 2, tzinfo=KST),
            cutoff_timestamp=datetime(2024, 5, 16, 9, 2, tzinfo=KST),
            retention_days=kwargs["retention_days"],
            dry_run=kwargs["dry_run"],
            canonical_rows_eligible=3,
            raw_rows_eligible=4,
            canonical_rows_deleted=0,
            raw_rows_deleted=0,
        )

    monkeypatch.setattr("zurini.simulation_analysis_cli.db.apply_research_minute_rolling_retention", _fake_retention)

    exit_code = main(
        [
            "research-minute-retention",
            "--retention-days",
            "400",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert calls["dry_run"] is True
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["retention"]["retention_days"] == 400
    assert payload["retention"]["raw_rows_deleted"] == 0


def test_kis_rolling_integrity_command_fails_closed_when_rows_are_missing(tmp_path, monkeypatch) -> None:
    output = tmp_path / "kis-integrity.json"

    monkeypatch.setattr("zurini.simulation_analysis_cli.db.apply_schema", lambda: None)
    monkeypatch.setattr(
        "zurini.simulation_analysis_cli.collect_kis_rolling_integrity",
        lambda **_: {
            "status": "blocked",
            "blockers": ["raw_rows_below_minimum", "canonical_kis_rows_missing"],
            "thresholds": {
                "min_raw_rows": 1000,
                "min_canonical_rows": 1000,
                "min_symbols": 1,
                "min_span_minutes": 60,
            },
            "raw": {
                "row_count": 1,
                "symbol_count": 1,
                "first_timestamp": "2026-05-15T10:00:00+09:00",
                "last_timestamp": "2026-05-15T10:00:00+09:00",
                "span_minutes": 0,
                "kis_row_count": 1,
                "kis_symbol_count": 1,
                "kis_first_timestamp": "2026-05-15T10:00:00+09:00",
                "kis_last_timestamp": "2026-05-15T10:00:00+09:00",
                "kis_span_minutes": 0,
                "sources": [{"vendor": "kis", "source": "kis-minute-poll", "row_count": 1}],
            },
            "canonical": {
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
            },
            "data_contract": "required rolling KIS minute data must be present",
        },
    )

    exit_code = main(["kis-rolling-integrity", "--output", str(output)])

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["report"]["raw"]["kis_row_count"] == 1
    assert "canonical_kis_rows_missing" in payload["report"]["blockers"]


def test_post_close_simulation_report_command_writes_filter_gap(tmp_path) -> None:
    filter_off = tmp_path / "off.txt"
    filter_on = tmp_path / "on.txt"
    filter_off.write_text("A005930\nA000660\n", encoding="utf-8")
    filter_on.write_text("A005930\n", encoding="utf-8")
    output = tmp_path / "post-close.json"

    exit_code = main(
        [
            "post-close-simulation-report",
            "--filter-off-symbol-list",
            str(filter_off),
            "--filter-on-symbol-list",
            str(filter_on),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "analysis-only-no-order"
    assert payload["plan"]["day_recipes"][0]["candidate_id"] == "day-immediate-baseline"
    assert payload["filter_comparison"]["blocked_symbols"] == ["A000660"]


def test_post_close_simulation_report_command_writes_model_results_from_replay(tmp_path) -> None:
    replay = tmp_path / "watchlist-full.json"
    replay.write_text(
        json.dumps(
            {
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
                    }
                ],
                "entry_trigger_outcomes": [
                    {
                        "symbol": "A005930",
                        "entry_price": "100",
                        "latest_close": "104",
                        "max_adverse_pct": "-1.2",
                        "max_favorable_pct": "4.0",
                    }
                ],
                "symbol_summaries": [],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "post-close.json"

    exit_code = main(
        [
            "post-close-simulation-report",
            "--replay-watchlist",
            str(replay),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["replay_input"]["mode"] == "analysis-only-replay"
    assert "not KIS rolling DB evidence" in payload["replay_input"]["warning"]
    assert len(payload["model_results"]) == 11
    by_id = {item["candidate_id"]: item for item in payload["model_results"]}
    assert by_id["day-immediate-baseline"]["accepted_count"] == 1
    assert by_id["day-pullback-reentry-010"]["accepted_count"] == 1
    assert by_id["day-market-defense-filtered"]["accepted_count"] == 0


def test_post_close_simulation_report_command_rejects_invalid_replay_payload(tmp_path) -> None:
    replay = tmp_path / "bad-watchlist.json"
    replay.write_text(json.dumps({"rows": {}}), encoding="utf-8")
    output = tmp_path / "post-close.json"

    try:
        main(
            [
                "post-close-simulation-report",
                "--replay-watchlist",
                str(replay),
                "--output",
                str(output),
            ]
        )
    except ValueError as exc:
        assert "rows[]" in str(exc)
    else:
        raise AssertionError("invalid replay payload should fail closed")


def test_universe_recall_audit_command_reads_csv_observations(tmp_path) -> None:
    universe = tmp_path / "universe.txt"
    universe.write_text("A005930\nA000660\n", encoding="utf-8")
    observations = tmp_path / "signals.csv"
    observations.write_text(
        "symbol,timestamp,candidate_id,score\n"
        "A005930,2026-05-15T10:00:00+09:00,day-pullback-reentry-010,1.2\n"
        "A035420,2026-05-15T10:01:00+09:00,day-pullback-reentry-010,0.7\n",
        encoding="utf-8",
    )
    output = tmp_path / "recall.json"

    exit_code = main(
        [
            "universe-recall-audit",
            "--universe-id",
            "U80-current",
            "--universe-symbol-list",
            str(universe),
            "--signal-observations",
            str(observations),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report"]["captured_symbols"] == ["A005930"]
    assert payload["report"]["missed_symbols"] == ["A035420"]
    assert payload["mode"] == "analysis-only-no-order"


def test_swing_zero_diagnostics_command_writes_reason_counts(tmp_path) -> None:
    reasons = tmp_path / "reasons.json"
    reasons.write_text(json.dumps({"entry-window": 4, "index-trend": 2}), encoding="utf-8")
    output = tmp_path / "swing-zero.json"

    exit_code = main(
        [
            "swing-zero-diagnostics",
            "--control-count",
            "0",
            "--rebound-count",
            "1",
            "--relative-strength-count",
            "0",
            "--rejection-reasons",
            str(reasons),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["diagnostics"]["status"] == "simulation-only-swing-candidates-found"
    assert payload["diagnostics"]["rejection_reasons"] == {"entry-window": 4, "index-trend": 2}
