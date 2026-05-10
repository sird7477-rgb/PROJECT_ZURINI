from __future__ import annotations

import json

from zurini.cli import main
from zurini.observability import append_event_jsonl, build_event, redact_message, redact_payload


def test_observability_redacts_secret_like_keys(tmp_path):
    event = build_event(
        run_id="run-1",
        event_type="api-smoke",
        component="kis",
        status="planned",
        payload={"api_key": "secret-value", "nested": {"token": "abc", "safe": "visible"}},
    )
    path = tmp_path / "events.jsonl"
    append_event_jsonl(path, event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["payload"]["api_key"] == "<redacted>"
    assert payload["payload"]["nested"]["token"] == "<redacted>"
    assert payload["payload"]["nested"]["safe"] == "visible"
    assert redact_payload(["x", {"password": "pw"}]) == ["x", {"password": "<redacted>"}]


def test_observability_redacts_secret_like_message_values(tmp_path):
    event = build_event(
        run_id="run-1",
        event_type="api-smoke",
        component="telegram",
        status="failed",
        message="token=abc123 비밀번호: qwer safe",
    )
    path = tmp_path / "events.jsonl"
    append_event_jsonl(path, event)

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["message"] == "token=<redacted> 비밀번호: <redacted> safe"
    assert redact_message("api_key: value") == "api_key: <redacted>"


def test_ops_status_cli_checks_report_artifacts(tmp_path):
    report = tmp_path / "report.json"
    report.write_text('{"ok": true}\n', encoding="utf-8")
    output = tmp_path / "status.json"

    exit_code = main(["ops-status", "--report", str(report), "--output", str(output)])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["checked_reports"][0]["status"] == "ok"


def test_ops_status_cli_rejects_missing_report(tmp_path):
    output = tmp_path / "status.json"

    exit_code = main(["ops-status", "--report", str(tmp_path / "missing.json"), "--output", str(output)])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["status"] == "review-required"
    assert payload["checked_reports"][0]["status"] == "missing"


def test_record_event_cli_writes_redacted_jsonl_event(tmp_path):
    output = tmp_path / "events.jsonl"

    exit_code = main(
        [
            "record-event",
            "--run-id",
            "run-1",
            "--event-type",
            "coverage",
            "--component",
            "phase2",
            "--status",
            "started",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["component"] == "phase2"


def test_chaos_plan_cli_stays_fixture_only(tmp_path):
    output = tmp_path / "chaos-plan.json"

    exit_code = main(["chaos-plan", "--output", str(output)])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["execution_mode"] == "manual-local-fixture"
    assert all("no broker" in scenario["safety_boundary"] or "synthetic" in scenario["safety_boundary"] for scenario in payload["scenarios"])
