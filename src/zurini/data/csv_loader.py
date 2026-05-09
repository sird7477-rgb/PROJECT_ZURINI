from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from zurini.data.validation import validate_bars
from zurini.market import Bar

KST = ZoneInfo("Asia/Seoul")
REQUIRED_COLUMNS = ["date", "time", "open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class CsvQualityReport:
    symbol: str
    source_path: str
    row_count: int
    duplicate_timestamp_count: int
    gap_count: int
    missing_minutes_count: int
    max_gap_minutes: int
    zero_volume_count: int
    first_timestamp: str | None
    last_timestamp: str | None
    source: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def load_daishin_minute_csv(path: Path | str, *, symbol: str | None = None, source: str = "sample") -> list[Bar]:
    """Load Daishin/CYBOS minute-bar CSV into the common market bar contract."""
    path = Path(path)
    symbol = symbol or path.stem
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames)
        bars = [_row_to_bar(row, symbol=symbol, source=source) for row in reader]
    return validate_bars(sorted(bars, key=lambda bar: (bar.symbol, bar.timestamp)))


def build_csv_quality_report(
    bars: list[Bar],
    *,
    source_path: Path | str,
    symbol: str | None = None,
    source: str = "sample",
) -> CsvQualityReport:
    source_path = Path(source_path)
    sorted_bars = sorted(bars, key=lambda bar: (bar.symbol, bar.timestamp))
    timestamps = [bar.timestamp for bar in sorted_bars]
    counts = Counter((bar.symbol, bar.timestamp) for bar in sorted_bars)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    zero_volume_count = sum(1 for bar in sorted_bars if bar.volume == 0)

    by_symbol_day: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for bar in sorted_bars:
        by_symbol_day[(bar.symbol, bar.timestamp.strftime("%Y%m%d"))].append(bar.timestamp)

    gap_count = 0
    missing_minutes_count = 0
    max_gap_minutes = 0
    for day_timestamps in by_symbol_day.values():
        ordered = sorted(day_timestamps)
        for left, right in zip(ordered, ordered[1:]):
            gap_minutes = int((right - left).total_seconds() // 60) - 1
            if gap_minutes > 0:
                gap_count += 1
                missing_minutes_count += gap_minutes
                max_gap_minutes = max(max_gap_minutes, gap_minutes)

    inferred_symbol = symbol or (sorted_bars[0].symbol if sorted_bars else source_path.stem)
    return CsvQualityReport(
        symbol=inferred_symbol,
        source_path=str(source_path),
        row_count=len(sorted_bars),
        duplicate_timestamp_count=duplicate_count,
        gap_count=gap_count,
        missing_minutes_count=missing_minutes_count,
        max_gap_minutes=max_gap_minutes,
        zero_volume_count=zero_volume_count,
        first_timestamp=timestamps[0].isoformat() if timestamps else None,
        last_timestamp=timestamps[-1].isoformat() if timestamps else None,
        source=source,
    )


def _row_to_bar(row: dict[str, str], *, symbol: str, source: str) -> Bar:
    try:
        timestamp = _parse_timestamp(row["date"], row["time"])
        open_ = _money(row["open"])
        high = _money(row["high"])
        low = _money(row["low"])
        close = _money(row["close"])
        volume = int(row["volume"])
        return Bar(
            symbol=symbol,
            timestamp=timestamp,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            value=_money(close * Decimal(volume)),
            source=source,
        )
    except (KeyError, ValueError, ArithmeticError) as exc:
        row_id = f"{row.get('date', '')} {row.get('time', '')}".strip()
        raise ValueError(f"invalid minute CSV row for {symbol} at {row_id}: {exc}") from exc


def _parse_timestamp(date_value: str, time_value: str) -> datetime:
    date_part = str(date_value).strip()
    time_part = str(time_value).strip().zfill(4)
    return datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M").replace(tzinfo=KST)


def _money(value: Decimal | str | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _require_columns(fieldnames: list[str] | None) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in (fieldnames or [])]
    if missing:
        raise ValueError(f"missing required CSV columns: {', '.join(missing)}")
