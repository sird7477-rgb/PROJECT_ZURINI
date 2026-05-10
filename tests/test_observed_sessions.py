from __future__ import annotations

import json
from pathlib import Path

from zurini.cli import main
from zurini.observed_sessions import build_observed_session_plan


def _write_csv(path: Path, date: str, minutes: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,time,open,high,low,close,volume"]
    lines.extend(f"{date},{minute},100,101,99,100,10" for minute in minutes)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_multi_day_csv(path: Path, days: list[str], minutes: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,time,open,high,low,close,volume"]
    for day in days:
        lines.extend(f"{day},{minute},100,101,99,100,10" for minute in minutes)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_observed_session_plan_uses_index_observed_days_without_requiring_full_month(tmp_path):
    index_root = tmp_path / "index-bars"
    stock_root = tmp_path / "minute-bars"
    for symbol in ["U001", "U180"]:
        _write_multi_day_csv(index_root / "202405" / f"{symbol}.csv", ["20240509", "20240510", "20240513"], ["901", "902"])
    _write_csv(stock_root / "202405" / "A000020.csv", "20240509", ["901"])
    _write_csv(stock_root / "202405" / "A000030.csv", "20240509", ["901"])

    plan = build_observed_session_plan(
        index_root=index_root,
        stock_root=stock_root,
        output_dir=tmp_path / "reports",
        limit_symbols=1,
        min_trading_days=3,
    )

    assert plan.accepted_day_count == 3
    assert plan.blocks[0].start_date == "2024-05-09"
    assert plan.blocks[0].end_date == "2024-05-13"
    assert plan.selected_symbols == ["A000020"]
    assert plan.path_list == [str(stock_root / "202405" / "A000020.csv")]


def test_observed_session_plan_rejects_shared_index_gap(tmp_path):
    index_root = tmp_path / "index-bars"
    stock_root = tmp_path / "minute-bars"
    for symbol in ["U001", "U180"]:
        _write_csv(index_root / "202405" / f"{symbol}.csv", "20240509", ["901", "903"])
    _write_csv(stock_root / "202405" / "A000020.csv", "20240509", ["901"])

    plan = build_observed_session_plan(
        index_root=index_root,
        stock_root=stock_root,
        output_dir=tmp_path / "reports",
        limit_symbols=1,
        min_trading_days=1,
    )

    assert plan.accepted_day_count == 0
    assert plan.rejected_day_count == 1
    assert plan.selected_block is None
    assert plan.path_list == []
    assert "--start-date" not in plan.recommended_command
    assert "--end-date" not in plan.recommended_command


def test_observed_session_plan_can_select_named_block(tmp_path):
    index_root = tmp_path / "index-bars"
    stock_root = tmp_path / "minute-bars"
    for symbol in ["U001", "U180"]:
        _write_multi_day_csv(index_root / "202405" / f"{symbol}.csv", ["20240509", "20240510"], ["901", "902"])
        _write_multi_day_csv(index_root / "202406" / f"{symbol}.csv", ["20240603", "20240604", "20240605"], ["901", "902"])
    _write_csv(stock_root / "202405" / "A000020.csv", "20240509", ["901"])
    _write_csv(stock_root / "202406" / "A000020.csv", "20240603", ["901"])

    plan = build_observed_session_plan(
        index_root=index_root,
        stock_root=stock_root,
        output_dir=tmp_path / "reports",
        limit_symbols=1,
        min_trading_days=2,
        select_block="observed-block-2",
    )

    assert plan.selected_block is not None
    assert plan.selected_block.name == "observed-block-2"
    assert plan.selected_block.start_date == "2024-06-03"
    assert plan.path_list == [str(stock_root / "202406" / "A000020.csv")]


def test_observed_session_plan_breaks_when_intervening_trading_day_is_missing(tmp_path):
    index_root = tmp_path / "index-bars"
    stock_root = tmp_path / "minute-bars"
    for symbol in ["U001", "U180"]:
        _write_multi_day_csv(index_root / "202605" / f"{symbol}.csv", ["20260507", "20260511"], ["901", "902"])
    _write_csv(stock_root / "202605" / "A000020.csv", "20260507", ["901"])

    plan = build_observed_session_plan(
        index_root=index_root,
        stock_root=stock_root,
        output_dir=tmp_path / "reports",
        limit_symbols=1,
        min_trading_days=1,
    )

    assert [block.start_date for block in plan.blocks] == ["2026-05-07", "2026-05-11"]
    assert [block.trading_day_count for block in plan.blocks] == [1, 1]


def test_observed_session_plan_cli_writes_plan_and_path_list(tmp_path):
    index_root = tmp_path / "index-bars"
    stock_root = tmp_path / "minute-bars"
    for symbol in ["U001", "U180"]:
        _write_csv(index_root / "202405" / f"{symbol}.csv", "20240509", ["901", "902"])
    _write_csv(stock_root / "202405" / "A000020.csv", "20240509", ["901"])
    output_dir = tmp_path / "reports"

    exit_code = main(
        [
            "phase2-observed-plan",
            "--index-root",
            str(index_root),
            "--stock-root",
            str(stock_root),
            "--output-dir",
            str(output_dir),
            "--limit-symbols",
            "1",
            "--min-trading-days",
            "1",
        ]
    )

    payload = json.loads((output_dir / "observed-session-plan.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["selected_block"]["start_date"] == "2024-05-09"
    assert (output_dir / "observed-backtest-paths.txt").read_text(encoding="utf-8").strip().endswith("A000020.csv")
