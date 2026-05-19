from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable, Iterator
from zoneinfo import ZoneInfo

from zurini.data import db
from zurini.research_minute_dataset import normalize_research_minute_row


KST = ZoneInfo("Asia/Seoul")
CSV_FIELDS = ("date", "time", "open", "high", "low", "close", "volume")
INCLUDE_CHOICES = frozenset({"minute", "daily", "index"})

MINUTE_SOURCE = "legacy-daishin-minute-bars"
MINUTE_VENDOR = "daishin"
MINUTE_DATA_ORIGIN = "legacy-minute-backfill"
DAILY_SOURCE = "legacy-daishin-universe-daily-bars"
DAILY_VENDOR = "daishin"
DAILY_DATA_ORIGIN = "universe-selection-source"
INDEX_SOURCE = "legacy-daishin-index-bars"


@dataclass(frozen=True)
class BulkImportOptions:
    minute_root: Path = Path("data/raw/daishin/minute-bars")
    daily_root: Path = Path("data/derived/daishin/daily-bars")
    index_root: Path = Path("data/raw/daishin/index-bars")
    include: tuple[str, ...] = ("minute", "daily", "index")
    dry_run: bool = False
    limit_files: int | None = None
    source_run_id: str = "bulk-historical-artifact-import"
    import_batch_id: str = "bulk-historical-artifact-import"
    schema_version: str = "historical-artifact-csv-v1"
    batch_size: int = 5_000


@dataclass(frozen=True)
class ArtifactClassConfig:
    name: str
    root: Path
    file_prefix: str
    source: str
    vendor: str
    data_origin: str


@dataclass(frozen=True)
class ArtifactClassReport:
    artifact_class: str
    root: str
    source: str
    vendor: str
    data_origin: str
    dry_run: bool
    limit_files: int | None
    files_matched: int
    files_selected: int
    rows_read: int
    rows_inserted_or_updated: int
    rows_inserted: int
    rows_updated: int
    canonical_rows_refreshed: int
    distinct_key_count: int
    duplicate_input_rows: int

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_class": self.artifact_class,
            "root": self.root,
            "source": self.source,
            "vendor": self.vendor,
            "data_origin": self.data_origin,
            "dry_run": self.dry_run,
            "limit_files": self.limit_files,
            "files_matched": self.files_matched,
            "files_selected": self.files_selected,
            "rows_read": self.rows_read,
            "rows_inserted_or_updated": self.rows_inserted_or_updated,
            "rows_inserted": self.rows_inserted,
            "rows_updated": self.rows_updated,
            "canonical_rows_refreshed": self.canonical_rows_refreshed,
            "distinct_key_count": self.distinct_key_count,
            "duplicate_input_rows": self.duplicate_input_rows,
        }


def run_bulk_historical_import(
    options: BulkImportOptions,
    *,
    apply_schema: Callable[[], None] = db.apply_schema,
    insert_research_minute_rows: Callable[[Iterable[object]], object] = db.insert_research_minute_rows,
    insert_universe_daily_rows: Callable[[Iterable[object]], object] = db.insert_universe_daily_rows,
    insert_index_bars: Callable[[Iterable[db.IndexBarRow]], object] = db.insert_index_bar_rows,
) -> dict[str, object]:
    include = _normalize_include(options.include)
    if options.limit_files is not None and options.limit_files < 0:
        raise ValueError("limit_files must be non-negative")
    if options.batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if not options.dry_run:
        apply_schema()

    reports = []
    if "minute" in include:
        reports.append(
            _import_minute_files(
                _minute_config(options.minute_root),
                options,
                insert_research_minute_rows=insert_research_minute_rows,
            )
        )
    if "daily" in include:
        reports.append(
            _import_daily_files(
                _daily_config(options.daily_root),
                options,
                insert_universe_daily_rows=insert_universe_daily_rows,
            )
        )
    if "index" in include:
        reports.append(
            _import_index_files(
                _index_config(options.index_root),
                options,
                insert_index_bars=insert_index_bars,
            )
        )

    return {
        "status": "ok",
        "mode": "analysis-only-no-order",
        "dry_run": options.dry_run,
        "limit_files": options.limit_files,
        "source_run_id": options.source_run_id,
        "import_batch_id": options.import_batch_id,
        "artifact_reports": [report.as_dict() for report in reports],
        "totals": {
            "files_selected": sum(report.files_selected for report in reports),
            "rows_read": sum(report.rows_read for report in reports),
            "rows_inserted_or_updated": sum(report.rows_inserted_or_updated for report in reports),
            "rows_inserted": sum(report.rows_inserted for report in reports),
            "rows_updated": sum(report.rows_updated for report in reports),
            "canonical_rows_refreshed": sum(report.canonical_rows_refreshed for report in reports),
        },
        "full_dataset_import": "not_run; requires later explicit command without --dry-run/--limit-files guardrails",
    }


def _import_minute_files(
    config: ArtifactClassConfig,
    options: BulkImportOptions,
    *,
    insert_research_minute_rows: Callable[[Iterable[object]], object],
) -> ArtifactClassReport:
    selected, matched_count = _select_files(config.root, config.file_prefix, options.limit_files)
    rows_read = 0
    inserted = 0
    refreshed = 0
    distinct = 0
    duplicates = 0
    for chunk in _chunked(
        _iter_minute_rows_for_files(selected, config=config, options=options),
        options.batch_size,
    ):
        rows_read += len(chunk)
        if options.dry_run:
            continue
        result = insert_research_minute_rows(chunk)
        inserted += int(getattr(result, "inserted_raw_rows"))
        refreshed += int(getattr(result, "canonical_rows_refreshed"))
        distinct += int(getattr(result, "distinct_key_count"))
        duplicates += int(getattr(result, "duplicate_input_rows"))
    return _report(config, options, matched_count, len(selected), rows_read, inserted, inserted, 0, refreshed, distinct, duplicates)


def _import_daily_files(
    config: ArtifactClassConfig,
    options: BulkImportOptions,
    *,
    insert_universe_daily_rows: Callable[[Iterable[object]], object],
) -> ArtifactClassReport:
    selected, matched_count = _select_files(config.root, config.file_prefix, options.limit_files)
    rows_read = 0
    changed = 0
    refreshed = 0
    distinct = 0
    duplicates = 0
    for chunk in _chunked(
        _iter_daily_rows_for_files(selected, config=config, options=options),
        options.batch_size,
    ):
        rows_read += len(chunk)
        if options.dry_run:
            continue
        result = insert_universe_daily_rows(chunk)
        changed += int(getattr(result, "inserted_or_updated_raw_rows"))
        refreshed += int(getattr(result, "canonical_rows_refreshed"))
        distinct += int(getattr(result, "distinct_key_count"))
        duplicates += int(getattr(result, "duplicate_input_rows"))
    return _report(config, options, matched_count, len(selected), rows_read, changed, changed, 0, refreshed, distinct, duplicates)


def _import_index_files(
    config: ArtifactClassConfig,
    options: BulkImportOptions,
    *,
    insert_index_bars: Callable[[Iterable[db.IndexBarRow]], object],
) -> ArtifactClassReport:
    selected, matched_count = _select_files(config.root, config.file_prefix, options.limit_files)
    rows_read = 0
    changed = 0
    inserted = 0
    updated = 0
    distinct = 0
    duplicates = 0
    for chunk in _chunked(
        _iter_index_bars_for_files(selected, config=config, options=options),
        options.batch_size,
    ):
        rows_read += len(chunk)
        if not options.dry_run:
            result = insert_index_bars(chunk)
            if isinstance(result, int):
                changed += result
                inserted += result
                distinct += result
            else:
                changed += int(getattr(result, "inserted_or_updated_rows"))
                inserted += int(getattr(result, "inserted_rows"))
                updated += int(getattr(result, "updated_rows"))
                distinct += int(getattr(result, "distinct_key_count"))
                duplicates += int(getattr(result, "duplicate_input_rows"))
    return _report(
        config,
        options,
        matched_count,
        len(selected),
        rows_read,
        changed,
        inserted,
        updated,
        0,
        distinct,
        duplicates,
    )


def _iter_minute_rows(path: Path, *, config: ArtifactClassConfig, options: BulkImportOptions):
    symbol = _symbol_from_filename(path, "A")
    for row_number, row in _read_csv_rows(path):
        observed_at = _timestamp_from_daishin_fields(row["date"], row["time"], path=path, row_number=row_number)
        value = _optional_decimal(row, "value", path=path, row_number=row_number)
        yield normalize_research_minute_row(
            symbol=symbol,
            timestamp=observed_at,
            interval="1m",
            open_price=_required_decimal(row, "open", path=path, row_number=row_number),
            high=_required_decimal(row, "high", path=path, row_number=row_number),
            low=_required_decimal(row, "low", path=path, row_number=row_number),
            close=_required_decimal(row, "close", path=path, row_number=row_number),
            volume=_optional_int(row, "volume", path=path, row_number=row_number),
            value=value,
            traded_value=None,
            data_origin=config.data_origin,
            source=config.source,
            vendor=config.vendor,
            source_run_id=options.source_run_id,
            import_batch_id=options.import_batch_id,
            schema_version=options.schema_version,
            raw_payload=_raw_payload(path, row_number, row),
        )


def _iter_minute_rows_for_files(
    paths: Iterable[Path],
    *,
    config: ArtifactClassConfig,
    options: BulkImportOptions,
):
    for path in paths:
        yield from _iter_minute_rows(path, config=config, options=options)


def _iter_daily_rows(path: Path, *, config: ArtifactClassConfig, options: BulkImportOptions):
    symbol = _symbol_from_filename(path, "A")
    for row_number, row in _read_csv_rows(path):
        if _normalize_time_token(row["time"]) != "000000":
            raise ValueError(f"{path}:{row_number} daily universe CSV requires time=0")
        volume = _optional_int(row, "volume", path=path, row_number=row_number)
        value = _optional_decimal(row, "value", path=path, row_number=row_number)
        flags = []
        if volume is None:
            flags.append("volume_missing")
        if value is None:
            flags.append("value_missing")
        yield db.UniverseDailyRow(
            symbol=symbol,
            trading_date=_parse_date(row["date"], path=path, row_number=row_number),
            open=_required_decimal(row, "open", path=path, row_number=row_number),
            high=_required_decimal(row, "high", path=path, row_number=row_number),
            low=_required_decimal(row, "low", path=path, row_number=row_number),
            close=_required_decimal(row, "close", path=path, row_number=row_number),
            volume=volume,
            value=value,
            data_origin=config.data_origin,
            source=config.source,
            vendor=config.vendor,
            source_run_id=options.source_run_id,
            import_batch_id=options.import_batch_id,
            schema_version=options.schema_version,
            quality_flags=tuple(flags),
            raw_payload=_raw_payload(path, row_number, row),
        )


def _iter_daily_rows_for_files(
    paths: Iterable[Path],
    *,
    config: ArtifactClassConfig,
    options: BulkImportOptions,
):
    for path in paths:
        yield from _iter_daily_rows(path, config=config, options=options)


def _iter_index_bars(path: Path, *, config: ArtifactClassConfig, options: BulkImportOptions) -> Iterator[db.IndexBarRow]:
    index_code = _symbol_from_filename(path, "U")
    for row_number, row in _read_csv_rows(path):
        yield db.IndexBarRow(
            index_code=index_code,
            timestamp=_timestamp_from_daishin_fields(row["date"], row["time"], path=path, row_number=row_number),
            open=_required_decimal(row, "open", path=path, row_number=row_number),
            high=_required_decimal(row, "high", path=path, row_number=row_number),
            low=_required_decimal(row, "low", path=path, row_number=row_number),
            close=_required_decimal(row, "close", path=path, row_number=row_number),
            volume=_required_int(row, "volume", path=path, row_number=row_number),
            data_origin=config.data_origin,
            source=config.source,
            vendor=config.vendor,
            source_run_id=options.source_run_id,
            import_batch_id=options.import_batch_id,
            schema_version=options.schema_version,
            raw_payload=_raw_payload(path, row_number, row),
        )


def _iter_index_bars_for_files(
    paths: Iterable[Path],
    *,
    config: ArtifactClassConfig,
    options: BulkImportOptions,
) -> Iterator[db.IndexBarRow]:
    for path in paths:
        yield from _iter_index_bars(path, config=config, options=options)


def _read_csv_rows(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no CSV header")
        normalized = tuple((field or "").strip().lower() for field in reader.fieldnames)
        missing = [field for field in CSV_FIELDS if field not in normalized]
        if missing:
            raise ValueError(f"{path} missing required CSV columns: {', '.join(missing)}")
        for row_number, row in enumerate(reader, start=2):
            yield row_number, {
                (key or "").strip().lower(): (value or "").strip()
                for key, value in row.items()
            }


def _select_files(root: Path, file_prefix: str, limit_files: int | None) -> tuple[list[Path], int]:
    files = list(_discover_files(root, file_prefix))
    if limit_files is None:
        return files, len(files)
    return files[:limit_files], len(files)


def _discover_files(root: Path, file_prefix: str) -> Iterator[Path]:
    if not root.exists():
        raise ValueError(f"artifact root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"artifact root is not a directory: {root}")
    for month_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if len(month_dir.name) != 6 or not month_dir.name.isdigit():
            continue
        yield from sorted(month_dir.glob(f"{file_prefix}*.csv"))


def _timestamp_from_daishin_fields(value_date: str, value_time: str, *, path: Path, row_number: int) -> datetime:
    parsed_date = _parse_date(value_date, path=path, row_number=row_number)
    token = _normalize_time_token(value_time)
    try:
        parsed_time = time(int(token[:2]), int(token[2:4]), int(token[4:6]))
    except ValueError as exc:
        raise ValueError(f"{path}:{row_number} invalid time value: {value_time!r}") from exc
    return datetime.combine(parsed_date, parsed_time, tzinfo=KST)


def _parse_date(value: str, *, path: Path, row_number: int) -> date:
    token = value.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"{path}:{row_number} invalid date value: {value!r}; expected YYYYMMDD or YYYY-MM-DD")


def _normalize_time_token(value: str) -> str:
    token = value.strip()
    if token in {"0", "0000", "000000"}:
        return "000000"
    if ":" in token:
        parts = token.split(":")
        if len(parts) == 2:
            hour, minute = parts
            second = "00"
        elif len(parts) == 3:
            hour, minute, second = parts
        else:
            raise ValueError(f"invalid time value: {value!r}")
        if not (hour.isdigit() and minute.isdigit() and second.isdigit()):
            raise ValueError(f"invalid time value: {value!r}")
        return f"{int(hour):02d}{int(minute):02d}{int(second):02d}"
    if not token.isdigit():
        raise ValueError(f"invalid time value: {value!r}")
    if len(token) in {3, 4}:
        return f"{int(token):04d}00"
    if len(token) == 6:
        return token
    raise ValueError(f"invalid time value: {value!r}; expected HHMM, HHMMSS, HH:MM, HH:MM:SS, or 0")


def _required_decimal(row: dict[str, str], field: str, *, path: Path, row_number: int) -> Decimal:
    value = row.get(field, "")
    if value == "":
        raise ValueError(f"{path}:{row_number} missing required decimal column {field}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{path}:{row_number} invalid decimal in {field}: {value!r}") from exc


def _optional_decimal(row: dict[str, str], field: str, *, path: Path, row_number: int) -> Decimal | None:
    value = row.get(field, "")
    if value == "":
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{path}:{row_number} invalid decimal in {field}: {value!r}") from exc


def _required_int(row: dict[str, str], field: str, *, path: Path, row_number: int) -> int:
    value = _optional_int(row, field, path=path, row_number=row_number)
    if value is None:
        raise ValueError(f"{path}:{row_number} missing required integer column {field}")
    return value


def _optional_int(row: dict[str, str], field: str, *, path: Path, row_number: int) -> int | None:
    value = row.get(field, "")
    if value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{path}:{row_number} invalid integer in {field}: {value!r}") from exc


def _symbol_from_filename(path: Path, expected_prefix: str) -> str:
    symbol = path.stem
    if not symbol.startswith(expected_prefix):
        raise ValueError(f"{path} filename must start with {expected_prefix!r}")
    return symbol


def _raw_payload(path: Path, row_number: int, row: dict[str, str]) -> dict[str, object]:
    return {
        "path": str(path),
        "row_number": row_number,
        "row": row,
    }


def _chunked(rows: Iterable[object], batch_size: int) -> Iterator[list[object]]:
    chunk = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= batch_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _report(
    config: ArtifactClassConfig,
    options: BulkImportOptions,
    files_matched: int,
    files_selected: int,
    rows_read: int,
    rows_inserted_or_updated: int,
    rows_inserted: int,
    rows_updated: int,
    canonical_rows_refreshed: int,
    distinct_key_count: int,
    duplicate_input_rows: int,
) -> ArtifactClassReport:
    return ArtifactClassReport(
        artifact_class=config.name,
        root=str(config.root),
        source=config.source,
        vendor=config.vendor,
        data_origin=config.data_origin,
        dry_run=options.dry_run,
        limit_files=options.limit_files,
        files_matched=files_matched,
        files_selected=files_selected,
        rows_read=rows_read,
        rows_inserted_or_updated=rows_inserted_or_updated,
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
        canonical_rows_refreshed=canonical_rows_refreshed,
        distinct_key_count=distinct_key_count,
        duplicate_input_rows=duplicate_input_rows,
    )


def _normalize_include(include: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item.strip() for item in include if item.strip()))
    unknown = sorted(set(normalized) - INCLUDE_CHOICES)
    if unknown:
        allowed = ", ".join(sorted(INCLUDE_CHOICES))
        raise ValueError(f"include contains unsupported artifact classes {unknown}; allowed: {allowed}")
    return normalized


def _minute_config(root: Path) -> ArtifactClassConfig:
    return ArtifactClassConfig(
        name="minute",
        root=root,
        file_prefix="A",
        source=MINUTE_SOURCE,
        vendor=MINUTE_VENDOR,
        data_origin=MINUTE_DATA_ORIGIN,
    )


def _daily_config(root: Path) -> ArtifactClassConfig:
    return ArtifactClassConfig(
        name="daily",
        root=root,
        file_prefix="A",
        source=DAILY_SOURCE,
        vendor=DAILY_VENDOR,
        data_origin=DAILY_DATA_ORIGIN,
    )


def _index_config(root: Path) -> ArtifactClassConfig:
    return ArtifactClassConfig(
        name="index",
        root=root,
        file_prefix="U",
        source=INDEX_SOURCE,
        vendor="daishin",
        data_origin="index-minute-backfill",
    )
