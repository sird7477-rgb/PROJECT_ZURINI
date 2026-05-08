from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path


def load_collector():
    path = Path("sample/collect_yearly/collect_yearly.py")
    spec = importlib.util.spec_from_file_location("collect_yearly", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_monthly_periods_reverse_uses_current_partial_month_first():
    collector = load_collector()

    periods = collector.monthly_periods_reverse(3, today=datetime(2026, 5, 9, 13, 30))

    assert [(period.folder_name, period.start, period.end) for period in periods] == [
        ("202605", "20260501", "20260509"),
        ("202604", "20260401", "20260430"),
        ("202603", "20260301", "20260331"),
    ]


def test_explicit_periods_are_month_bounded_and_reverse_ordered():
    collector = load_collector()

    periods = collector.explicit_periods("20250115", "20250302")

    assert [(period.folder_name, period.start, period.end) for period in periods] == [
        ("202503", "20250301", "20250302"),
        ("202502", "20250201", "20250228"),
        ("202501", "20250115", "20250131"),
    ]


def test_collection_output_paths_are_partitioned_by_category_and_month():
    collector = load_collector()
    period = collector.Period(folder_name="202504", start="20250401", end="20250430")

    assert collector.output_path(Path("data/raw/daishin"), "minute-bars", period, "A000020") == Path(
        "data/raw/daishin/minute-bars/202504/A000020.csv"
    )
    assert collector.output_path(Path("data/raw/daishin"), "index-bars", period, "U001") == Path(
        "data/raw/daishin/index-bars/202504/U001.csv"
    )


def test_arg_parser_keeps_default_second_phase_index_codes():
    collector = load_collector()

    config = collector.parse_args(["--no-stocks", "--no-metadata"])

    assert config.collect_indices is True
    assert config.collect_stocks is False
    assert config.collect_metadata is False
    assert config.months == 24
    assert config.index_codes["U001"] == "KOSPI"
    assert config.index_codes["U201"] == "KOSDAQ"


def test_arg_parser_accepts_custom_index_code_overrides():
    collector = load_collector()

    config = collector.parse_args(["--no-stocks", "--no-metadata", "--index-code", "U999=CUSTOM"])

    assert config.index_codes["U999"] == "CUSTOM"
