from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from zurini.market import Bar

DATA_ORIGIN_LEGACY_MINUTE_BACKFILL = "legacy-minute-backfill"
DATA_ORIGIN_FIELD_OBSERVATION = "field-observation"

ALLOWED_DATA_ORIGINS = frozenset(
    {
        DATA_ORIGIN_LEGACY_MINUTE_BACKFILL,
        DATA_ORIGIN_FIELD_OBSERVATION,
    }
)

ALLOWED_INTERVALS_BY_DATA_ORIGIN = {
    DATA_ORIGIN_LEGACY_MINUTE_BACKFILL: frozenset({"1m"}),
    DATA_ORIGIN_FIELD_OBSERVATION: frozenset({"1m"}),
}


@dataclass(frozen=True)
class ResearchMinuteRow:
    symbol: str
    timestamp: datetime
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None
    value: Decimal | None
    bid_ask_ratio: Decimal | None
    traded_value: Decimal | None
    action: str | None
    passed: bool | None
    rank: int | None
    reason: str | None
    score: Decimal | None
    strategy_group: str | None
    input_flags: tuple[str, ...]
    data_origin: str
    raw_payload: dict[str, object] | None
    source: str
    vendor: str
    source_run_id: str
    import_batch_id: str
    schema_version: str
    quality_flags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        for key in ("open", "high", "low", "close", "value", "bid_ask_ratio", "traded_value", "score"):
            value = payload[key]
            if isinstance(value, Decimal):
                payload[key] = str(value)
        payload["input_flags"] = list(self.input_flags)
        payload["quality_flags"] = list(self.quality_flags)
        return payload


@dataclass(frozen=True)
class CanonicalMinuteSelection:
    row: ResearchMinuteRow
    source_count: int
    conflict_flags: tuple[str, ...] = ()

    def as_bar(self) -> Bar:
        return Bar(
            symbol=self.row.symbol,
            timestamp=self.row.timestamp,
            open=self.row.open,
            high=self.row.high,
            low=self.row.low,
            close=self.row.close,
            volume=self.row.volume or 0,
            value=self.row.value or Decimal("0"),
            source=f"{self.row.vendor}:{self.row.source}",
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "row": self.row.as_dict(),
            "source_count": self.source_count,
            "conflict_flags": list(self.conflict_flags),
        }


def normalize_research_minute_row(
    *,
    symbol: str,
    timestamp: datetime,
    open_price: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: int | None,
    value: Decimal | None,
    source: str,
    vendor: str,
    source_run_id: str,
    import_batch_id: str,
    bid_ask_ratio: Decimal | None = None,
    traded_value: Decimal | None = None,
    action: str | None = None,
    passed: bool | None = None,
    rank: int | None = None,
    reason: str | None = None,
    score: Decimal | None = None,
    strategy_group: str | None = None,
    input_flags: tuple[str, ...] = (),
    data_origin: str | None = None,
    raw_payload: dict[str, object] | None = None,
    schema_version: str = "research-minute-v1",
    interval: str | None = None,
    quality_flags: tuple[str, ...] = (),
) -> ResearchMinuteRow:
    normalized_origin = normalize_data_origin(data_origin, source=source, vendor=vendor)
    normalized_interval = normalize_interval(interval, data_origin=normalized_origin)
    flags = list(quality_flags)
    if volume is None:
        flags.append("volume_missing")
    if value is None:
        flags.append("value_missing")
    if bid_ask_ratio is None:
        flags.append("bid_ask_ratio_missing")
    if source.startswith("kis") and (volume is None or value is None):
        flags.append("kis_row_degraded")
    if normalized_origin == DATA_ORIGIN_LEGACY_MINUTE_BACKFILL or source.startswith("legacy"):
        if bid_ask_ratio is None:
            flags.append("legacy_operating_field_missing")
    return ResearchMinuteRow(
        symbol=symbol,
        timestamp=timestamp,
        interval=normalized_interval,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        value=value,
        bid_ask_ratio=bid_ask_ratio,
        traded_value=traded_value,
        action=action,
        passed=passed,
        rank=rank,
        reason=reason,
        score=score,
        strategy_group=strategy_group,
        input_flags=tuple(dict.fromkeys(input_flags)),
        data_origin=normalized_origin,
        raw_payload=raw_payload,
        source=source,
        vendor=vendor,
        source_run_id=source_run_id,
        import_batch_id=import_batch_id,
        schema_version=schema_version,
        quality_flags=tuple(dict.fromkeys(flags)),
    )


def normalize_data_origin(data_origin: str | None, *, source: str, vendor: str) -> str:
    candidate = (data_origin or "").strip()
    if candidate and candidate != "unknown":
        if candidate not in ALLOWED_DATA_ORIGINS:
            allowed = ", ".join(sorted(ALLOWED_DATA_ORIGINS))
            raise ValueError(f"data_origin must be one of: {allowed}")
        return candidate

    source_key = source.lower()
    vendor_key = vendor.lower()
    if "universe" in source_key or "daily" in source_key:
        raise ValueError("daily/universe source data must use universe_daily tables, not research_minute tables")
    if source_key.startswith("legacy") or vendor_key == "daishin":
        return DATA_ORIGIN_LEGACY_MINUTE_BACKFILL
    return DATA_ORIGIN_FIELD_OBSERVATION


def normalize_interval(interval: str | None, *, data_origin: str) -> str:
    candidate = (interval or "").strip()
    if not candidate:
        candidate = "1m"
    allowed = ALLOWED_INTERVALS_BY_DATA_ORIGIN[data_origin]
    if candidate not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"interval for data_origin={data_origin} must be one of: {allowed_text}")
    return candidate


def select_canonical_minute_row(rows: list[ResearchMinuteRow]) -> CanonicalMinuteSelection:
    if not rows:
        raise ValueError("canonical minute selection requires at least one row")
    keys = {(row.symbol, row.timestamp, row.interval) for row in rows}
    if len(keys) != 1:
        raise ValueError("canonical minute selection requires one symbol/timestamp/interval key")

    ordered = sorted(rows, key=_source_priority)
    selected = ordered[0]
    selected_signature = _bar_signature(selected)
    conflicts = []
    if any(
        _bar_signature(row) != selected_signature
        for row in ordered[1:]
    ):
        conflicts.append("source_overlap_conflict")
    return CanonicalMinuteSelection(
        row=selected,
        source_count=len(rows),
        conflict_flags=tuple(conflicts),
    )


def rolling_two_year_cutoff(latest_timestamp: datetime, *, days: int = 730) -> datetime:
    return latest_timestamp - timedelta(days=days)


def rows_within_rolling_window(rows: list[ResearchMinuteRow], *, latest_timestamp: datetime) -> list[ResearchMinuteRow]:
    cutoff = rolling_two_year_cutoff(latest_timestamp)
    return [row for row in rows if row.timestamp >= cutoff]


def _source_priority(row: ResearchMinuteRow) -> tuple[int, str, str]:
    source = row.source.lower()
    vendor = row.vendor.lower()
    contract_valid = row.volume is not None and row.value is not None and "kis_row_degraded" not in row.quality_flags
    if source.startswith("kis") or vendor == "kis":
        return (0 if contract_valid else 2, vendor, source)
    return (1 if contract_valid else 3, vendor, source)


def _bar_signature(row: ResearchMinuteRow) -> tuple[object, ...]:
    return (
        row.open,
        row.high,
        row.low,
        row.close,
        row.volume,
        row.value,
        row.bid_ask_ratio,
        row.traded_value,
        row.action,
        row.passed,
        row.rank,
        row.reason,
        row.score,
        row.strategy_group,
        row.input_flags,
    )
