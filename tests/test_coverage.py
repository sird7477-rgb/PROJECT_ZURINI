from __future__ import annotations

import json
from datetime import time
from pathlib import Path

from zurini.cli import main
from zurini.data.calendar import load_trading_calendar
from zurini.data.coverage import profile_csv_coverage


def _write_csv(path: Path, rows: list[tuple[str, str, str, str, str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,time,open,high,low,close,volume"]
    lines.extend(",".join(row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _short_rows(*, skip_time: str | None = None) -> list[tuple[str, str, str, str, str, str, str]]:
    return [
        ("20260504", minute, "100", "101", "99", "100", "0")
        for minute in ["901", "902", "903"]
        if minute != skip_time
    ]


def _month_short_rows(yyyymm: str) -> list[tuple[str, str, str, str, str, str, str]]:
    calendar = load_trading_calendar()
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    for value_date in calendar.trading_days_in_month(yyyymm):
        rows.extend(
            (value_date.strftime("%Y%m%d"), minute, "100", "101", "99", "100", "0")
            for minute in ["901", "902", "903"]
        )
    return rows


def _month_minute_rows(yyyymm: str) -> list[tuple[str, str, str, str, str, str, str]]:
    calendar = load_trading_calendar()
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    for value_date in calendar.trading_days_in_month(yyyymm):
        rows.extend(
            _minute_rows(value_date.strftime("%Y%m%d"), start_hour=9, start_minute=1, end_hour=15, end_minute=30)
        )
    return rows


def _minute_rows(date: str, *, start_hour: int, start_minute: int, end_hour: int, end_minute: int):
    rows = []
    hour = start_hour
    minute = start_minute
    while hour < end_hour or (hour == end_hour and minute <= end_minute):
        rows.append((date, f"{hour}{minute:02d}", "100", "101", "99", "100", "0"))
        minute += 1
        if minute == 60:
            hour += 1
            minute = 0
    return rows


def test_index_grid_coverage_accepts_complete_observed_session(tmp_path):
    path = tmp_path / "index-bars" / "202605" / "U001.csv"
    _write_csv(path, _month_short_rows("202605"))

    summary = profile_csv_coverage(
        path,
        class_mode="index-grid",
        session_start=time(9, 1),
        session_end=time(9, 3),
        require_day_set=True,
    )

    assert summary.acceptance_status == "accepted"
    assert summary.calendar_version == "krx-korean-equity-v1"
    assert summary.calendar_certified is False
    assert summary.day_set_evaluated is True
    assert summary.day_set_complete is True
    assert summary.promotable_calendar is False
    assert summary.expected_session_minutes == summary.expected_trading_days * 3
    assert summary.observed_minutes == summary.expected_trading_days * 3
    assert summary.missing_minutes_count == 0


def test_index_grid_coverage_rejects_missing_middle_minute(tmp_path):
    path = tmp_path / "index-bars" / "202605" / "U001.csv"
    _write_csv(path, _short_rows(skip_time="902"))

    summary = profile_csv_coverage(path, class_mode="index-grid", session_start=time(9, 1), session_end=time(9, 3))

    assert summary.acceptance_status == "review-required"
    assert summary.missing_minutes_count == 1
    assert summary.longest_missing_run == 1


def test_index_grid_coverage_allows_known_special_session_window(tmp_path):
    path = tmp_path / "index-bars" / "202511" / "U001.csv"
    _write_csv(path, _minute_rows("20251113", start_hour=10, start_minute=1, end_hour=16, end_minute=30))

    summary = profile_csv_coverage(path, class_mode="index-grid")

    assert summary.acceptance_status == "review-required"
    assert summary.day_set_evaluated is False
    assert summary.day_set_complete is False
    assert summary.out_of_session_count == 0


def test_index_grid_day_set_rejects_missing_whole_trading_days(tmp_path):
    path = tmp_path / "index-bars" / "202605" / "U001.csv"
    _write_csv(path, _short_rows())

    summary = profile_csv_coverage(
        path,
        class_mode="index-grid",
        session_start=time(9, 1),
        session_end=time(9, 3),
        require_day_set=True,
    )

    assert summary.acceptance_status == "review-required"
    assert summary.day_set_complete is False
    assert "2026-05-06" in summary.missing_trading_days
    assert "2026-05-05" not in summary.missing_trading_days
    assert summary.missing_minutes_count >= 3


def test_index_grid_day_set_rejects_unexpected_non_trading_days(tmp_path):
    path = tmp_path / "index-bars" / "202605" / "U001.csv"
    _write_csv(
        path,
        _short_rows()
        + [
            ("20260505", "901", "100", "101", "99", "100", "0"),
            ("20260505", "902", "100", "101", "99", "100", "0"),
            ("20260505", "903", "100", "101", "99", "100", "0"),
        ],
    )

    summary = profile_csv_coverage(
        path,
        class_mode="index-grid",
        session_start=time(9, 1),
        session_end=time(9, 3),
        require_day_set=True,
    )

    assert summary.acceptance_status == "review-required"
    assert summary.day_set_complete is False
    assert summary.unexpected_trading_days == ["2026-05-05"]
    assert summary.results[0].unexpected_trading_days == ["2026-05-05"]


def test_stock_sparse_coverage_profiles_gaps_without_rejecting(tmp_path):
    path = tmp_path / "minute-bars" / "202605" / "A000020.csv"
    _write_csv(
        path,
        [
            ("20260504", "901", "100", "101", "99", "100", "10"),
            ("20260504", "930", "100", "101", "99", "100", "10"),
        ],
    )

    summary = profile_csv_coverage(path, class_mode="stock-sparse", session_start=time(9, 1), session_end=time(9, 30))

    assert summary.acceptance_status == "accepted"
    assert summary.missing_minutes_count == 28
    assert summary.coverage_ratio < 1


def test_stock_sparse_coverage_rejects_missing_days_when_day_set_required(tmp_path):
    path = tmp_path / "minute-bars" / "202605" / "A000020.csv"
    _write_csv(
        path,
        [
            ("20260504", "901", "100", "101", "99", "100", "10"),
            ("20260504", "930", "100", "101", "99", "100", "10"),
        ],
    )

    summary = profile_csv_coverage(
        path,
        class_mode="stock-sparse",
        session_start=time(9, 1),
        session_end=time(9, 30),
        require_day_set=True,
    )

    assert summary.acceptance_status == "review-required"
    assert summary.results[0].status == "accepted"
    assert summary.results[0].day_set_evaluated is False
    assert summary.period_day_sets["202605"]["day_set_complete"] is False
    assert summary.day_set_complete is False


def test_phase2_coverage_cli_writes_report(tmp_path):
    path = tmp_path / "index-bars" / "202605" / "U001.csv"
    _write_csv(path, _minute_rows("20260504", start_hour=9, start_minute=1, end_hour=15, end_minute=30))
    output = tmp_path / "coverage.json"

    exit_code = main(["phase2-coverage", "--root", str(path), "--class-mode", "index-grid", "--output", str(output)])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["acceptance_status"] == "review-required"
    assert payload["class_mode"] == "index-grid"
    assert payload["calendar_certified"] is False
    assert payload["day_set_evaluated"] is False
    assert payload["day_set_complete"] is False
    assert payload["promotable_calendar"] is False


def test_phase2_coverage_cli_accepts_only_when_day_set_is_evaluated(tmp_path):
    path = tmp_path / "index-bars" / "202605" / "U001.csv"
    _write_csv(path, _month_minute_rows("202605"))
    output = tmp_path / "coverage.json"

    exit_code = main(
        [
            "phase2-coverage",
            "--root",
            str(path),
            "--class-mode",
            "index-grid",
            "--require-day-set",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["acceptance_status"] == "accepted"
    assert payload["day_set_evaluated"] is True
    assert payload["day_set_complete"] is True
    assert payload["calendar_certified"] is False
    assert payload["promotable_calendar"] is False


def test_phase2_coverage_cli_can_require_day_set(tmp_path):
    path = tmp_path / "index-bars" / "202605" / "U001.csv"
    _write_csv(path, _short_rows())
    output = tmp_path / "coverage.json"

    exit_code = main(
        [
            "phase2-coverage",
            "--root",
            str(path),
            "--class-mode",
            "index-grid",
            "--require-day-set",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["day_set_complete"] is False
    assert payload["missing_trading_days"]


def test_phase2_coverage_filters_periods_and_limits_files(tmp_path):
    first = tmp_path / "minute-bars" / "202604" / "A000020.csv"
    second = tmp_path / "minute-bars" / "202605" / "A000030.csv"
    third = tmp_path / "minute-bars" / "202605" / "A000040.csv"
    for path in [first, second, third]:
        _write_csv(path, [("20260504", "901", "100", "101", "99", "100", "10")])

    summary = profile_csv_coverage(
        tmp_path / "minute-bars",
        class_mode="stock-sparse",
        periods=["202605"],
        limit_files=1,
    )

    assert summary.file_count == 1
    assert summary.results[0].path.endswith("202605/A000030.csv")


def test_phase2_coverage_rejects_empty_period_match(tmp_path, capsys):
    root = tmp_path / "minute-bars"
    (root / "202605").mkdir(parents=True)
    output = tmp_path / "coverage.json"

    exit_code = main(
        [
            "phase2-coverage",
            "--root",
            str(root),
            "--class-mode",
            "stock-sparse",
            "--period",
            "202605",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert exit_code == 1
    assert payload["file_count"] == 0
    assert payload["acceptance_status"] == "review-required"
    assert "no csv files matched" in captured.err


def test_stock_sparse_coverage_rejects_empty_csv(tmp_path):
    path = tmp_path / "minute-bars" / "202605" / "A000020.csv"
    _write_csv(path, [])

    summary = profile_csv_coverage(path, class_mode="stock-sparse", session_start=time(9, 1), session_end=time(9, 30))

    assert summary.acceptance_status == "review-required"
