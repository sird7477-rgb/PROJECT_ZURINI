from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from zurini.cli import main
from zurini.field_universe import build_prior_only_field_universe, load_prior_daily_bars_from_minute_csvs
from zurini.market import Bar


KST = ZoneInfo("Asia/Seoul")


def test_prior_only_field_universe_includes_and_excludes_with_reasons():
    bars = []
    bars.extend(_bars("A111111", close_start=Decimal("100"), value=Decimal("1000000"), high_low_gap=Decimal("8"), days=20))
    bars.extend(_bars("A222222", close_start=Decimal("100"), value=Decimal("100"), high_low_gap=Decimal("8"), days=20))
    bars.extend(_bars("ETF001", close_start=Decimal("100"), value=Decimal("1000000"), high_low_gap=Decimal("8"), days=20))
    bars.extend(_bars("A333333", close_start=Decimal("100"), value=Decimal("1000000"), high_low_gap=Decimal("8"), days=10))
    bars.append(
        Bar(
            symbol="A999999",
            timestamp=datetime(2026, 5, 11, 15, 15, tzinfo=KST),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=1,
            value=Decimal("999999999"),
            source="future",
        )
    )

    report = build_prior_only_field_universe(
        bars,
        target_date=date(2026, 5, 11),
        min_average_value=Decimal("500000"),
        min_atr_ratio=Decimal("0.03"),
        max_symbols=10,
        min_prior_trading_days=10,
    )

    assert report.included_symbols == ("A111111",)
    assert report.kis_symbols == ("111111",)
    reasons = dict(report.excluded_symbols)
    assert reasons["A222222"] == "average-value-below-threshold"
    assert reasons["ETF001"] == "non-common-symbol-format"
    assert reasons["A333333"] == "insufficient-prior-history"
    assert "A999999" not in {member.symbol for member in report.members}
    assert report.summary()["ready_for_broker_or_order_transmission"] is False


def test_prior_only_field_universe_uses_kst_session_date_for_prior_filter():
    bars = _bars("A111111", close_start=Decimal("100"), value=Decimal("1000000"), high_low_gap=Decimal("8"), days=20)
    bars.append(
        Bar(
            symbol="A999999",
            timestamp=datetime(2026, 5, 11, 15, 5, tzinfo=KST).astimezone(ZoneInfo("UTC")),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=1000,
            value=Decimal("1050000000"),
            source="target-session-utc",
        )
    )

    report = build_prior_only_field_universe(
        bars,
        target_date=date(2026, 5, 11),
        min_average_value=Decimal("1"),
        min_atr_ratio=Decimal("0.01"),
        max_symbols=10,
        min_prior_trading_days=20,
    )

    assert "A999999" not in {member.symbol for member in report.members}


def test_build_field_universe_cli_writes_report_and_kis_symbol_list(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    rows = ["date,time,open,high,low,close,volume"]
    start = date(2026, 4, 10)
    for index in range(20):
        day = start + timedelta(days=index)
        close = 100 + index
        rows.append(f"{day:%Y%m%d},1515,{close},{close + 4},{close - 4},{close},10000")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    output = tmp_path / "field-universe.json"
    symbol_list = tmp_path / "kis-symbols.txt"

    exit_code = main(
        [
            "build-field-universe",
            "--target-date",
            "2026-05-12",
            "--path",
            str(csv_path),
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--min-prior-trading-days",
            "20",
            "--kis-symbol-list-output",
            str(symbol_list),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["included_count"] == 1
    assert payload["report"]["included_symbols"] == ["A111111"]
    assert payload["report"]["kis_symbols"] == ["111111"]
    assert symbol_list.read_text(encoding="utf-8") == "111111\n"


def test_build_field_universe_cli_blocks_less_than_60_prior_trading_days_by_default(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    rows = ["date,time,open,high,low,close,volume"]
    start = date(2026, 4, 10)
    for index in range(20):
        day = start + timedelta(days=index)
        close = 100 + index
        rows.append(f"{day:%Y%m%d},1515,{close},{close + 4},{close - 4},{close},10000")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    output = tmp_path / "field-universe.json"

    exit_code = main(
        [
            "build-field-universe",
            "--target-date",
            "2026-05-12",
            "--path",
            str(csv_path),
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["included_count"] == 0
    assert payload["report"]["members"][0]["observed_days"] == 20
    assert payload["report"]["members"][0]["reason"] == "insufficient-prior-source-days"
    assert payload["report"]["parameters"]["min_prior_trading_days"] == 60


def test_build_daily_field_universe_cli_uses_existing_builder_contract(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    rows = ["date,time,open,high,low,close,volume"]
    start = date(2026, 4, 10)
    for index in range(20):
        day = start + timedelta(days=index)
        close = 100 + index
        rows.append(f"{day:%Y%m%d},1515,{close},{close + 4},{close - 4},{close},10000")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    output = tmp_path / "daily-field-universe.json"

    exit_code = main(
        [
            "build-daily-field-universe",
            "--target-date",
            "2026-05-12",
            "--path",
            str(csv_path),
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--min-prior-trading-days",
            "20",
            "--max-prior-data-lag-days",
            "20",
            "--disable-expected-prior-date",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report"]["target_date"] == "2026-05-12"
    assert payload["summary"]["included_count"] == 1


def test_build_daily_field_universe_cli_fails_closed_on_stale_prior_source(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    _write_daily_csv(csv_path, start=date(2026, 2, 2), days=60, close_start=100)
    output = tmp_path / "daily-field-universe.json"

    exit_code = main(
        [
            "build-daily-field-universe",
            "--target-date",
            "2026-05-14",
            "--path",
            str(csv_path),
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["included_count"] == 0
    assert payload["summary"]["source_fresh"] is False
    assert payload["summary"]["latest_prior_date"] == "2026-04-02"
    assert payload["summary"]["latest_prior_lag_days"] == 42
    assert payload["report"]["parameters"]["max_prior_data_lag_days"] == 3
    assert {member["reason"] for member in payload["report"]["members"]} == {"source-data-unexpected-prior-date"}


def test_prior_only_field_universe_fails_closed_when_any_symbol_source_is_stale():
    fresh = _bars("A111111", close_start=Decimal("100"), value=Decimal("1000000"), high_low_gap=Decimal("8"), days=20)
    stale = [
        Bar(
            symbol="A222222",
            timestamp=bar.timestamp - timedelta(days=10),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            value=bar.value,
            source=bar.source,
        )
        for bar in _bars("A222222", close_start=Decimal("100"), value=Decimal("1000000"), high_low_gap=Decimal("8"), days=20)
    ]

    report = build_prior_only_field_universe(
        [*fresh, *stale],
        target_date=date(2026, 4, 21),
        min_average_value=Decimal("1"),
        min_atr_ratio=Decimal("0.01"),
        max_symbols=10,
        min_prior_trading_days=10,
        max_prior_data_lag_days=3,
    )

    assert report.included_symbols == ()
    assert report.source_fresh is False
    assert report.summary()["latest_prior_lag_days"] == 1
    assert report.summary()["source_date_lag_days"] == 11
    assert {reason for _, reason in report.excluded_symbols} == {
        "source-data-stale",
        "source-fleet-stale-fail-closed",
    }


def test_build_daily_field_universe_cli_reuses_valid_standby_artifact(tmp_path):
    standby = tmp_path / "standby-field-universe.json"
    standby.write_text(
        json.dumps(
            {
                "summary": {
                    "universe_id": "field-u1-prior-only",
                    "target_date": "2026-05-12",
                    "mode": "prior-only-read-only",
                    "included_count": 1,
                    "excluded_count": 0,
                    "ready_for_broker_or_order_transmission": False,
                    "latest_prior_date": "2026-05-11",
                    "latest_prior_lag_days": 1,
                    "source_date_lag_days": 1,
                    "source_fresh": True,
                },
                "report": {
                    "universe_id": "field-u1-prior-only",
                    "target_date": "2026-05-12",
                    "generated_at": "2026-05-11T06:30:00+00:00",
                    "mode": "prior-only-read-only",
                    "construction_rule": "U1",
                    "prior_only_cutoff": "2026-05-12",
                    "included_symbols": ["A111111"],
                    "kis_symbols": ["111111"],
                    "excluded_symbols": [],
                    "members": [],
                    "parameters": {"max_symbols": 100},
                    "safety_boundary": "read-only prior-data universe; no broker order, account, balance, credential, or real-fill calls",
                    "latest_prior_date": "2026-05-11",
                    "latest_prior_lag_days": 1,
                    "source_date_lag_days": 1,
                    "source_fresh": True,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "daily-field-universe.json"
    symbol_list = tmp_path / "kis-symbols.txt"

    exit_code = main(
        [
            "build-daily-field-universe",
            "--target-date",
            "2026-05-12",
            "--reuse-standby-artifact",
            "--standby-artifact",
            str(standby),
            "--max-standby-artifact-age-minutes",
            "10000",
            "--kis-symbol-list-output",
            str(symbol_list),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report"]["included_symbols"] == ["A111111"]
    assert payload["report"]["kis_symbols"] == ["111111"]
    assert symbol_list.read_text(encoding="utf-8") == "111111\n"


def test_build_daily_field_universe_cli_rejects_stale_standby_artifact(tmp_path):
    standby = tmp_path / "standby-field-universe.json"
    standby.write_text(
        json.dumps(
            {
                "summary": {
                    "universe_id": "field-u1-prior-only",
                    "target_date": "2026-05-12",
                    "mode": "prior-only-read-only",
                    "included_count": 1,
                    "excluded_count": 0,
                    "ready_for_broker_or_order_transmission": False,
                    "latest_prior_date": "2026-05-07",
                    "latest_prior_lag_days": 5,
                    "source_date_lag_days": 5,
                    "source_fresh": False,
                },
                "report": {
                    "universe_id": "field-u1-prior-only",
                    "target_date": "2026-05-12",
                    "generated_at": "2026-05-11T06:30:00+00:00",
                    "mode": "prior-only-read-only",
                    "construction_rule": "U1",
                    "prior_only_cutoff": "2026-05-12",
                    "included_symbols": ["A111111"],
                    "kis_symbols": ["111111"],
                    "excluded_symbols": [],
                    "members": [],
                    "parameters": {"max_symbols": 100},
                    "safety_boundary": "read-only prior-data universe; no broker order, account, balance, credential, or real-fill calls",
                    "latest_prior_date": "2026-05-07",
                    "latest_prior_lag_days": 5,
                    "source_date_lag_days": 5,
                    "source_fresh": False,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source freshness"):
        main(
            [
                "build-daily-field-universe",
                "--target-date",
                "2026-05-12",
                "--reuse-standby-artifact",
                "--standby-artifact",
                str(standby),
                "--output",
                str(tmp_path / "daily-field-universe.json"),
            ]
        )


def test_build_daily_field_universe_cli_rejects_invalid_standby_artifact(tmp_path):
    standby = tmp_path / "standby-field-universe.json"
    standby.write_text(
        json.dumps(
            {
                "summary": {
                    "universe_id": "field-u1-prior-only",
                    "target_date": "2026-05-11",
                    "mode": "prior-only-read-only",
                    "included_count": 0,
                    "excluded_count": 0,
                    "ready_for_broker_or_order_transmission": True,
                },
                "report": {
                    "universe_id": "field-u1-prior-only",
                    "target_date": "2026-05-11",
                    "mode": "prior-only-read-only",
                    "included_symbols": [],
                    "kis_symbols": [],
                    "safety_boundary": "read-only",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="target_date"):
        main(
            [
                "build-daily-field-universe",
                "--target-date",
                "2026-05-12",
                "--reuse-standby-artifact",
                "--standby-artifact",
                str(standby),
                "--output",
                str(tmp_path / "daily-field-universe.json"),
            ]
        )


def test_build_field_universe_cli_aggregates_minute_rows_into_daily_ohlcv(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    rows = ["date,time,open,high,low,close,volume"]
    start = date(2026, 4, 10)
    for index in range(20):
        day = start + timedelta(days=index)
        open_ = 100 + index
        rows.append(f"{day:%Y%m%d},0900,{open_},{open_ + 1},{open_ - 1},{open_ + 2},10")
        rows.append(f"{day:%Y%m%d},1515,{open_ + 2},{open_ + 6},{open_ - 3},{open_ + 5},20")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    output = tmp_path / "field-universe.json"

    exit_code = main(
        [
            "build-field-universe",
            "--target-date",
            "2026-05-12",
            "--path",
            str(csv_path),
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--min-prior-trading-days",
            "20",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    member = payload["report"]["members"][0]
    expected_latest_values = [
        Decimal(100 + index + 2) * Decimal("10") + Decimal(100 + index + 5) * Decimal("20")
        for index in range(15, 20)
    ]
    expected_average_value = sum(expected_latest_values, Decimal("0")) / Decimal(len(expected_latest_values))

    assert payload["report"]["included_symbols"] == ["A111111"]
    assert Decimal(member["average_value"]) == expected_average_value
    assert Decimal(member["atr_ratio"]) > Decimal("0.01")


def test_prior_only_field_universe_uses_true_range_for_gap_risk():
    bars = [
        Bar(
            symbol="A111111",
            timestamp=datetime(2026, 4, 1, 15, 15, tzinfo=KST),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1,
            value=Decimal("1000000"),
            source="test",
        ),
        Bar(
            symbol="A111111",
            timestamp=datetime(2026, 4, 2, 15, 15, tzinfo=KST),
            open=Decimal("120"),
            high=Decimal("121"),
            low=Decimal("119"),
            close=Decimal("120"),
            volume=1,
            value=Decimal("1000000"),
            source="test",
        ),
    ]

    report = build_prior_only_field_universe(
        bars,
        target_date=date(2026, 4, 3),
        value_window=1,
        sma_window=1,
        atr_window=2,
        min_average_value=Decimal("1"),
        min_atr_ratio=Decimal("0"),
        require_close_above_sma=False,
        max_symbols=10,
        min_prior_trading_days=2,
    )

    assert report.members[0].atr_ratio == Decimal("11.5") / Decimal("120")


def test_prior_only_field_universe_tie_breaks_symbols_ascending():
    bars = []
    bars.extend(_bars("A222222", close_start=Decimal("100"), value=Decimal("1000000"), high_low_gap=Decimal("8"), days=20))
    bars.extend(_bars("A111111", close_start=Decimal("100"), value=Decimal("1000000"), high_low_gap=Decimal("8"), days=20))

    report = build_prior_only_field_universe(
        bars,
        target_date=date(2026, 5, 11),
        min_average_value=Decimal("1"),
        min_atr_ratio=Decimal("0.01"),
        max_symbols=1,
        min_prior_trading_days=20,
    )

    assert report.included_symbols == ("A111111",)
    assert dict(report.excluded_symbols)["A222222"] == "max-symbols-rank-cutoff"


def test_build_field_universe_cli_uses_latest_available_month_dirs(tmp_path):
    root = tmp_path / "minute-bars"
    _write_daily_csv(root / "202601" / "A999999.csv", start=date(2026, 1, 5), days=20, close_start=200)
    _write_daily_csv(root / "202602" / "A111111.csv", start=date(2026, 2, 2), days=10, close_start=100)
    _write_daily_csv(root / "202603" / "A111111.csv", start=date(2026, 3, 2), days=10, close_start=110)
    output = tmp_path / "field-universe.json"

    exit_code = main(
        [
            "build-field-universe",
            "--target-date",
            "2026-04-01",
            "--root",
            str(root),
            "--latest-months",
            "2",
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--min-prior-trading-days",
            "20",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report"]["included_symbols"] == ["A111111"]
    assert "A999999" not in {member["symbol"] for member in payload["report"]["members"]}


def test_build_field_universe_cli_combines_same_symbol_across_selected_month_dirs(tmp_path):
    root = tmp_path / "minute-bars"
    _write_daily_csv(root / "202602" / "A111111.csv", start=date(2026, 2, 2), days=10, close_start=100)
    _write_daily_csv(root / "202603" / "A111111.csv", start=date(2026, 3, 2), days=10, close_start=110)
    output = tmp_path / "field-universe.json"

    exit_code = main(
        [
            "build-field-universe",
            "--target-date",
            "2026-04-01",
            "--root",
            str(root),
            "--latest-months",
            "2",
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--min-prior-trading-days",
            "20",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    members = {member["symbol"]: member for member in payload["report"]["members"]}
    assert payload["report"]["included_symbols"] == ["A111111"]
    assert members["A111111"]["observed_days"] == 20
    assert members["A111111"]["reason"] == "included"


def test_build_field_universe_cli_uses_nested_latest_month_dirs(tmp_path):
    root = tmp_path / "minute-bars"
    _write_daily_csv(root / "kospi" / "202602" / "A111111.csv", start=date(2026, 2, 2), days=10, close_start=100)
    _write_daily_csv(root / "kospi" / "202603" / "A111111.csv", start=date(2026, 3, 2), days=10, close_start=110)
    _write_daily_csv(root / "kospi" / "202604" / "A222222.csv", start=date(2026, 4, 2), days=20, close_start=120)
    output = tmp_path / "field-universe.json"

    exit_code = main(
        [
            "build-field-universe",
            "--target-date",
            "2026-05-01",
            "--root",
            str(root),
            "--latest-months",
            "1",
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--min-prior-trading-days",
            "20",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report"]["included_symbols"] == ["A222222"]
    assert "A111111" not in {member["symbol"] for member in payload["report"]["members"]}


def test_build_field_universe_cli_selects_latest_distinct_months_across_nested_markets(tmp_path):
    root = tmp_path / "minute-bars"
    _write_daily_csv(root / "kospi" / "202602" / "A999999.csv", start=date(2026, 2, 2), days=20, close_start=90)
    _write_daily_csv(root / "kospi" / "202603" / "A111111.csv", start=date(2026, 3, 2), days=20, close_start=100)
    _write_daily_csv(root / "kosdaq" / "202603" / "A222222.csv", start=date(2026, 3, 2), days=20, close_start=120)
    _write_daily_csv(root / "kospi" / "202604" / "A333333.csv", start=date(2026, 4, 2), days=20, close_start=140)
    output = tmp_path / "field-universe.json"

    exit_code = main(
        [
            "build-field-universe",
            "--target-date",
            "2026-05-01",
            "--root",
            str(root),
            "--latest-months",
            "2",
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--min-prior-trading-days",
            "20",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    member_symbols = {member["symbol"] for member in payload["report"]["members"]}
    assert {"A111111", "A222222", "A333333"}.issubset(member_symbols)
    assert "A999999" not in member_symbols


def test_build_field_universe_cli_prefers_direct_month_layout_over_nested_archives(tmp_path):
    root = tmp_path / "daily-bars"
    _write_daily_csv(root / "202604" / "A111111.csv", start=date(2026, 4, 2), days=20, close_start=100)
    _write_daily_csv(root / "archive" / "202605" / "A999999.csv", start=date(2026, 5, 2), days=20, close_start=200)
    output = tmp_path / "field-universe.json"

    exit_code = main(
        [
            "build-field-universe",
            "--target-date",
            "2026-05-20",
            "--root",
            str(root),
            "--latest-months",
            "1",
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--min-prior-trading-days",
            "20",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    member_symbols = {member["symbol"] for member in payload["report"]["members"]}
    assert "A111111" in member_symbols
    assert "A999999" not in member_symbols


def test_build_field_universe_cli_prefers_direct_symbol_files_inside_selected_month(tmp_path):
    root = tmp_path / "daily-bars"
    _write_daily_csv(root / "202605" / "A111111.csv", start=date(2026, 5, 1), days=20, close_start=100)
    _write_daily_csv(root / "202605" / "nested" / "A999999.csv", start=date(2026, 5, 1), days=20, close_start=200)
    output = tmp_path / "field-universe.json"

    exit_code = main(
        [
            "build-field-universe",
            "--target-date",
            "2026-05-25",
            "--root",
            str(root),
            "--latest-months",
            "1",
            "--min-average-value",
            "1",
            "--min-atr-ratio",
            "0.01",
            "--min-prior-trading-days",
            "20",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    member_symbols = {member["symbol"] for member in payload["report"]["members"]}
    assert "A111111" in member_symbols
    assert "A999999" not in member_symbols


def test_field_universe_loader_uses_optional_kis_traded_value_column(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    csv_path.write_text(
        "\n".join(
            [
                "date,time,open,high,low,close,volume,value",
                "20260513,1515,100,110,90,100,10,50000000000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    bars = load_prior_daily_bars_from_minute_csvs(
        [csv_path],
        target_date=date(2026, 5, 14),
        source="kis-daily-bars",
    )

    assert bars[0].value == Decimal("50000000000")


def _write_daily_csv(path, *, start: date, days: int, close_start: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["date,time,open,high,low,close,volume"]
    for index in range(days):
        day = start + timedelta(days=index)
        close = close_start + index
        rows.append(f"{day:%Y%m%d},1515,{close},{close + 4},{close - 4},{close},10000")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _bars(
    symbol: str,
    *,
    close_start: Decimal,
    value: Decimal,
    high_low_gap: Decimal,
    days: int,
) -> list[Bar]:
    start = date(2026, 4, 1)
    bars = []
    for index in range(days):
        close = close_start + Decimal(index)
        high = close + high_low_gap / Decimal("2")
        low = close - high_low_gap / Decimal("2")
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=datetime.combine(start + timedelta(days=index), datetime.min.time(), tzinfo=KST).replace(hour=15, minute=15),
                open=close,
                high=high,
                low=low,
                close=close,
                volume=1,
                value=value,
                source="test",
            )
        )
    return bars
