from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from zurini.bulk_db_import import BulkImportOptions
from zurini.bulk_db_import import DAILY_DATA_ORIGIN
from zurini.bulk_db_import import DAILY_SOURCE
from zurini.bulk_db_import import INDEX_SOURCE
from zurini.bulk_db_import import MINUTE_DATA_ORIGIN
from zurini.bulk_db_import import MINUTE_SOURCE
from zurini.bulk_db_import import run_bulk_historical_import
from zurini.data import db
from zurini.simulation_analysis_cli import main


KST = ZoneInfo("Asia/Seoul")


def test_bulk_historical_import_minimal_files_insert_each_artifact_class(tmp_path) -> None:
    minute_root = tmp_path / "minute-bars"
    daily_root = tmp_path / "daily-bars"
    index_root = tmp_path / "index-bars"
    _write_csv(
        minute_root / "202605" / "A005930.csv",
        "date,time,open,high,low,close,volume\n"
        "20260515,0901,100,101,99,100,1000\n"
        "20260515,0902,100,102,99,101,\n",
    )
    _write_csv(
        daily_root / "202605" / "A005930.csv",
        "date,time,open,high,low,close,volume\n"
        "20260515,0,100,102,99,101,1000\n",
    )
    _write_csv(
        index_root / "202605" / "U001.csv",
        "date,time,open,high,low,close,volume\n"
        "20260515,0901,300,301,299,300,10\n",
    )
    captured: dict[str, list[object]] = {"minute": [], "daily": [], "index": []}

    def _insert_minute(rows):
        captured["minute"].extend(rows)
        return db.ResearchMinuteImportResult(
            inserted_raw_rows=len(rows),
            canonical_rows_refreshed=len(rows),
            distinct_key_count=len(rows),
            duplicate_input_rows=0,
        )

    def _insert_daily(rows):
        captured["daily"].extend(rows)
        return db.UniverseDailyImportResult(
            inserted_or_updated_raw_rows=len(rows),
            canonical_rows_refreshed=len(rows),
            distinct_key_count=len(rows),
            duplicate_input_rows=0,
        )

    def _insert_index(rows):
        captured["index"].extend(rows)
        return len(rows)

    report = run_bulk_historical_import(
        BulkImportOptions(
            minute_root=minute_root,
            daily_root=daily_root,
            index_root=index_root,
            include=("minute", "daily", "index"),
            limit_files=1,
            source_run_id="smoke-run",
            import_batch_id="smoke-batch",
            batch_size=1,
        ),
        apply_schema=lambda: None,
        insert_research_minute_rows=_insert_minute,
        insert_universe_daily_rows=_insert_daily,
        insert_index_bars=_insert_index,
    )

    minute = captured["minute"]
    daily = captured["daily"]
    index = captured["index"]
    assert report["totals"]["files_selected"] == 3
    assert report["totals"]["rows_read"] == 4
    assert report["totals"]["rows_inserted_or_updated"] == 4
    assert minute[0].source == MINUTE_SOURCE
    assert minute[0].vendor == "daishin"
    assert minute[0].data_origin == MINUTE_DATA_ORIGIN
    assert minute[0].timestamp == datetime(2026, 5, 15, 9, 1, tzinfo=KST)
    assert minute[0].value is None
    assert minute[0].traded_value is None
    assert minute[1].volume is None
    assert daily[0].source == DAILY_SOURCE
    assert daily[0].data_origin == DAILY_DATA_ORIGIN
    assert daily[0].source_run_id == "smoke-run"
    assert daily[0].import_batch_id == "smoke-batch"
    assert daily[0].quality_flags == ("value_missing",)
    assert index[0].index_code == "U001"
    assert index[0].source == INDEX_SOURCE
    assert index[0].vendor == "daishin"
    assert index[0].data_origin == "index-minute-backfill"
    assert index[0].source_run_id == "smoke-run"
    assert index[0].import_batch_id == "smoke-batch"
    assert index[0].schema_version == "historical-artifact-csv-v1"
    assert index[0].raw_payload["row_number"] == 2
    assert index[0].timestamp == datetime(2026, 5, 15, 9, 1, tzinfo=KST)


def test_bulk_historical_import_batches_minute_rows_across_files(tmp_path) -> None:
    minute_root = tmp_path / "minute-bars"
    for symbol in ("A000001", "A000002", "A000003"):
        _write_csv(minute_root / "202605" / f"{symbol}.csv", _one_row_csv("0901"))
    batch_lengths = []

    def _insert_minute(rows):
        batch = list(rows)
        batch_lengths.append(len(batch))
        return db.ResearchMinuteImportResult(
            inserted_raw_rows=len(batch),
            canonical_rows_refreshed=len(batch),
            distinct_key_count=len(batch),
            duplicate_input_rows=0,
        )

    report = run_bulk_historical_import(
        BulkImportOptions(
            minute_root=minute_root,
            include=("minute",),
            limit_files=3,
            batch_size=2,
        ),
        apply_schema=lambda: None,
        insert_research_minute_rows=_insert_minute,
    )

    assert batch_lengths == [2, 1]
    assert report["totals"]["files_selected"] == 3
    assert report["totals"]["rows_read"] == 3
    assert report["totals"]["rows_inserted_or_updated"] == 3


def test_bulk_historical_import_batches_daily_rows_across_files(tmp_path) -> None:
    daily_root = tmp_path / "daily-bars"
    for symbol in ("A000001", "A000002", "A000003"):
        _write_csv(daily_root / "202605" / f"{symbol}.csv", _one_row_csv("0"))
    batch_lengths = []

    def _insert_daily(rows):
        batch = list(rows)
        batch_lengths.append(len(batch))
        return db.UniverseDailyImportResult(
            inserted_or_updated_raw_rows=len(batch),
            canonical_rows_refreshed=len(batch),
            distinct_key_count=len(batch),
            duplicate_input_rows=0,
        )

    report = run_bulk_historical_import(
        BulkImportOptions(
            daily_root=daily_root,
            include=("daily",),
            limit_files=3,
            batch_size=2,
        ),
        apply_schema=lambda: None,
        insert_universe_daily_rows=_insert_daily,
    )

    assert batch_lengths == [2, 1]
    assert report["totals"]["files_selected"] == 3
    assert report["totals"]["rows_read"] == 3
    assert report["totals"]["rows_inserted_or_updated"] == 3


def test_bulk_historical_import_batches_index_rows_across_files(tmp_path) -> None:
    index_root = tmp_path / "index-bars"
    for symbol in ("U001", "U002", "U003"):
        _write_csv(index_root / "202605" / f"{symbol}.csv", _one_row_csv("0901"))
    batch_lengths = []

    def _insert_index(rows):
        batch = list(rows)
        batch_lengths.append(len(batch))
        return db.IndexBarImportResult(
            inserted_or_updated_rows=len(batch),
            inserted_rows=len(batch),
            updated_rows=0,
            distinct_key_count=len(batch),
            duplicate_input_rows=0,
        )

    report = run_bulk_historical_import(
        BulkImportOptions(
            index_root=index_root,
            include=("index",),
            limit_files=3,
            batch_size=2,
        ),
        apply_schema=lambda: None,
        insert_index_bars=_insert_index,
    )

    assert batch_lengths == [2, 1]
    assert report["totals"]["files_selected"] == 3
    assert report["totals"]["rows_read"] == 3
    assert report["totals"]["rows_inserted_or_updated"] == 3
    assert report["totals"]["rows_inserted"] == 3


def test_bulk_historical_import_dry_run_counts_minimal_files_without_inserting(tmp_path) -> None:
    minute_root = tmp_path / "minute-bars"
    daily_root = tmp_path / "daily-bars"
    index_root = tmp_path / "index-bars"
    _write_csv(minute_root / "202605" / "A005930.csv", _one_row_csv("0901"))
    _write_csv(daily_root / "202605" / "A005930.csv", _one_row_csv("0"))
    _write_csv(index_root / "202605" / "U001.csv", _one_row_csv("0901"))

    def _unexpected_insert(_rows):
        raise AssertionError("dry-run must not call insert functions")

    report = run_bulk_historical_import(
        BulkImportOptions(
            minute_root=minute_root,
            daily_root=daily_root,
            index_root=index_root,
            dry_run=True,
            limit_files=1,
        ),
        apply_schema=lambda: None,
        insert_research_minute_rows=_unexpected_insert,
        insert_universe_daily_rows=_unexpected_insert,
        insert_index_bars=_unexpected_insert,
    )

    assert report["dry_run"] is True
    assert report["totals"]["files_selected"] == 3
    assert report["totals"]["rows_read"] == 3
    assert report["totals"]["rows_inserted_or_updated"] == 0
    assert "not_run" in report["full_dataset_import"]


def test_historical_db_import_cli_writes_limit_file_report(tmp_path) -> None:
    minute_root = tmp_path / "minute-bars"
    daily_root = tmp_path / "daily-bars"
    index_root = tmp_path / "index-bars"
    _write_csv(minute_root / "202605" / "A005930.csv", _one_row_csv("0901"))
    _write_csv(daily_root / "202605" / "A005930.csv", _one_row_csv("0"))
    _write_csv(index_root / "202605" / "U001.csv", _one_row_csv("0901"))
    output = tmp_path / "historical-db-import.json"

    exit_code = main(
        [
            "historical-db-import",
            "--dry-run",
            "--limit-files",
            "1",
            "--minute-root",
            str(minute_root),
            "--daily-root",
            str(daily_root),
            "--index-root",
            str(index_root),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["mode"] == "analysis-only-no-order"
    assert payload["dry_run"] is True
    assert payload["limit_files"] == 1
    assert payload["totals"]["rows_read"] == 3
    by_class = {item["artifact_class"]: item for item in payload["artifact_reports"]}
    assert by_class["minute"]["source"] == MINUTE_SOURCE
    assert by_class["daily"]["source"] == DAILY_SOURCE
    assert by_class["index"]["source"] == INDEX_SOURCE


def test_historical_db_import_cli_defaults_to_dry_run(tmp_path) -> None:
    minute_root = tmp_path / "minute-bars"
    daily_root = tmp_path / "daily-bars"
    index_root = tmp_path / "index-bars"
    _write_csv(minute_root / "202605" / "A005930.csv", _one_row_csv("0901"))
    output = tmp_path / "historical-db-import.json"

    exit_code = main(
        [
            "historical-db-import",
            "--include",
            "minute",
            "--limit-files",
            "1",
            "--minute-root",
            str(minute_root),
            "--daily-root",
            str(daily_root),
            "--index-root",
            str(index_root),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["totals"]["rows_inserted_or_updated"] == 0


def test_historical_db_import_apply_requires_limit_files(tmp_path) -> None:
    with pytest.raises(ValueError, match="--apply requires --limit-files"):
        main(
            [
                "historical-db-import",
                "--apply",
                "--minute-root",
                str(tmp_path / "minute-bars"),
                "--daily-root",
                str(tmp_path / "daily-bars"),
                "--index-root",
                str(tmp_path / "index-bars"),
            ]
        )


def test_bulk_historical_import_rejects_daily_rows_with_nonzero_time(tmp_path) -> None:
    daily_root = tmp_path / "daily-bars"
    _write_csv(daily_root / "202605" / "A005930.csv", _one_row_csv("0901"))

    try:
        run_bulk_historical_import(
            BulkImportOptions(
                daily_root=daily_root,
                include=("daily",),
                dry_run=True,
                limit_files=1,
            )
        )
    except ValueError as exc:
        assert "daily universe CSV requires time=0" in str(exc)
    else:
        raise AssertionError("daily CSV with nonzero time should fail closed")


@pytest.mark.integration
def test_bulk_historical_import_minimal_files_db_smoke(tmp_path) -> None:
    pytest.importorskip("psycopg")
    minute_root = tmp_path / "minute-bars"
    daily_root = tmp_path / "daily-bars"
    index_root = tmp_path / "index-bars"
    _write_csv(minute_root / "202605" / "A005930.csv", _one_row_csv("0901"))
    _write_csv(daily_root / "202605" / "A005930.csv", _one_row_csv("0"))
    _write_csv(index_root / "202605" / "U001.csv", _one_row_csv("0901"))
    db.reset_research_minute_tables()
    db.reset_universe_daily_tables()
    db.reset_index_tables()

    report = run_bulk_historical_import(
        BulkImportOptions(
            minute_root=minute_root,
            daily_root=daily_root,
            index_root=index_root,
            limit_files=1,
            source_run_id="db-smoke-run",
            import_batch_id="db-smoke-batch",
        )
    )

    assert report["totals"]["rows_inserted_or_updated"] == 3
    with db._connect() as conn:
        minute = conn.execute(
            """
            SELECT count(*), min(source), min(vendor), min(data_origin), min(value), min(traded_value)
            FROM research_minute_raw
            WHERE import_batch_id = 'db-smoke-batch'
            """
        ).fetchone()
        daily = conn.execute(
            """
            SELECT count(*), min(source), min(vendor), min(data_origin), min(source_count)
            FROM universe_daily_canonical
            WHERE import_batch_id = 'db-smoke-batch'
            """
        ).fetchone()
        index = conn.execute(
            """
            SELECT count(*), min(source), min(vendor), min(data_origin), min(source_run_id), min(import_batch_id),
                   min(schema_version), min(raw_payload ->> 'row_number')
            FROM index_bars
            WHERE import_batch_id = %s
            """,
            ("db-smoke-batch",),
        ).fetchone()
    assert minute == (1, MINUTE_SOURCE, "daishin", MINUTE_DATA_ORIGIN, None, None)
    assert daily == (1, DAILY_SOURCE, "daishin", DAILY_DATA_ORIGIN, 1)
    assert index == (
        1,
        INDEX_SOURCE,
        "daishin",
        "index-minute-backfill",
        "db-smoke-run",
        "db-smoke-batch",
        "historical-artifact-csv-v1",
        "2",
    )


@pytest.mark.integration
def test_bulk_historical_import_index_reimport_preserves_batch_provenance(tmp_path) -> None:
    pytest.importorskip("psycopg")
    index_root = tmp_path / "index-bars"
    csv_path = index_root / "202605" / "U001.csv"
    _write_csv(csv_path, _one_row_csv("0901"))
    db.reset_index_tables()

    first = run_bulk_historical_import(
        BulkImportOptions(
            index_root=index_root,
            include=("index",),
            limit_files=1,
            source_run_id="run-a",
            import_batch_id="batch-a",
        )
    )
    second = run_bulk_historical_import(
        BulkImportOptions(
            index_root=index_root,
            include=("index",),
            limit_files=1,
            source_run_id="run-b",
            import_batch_id="batch-b",
        )
    )
    repeat = run_bulk_historical_import(
        BulkImportOptions(
            index_root=index_root,
            include=("index",),
            limit_files=1,
            source_run_id="run-b",
            import_batch_id="batch-b",
        )
    )

    with db._connect() as conn:
        rows = conn.execute(
            """
            SELECT import_batch_id, source_run_id, source, vendor, data_origin, schema_version,
                   raw_payload ->> 'path', raw_payload ->> 'row_number'
            FROM index_bars
            ORDER BY import_batch_id
            """
        ).fetchall()

    assert first["totals"]["rows_inserted"] == 1
    assert first["totals"]["rows_updated"] == 0
    assert second["totals"]["rows_inserted"] == 1
    assert second["totals"]["rows_updated"] == 0
    assert repeat["totals"]["rows_inserted"] == 0
    assert repeat["totals"]["rows_updated"] == 1
    assert repeat["totals"]["rows_inserted_or_updated"] == 1
    assert [row[0] for row in rows] == ["batch-a", "batch-b"]
    assert rows[0][1:6] == ("run-a", INDEX_SOURCE, "daishin", "index-minute-backfill", "historical-artifact-csv-v1")
    assert rows[1][1:6] == ("run-b", INDEX_SOURCE, "daishin", "index-minute-backfill", "historical-artifact-csv-v1")
    assert rows[0][6] == str(csv_path)
    assert rows[1][7] == "2"


def _one_row_csv(time_value: str) -> str:
    return (
        "date,time,open,high,low,close,volume\n"
        f"20260515,{time_value},100,101,99,100,1000\n"
    )


def _write_csv(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
