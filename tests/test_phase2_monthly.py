from __future__ import annotations

import json
from pathlib import Path

import pytest

from zurini.cli import main
from zurini.phase2 import build_monthly_rehearsal_plan, read_path_list


def _write_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20260102,901,100,101,99,100,10\n",
        encoding="utf-8",
    )


def test_monthly_plan_selects_completed_months_and_common_symbols(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202601", "202602", "202603"]:
        _write_csv(root / period / "A111111.csv")
    _write_csv(root / "202601" / "A222222.csv")
    _write_csv(root / "202603" / "A222222.csv")

    plan = build_monthly_rehearsal_plan(
        root,
        output_dir=tmp_path / "reports",
        current_yyyymm="202603",
        limit_symbols=10,
    )

    assert plan.selected_months == ["202601", "202602"]
    assert plan.excluded_months == ["202603"]
    assert plan.selected_symbols == ["A111111"]
    assert plan.path_list == [
        str(root / "202601" / "A111111.csv"),
        str(root / "202602" / "A111111.csv"),
    ]
    assert "--path-list" in plan.recommended_command


def test_monthly_plan_can_restrict_requested_months(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202512", "202601", "202602"]:
        _write_csv(root / period / "A111111.csv")

    plan = build_monthly_rehearsal_plan(
        root,
        output_dir=tmp_path / "reports",
        current_yyyymm="202603",
        requested_months=["202601", "202602"],
    )

    assert plan.selected_months == ["202601", "202602"]
    assert plan.excluded_months == ["202512"]


def test_monthly_plan_rejects_missing_requested_month(tmp_path):
    root = tmp_path / "minute-bars"
    _write_csv(root / "202601" / "A111111.csv")

    with pytest.raises(ValueError, match="requested months are missing"):
        build_monthly_rehearsal_plan(
            root,
            output_dir=tmp_path / "reports",
            current_yyyymm="202603",
            requested_months=["202604"],
        )


def test_monthly_plan_rejects_requested_current_month(tmp_path):
    root = tmp_path / "minute-bars"
    _write_csv(root / "202602" / "A111111.csv")
    _write_csv(root / "202603" / "A111111.csv")

    with pytest.raises(ValueError, match="requested months are not completed candidates"):
        build_monthly_rehearsal_plan(
            root,
            output_dir=tmp_path / "reports",
            current_yyyymm="202603",
            requested_months=["202603"],
        )


def test_monthly_plan_rejects_non_contiguous_requested_months(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202601", "202602", "202603"]:
        _write_csv(root / period / "A111111.csv")

    with pytest.raises(ValueError, match="requested months must be contiguous"):
        build_monthly_rehearsal_plan(
            root,
            output_dir=tmp_path / "reports",
            current_yyyymm="202604",
            requested_months=["202601", "202603"],
        )


def test_monthly_plan_defaults_to_latest_contiguous_completed_range(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202501", "202503", "202504", "202505"]:
        _write_csv(root / period / "A111111.csv")

    plan = build_monthly_rehearsal_plan(root, output_dir=tmp_path / "reports", current_yyyymm="202506")

    assert plan.selected_months == ["202503", "202504", "202505"]
    assert plan.excluded_months == ["202501"]


def test_monthly_plan_treats_empty_month_as_not_completed(tmp_path):
    root = tmp_path / "minute-bars"
    (root / "202601").mkdir(parents=True)
    _write_csv(root / "202602" / "A111111.csv")

    plan = build_monthly_rehearsal_plan(root, output_dir=tmp_path / "reports", current_yyyymm="202603")

    assert plan.selected_months == ["202602"]
    assert plan.excluded_months == ["202601"]
    assert [month.status for month in plan.months if month.period == "202601"] == ["empty"]


def test_monthly_plan_rejects_requested_empty_month(tmp_path):
    root = tmp_path / "minute-bars"
    (root / "202601").mkdir(parents=True)

    with pytest.raises(ValueError, match="requested months are not completed candidates"):
        build_monthly_rehearsal_plan(
            root,
            output_dir=tmp_path / "reports",
            current_yyyymm="202603",
            requested_months=["202601"],
        )


def test_read_path_list_ignores_blank_lines_and_comments(tmp_path):
    path_list = tmp_path / "paths.txt"
    path_list.write_text("\n# comment\nsample/A000020.csv\n\n", encoding="utf-8")

    assert read_path_list(path_list) == [Path("sample/A000020.csv")]


def test_phase2_monthly_plan_cli_writes_plan_and_path_list(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202601", "202602"]:
        _write_csv(root / period / "A111111.csv")
    output_dir = tmp_path / "reports"

    exit_code = main(
        [
            "phase2-monthly-plan",
            "--root",
            str(root),
            "--output-dir",
            str(output_dir),
            "--current-yyyymm",
            "202603",
        ]
    )

    assert exit_code == 0
    plan = json.loads((output_dir / "monthly-plan.json").read_text(encoding="utf-8"))
    paths = (output_dir / "backtest-paths.txt").read_text(encoding="utf-8").splitlines()
    assert plan["selected_months"] == ["202601", "202602"]
    assert plan["selected_symbols"] == ["A111111"]
    assert paths == [
        str(root / "202601" / "A111111.csv"),
        str(root / "202602" / "A111111.csv"),
    ]
