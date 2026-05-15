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
    assert config.collect_daily_indices is False
    assert config.collect_daily_stocks is False
    assert config.collect_metadata is False
    assert config.months == 24
    assert config.index_codes["U001"] == "KOSPI"
    assert config.index_codes["U201"] == "KOSDAQ"


def test_arg_parser_accepts_custom_index_code_overrides():
    collector = load_collector()

    config = collector.parse_args(["--no-stocks", "--no-metadata", "--index-code", "U999=CUSTOM"])

    assert config.index_codes["U999"] == "CUSTOM"


def test_arg_parser_accepts_daily_bar_collection_without_minute_collection():
    collector = load_collector()

    config = collector.parse_args(["--no-stocks", "--no-indices", "--daily-stocks", "--daily-indices"])

    assert config.collect_stocks is False
    assert config.collect_indices is False
    assert config.collect_daily_stocks is True
    assert config.collect_daily_indices is True


def test_run_routes_daily_bar_collection_to_daily_categories(tmp_path, monkeypatch):
    collector = load_collector()

    class FakeSession:
        def stock_codes(self):
            return ["A000020"]

        def code_name(self, code):
            return f"name-{code}"

        def metadata_rows(self, codes):
            return [
                {
                    "code": code,
                    "name": self.code_name(code),
                    "market": 1,
                    "section_kind": 1,
                    "status_kind": 0,
                    "control_kind": 0,
                    "supervision_kind": 0,
                }
                for code in codes
            ]

        def fetch_daily_bars(self, code, start_date, end_date):
            return [
                {
                    "date": start_date,
                    "time": "0",
                    "open": 1000,
                    "high": 1010,
                    "low": 990,
                    "close": 1005,
                    "volume": 12,
                }
            ]

        def fetch_minute_bars(self, code, start_date, end_date):
            raise AssertionError("minute collection should not run")

    monkeypatch.setattr(collector, "CybosSession", FakeSession)
    config = collector.parse_args(
        [
            "--output-dir",
            str(tmp_path),
            "--start-date",
            "20260508",
            "--end-date",
            "20260508",
            "--no-stocks",
            "--no-indices",
            "--daily-stocks",
            "--daily-indices",
        ]
    )

    assert collector.run(config) == 0

    assert (tmp_path / "daily-bars" / "202605" / "A000020.csv").exists()
    assert (tmp_path / "daily-index-bars" / "202605" / "U001.csv").exists()
    manifest = next((tmp_path / "manifests").glob("collection_manifest_*.jsonl"))
    text = manifest.read_text(encoding="utf-8")
    assert '"category": "daily-bars"' in text
    assert '"category": "daily-index-bars"' in text
