from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import random
from typing import Any

from zurini.data.dummy import KST, money
from zurini.data.validation import BarValidationError, validate_bars
from zurini.market import Bar

INDEX_CODES = ("KOSPI", "KOSDAQ", "KOSPI200", "NASDAQ_FUTURES")


@dataclass(frozen=True)
class SymbolMetadata:
    symbol: str
    name: str
    market: str
    section_kind: str = "synthetic"
    status_kind: str = "normal"
    control_kind: str = ""
    supervision_kind: str = ""
    source: str = "phase15-dummy"


@dataclass(frozen=True)
class LargeDummyProfile:
    name: str
    symbol_count: int
    logical_months: int
    trading_days_per_month: int
    minutes_per_day: int
    start_date: str = "2024-01-02"
    seed: int = 1515
    source: str = "phase15-dummy"
    index_codes: tuple[str, ...] = INDEX_CODES

    @property
    def trading_day_count(self) -> int:
        return self.logical_months * self.trading_days_per_month

    @property
    def market_bar_count(self) -> int:
        return self.symbol_count * self.trading_day_count * self.minutes_per_day

    @property
    def index_bar_count(self) -> int:
        return len(self.index_codes) * self.trading_day_count * self.minutes_per_day

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trading_day_count"] = self.trading_day_count
        payload["market_bar_count"] = self.market_bar_count
        payload["index_bar_count"] = self.index_bar_count
        payload["logical_period"] = f"{self.logical_months} months"
        payload["time_acceleration"] = (
            "logical months are represented by a configured number of synthetic "
            "trading days and minutes per day; no real-time waiting is used"
        )
        return payload


PROFILES: dict[str, LargeDummyProfile] = {
    "smoke": LargeDummyProfile(
        name="smoke",
        symbol_count=8,
        logical_months=24,
        trading_days_per_month=1,
        minutes_per_day=12,
    ),
    "rehearsal": LargeDummyProfile(
        name="rehearsal",
        symbol_count=50,
        logical_months=24,
        trading_days_per_month=2,
        minutes_per_day=60,
    ),
    "scale": LargeDummyProfile(
        name="scale",
        symbol_count=200,
        logical_months=24,
        trading_days_per_month=3,
        minutes_per_day=120,
    ),
}


def get_large_dummy_profile(name: str) -> LargeDummyProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown large dummy profile: {name}") from exc


def generate_symbol_metadata(profile: LargeDummyProfile) -> list[SymbolMetadata]:
    return [
        SymbolMetadata(
            symbol=f"ZRN{index:04d}",
            name=f"Zurini Synthetic {index:04d}",
            market="KIS_FUTURE_REHEARSAL",
            source=profile.source,
        )
        for index in range(1, profile.symbol_count + 1)
    ]


def iter_large_dummy_market_bars(
    profile: LargeDummyProfile,
    *,
    include_quality_anomalies: bool = False,
) -> Iterator[Bar]:
    if include_quality_anomalies:
        _require_anomaly_capacity(profile)
    metadata = generate_symbol_metadata(profile)
    for symbol_index, item in enumerate(metadata, start=1):
        yield from _iter_symbol_bars(
            profile=profile,
            symbol=item.symbol,
            ordinal=symbol_index,
            include_quality_anomalies=include_quality_anomalies,
        )


def iter_large_dummy_index_bars(profile: LargeDummyProfile) -> Iterator[Bar]:
    for index_ordinal, index_code in enumerate(profile.index_codes, start=1):
        yield from _iter_symbol_bars(
            profile=profile,
            symbol=index_code,
            ordinal=10_000 + index_ordinal,
            include_quality_anomalies=False,
            base_price=Decimal("2500") + Decimal(index_ordinal * 250),
            base_volume=0,
            source="phase15-index-dummy",
        )


def build_quality_anomaly_fixtures(profile: LargeDummyProfile) -> dict[str, Any]:
    _require_anomaly_capacity(profile)
    clean = list(
        _iter_symbol_bars(
            profile=profile,
            symbol="ANOMALY",
            ordinal=1,
            include_quality_anomalies=False,
        )
    )
    duplicate = [clean[0], clean[0]]
    invalid_ohlc = replace(clean[1], high=clean[1].low - Decimal("1"))
    findings: dict[str, Any] = {
        "gap_fixture_minutes_missing": 1,
        "zero_volume_fixture_is_schema_valid": False,
        "duplicate_timestamp_error": "",
        "invalid_ohlc_error": "",
    }

    with_gap_and_zero_volume = list(
        _iter_symbol_bars(
            profile=profile,
            symbol="ANOMALY",
            ordinal=1,
            include_quality_anomalies=True,
        )
    )
    findings["gap_fixture_row_count"] = len(with_gap_and_zero_volume)
    findings["zero_volume_fixture_is_schema_valid"] = any(bar.volume == 0 for bar in with_gap_and_zero_volume)
    validate_bars(with_gap_and_zero_volume)

    for key, bars in {
        "duplicate_timestamp_error": duplicate,
        "invalid_ohlc_error": [invalid_ohlc],
    }.items():
        try:
            validate_bars(bars)
        except BarValidationError as exc:
            findings[key] = str(exc)
    return findings


def summarize_large_dummy_profile(
    profile: LargeDummyProfile,
    *,
    include_quality_anomalies: bool = False,
    inserted_market_rows: int = 0,
    inserted_index_rows: int = 0,
    inserted_metadata_rows: int = 0,
    backtest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "purpose": "phase-1.5 synthetic system rehearsal; not strategy profitability evidence",
        "real_data_source_boundary": (
            "promoted stage/API data source is Korea Investment Securities only; "
            "two-year historical raw acquisition may use Daishin Securities CYBOS "
            "only as unpromoted read-only intake"
        ),
        "resource_target": {
            "cpu": "13th Gen Intel Core i5-13420H",
            "ram_gb": 16,
            "gpu_mb": 128,
        },
        "profile": profile.as_dict(),
        "inserted_rows": {
            "market_bars": inserted_market_rows,
            "index_bars": inserted_index_rows,
            "symbol_metadata": inserted_metadata_rows,
        },
        "quality_anomalies": build_quality_anomaly_fixtures(profile) if include_quality_anomalies else {},
        "backtest": backtest or {},
    }
    return payload


def _iter_symbol_bars(
    *,
    profile: LargeDummyProfile,
    symbol: str,
    ordinal: int,
    include_quality_anomalies: bool,
    base_price: Decimal | None = None,
    base_volume: int = 1_000,
    source: str | None = None,
) -> Iterator[Bar]:
    rng = random.Random(profile.seed + ordinal)
    start_day = date.fromisoformat(profile.start_date)
    price = money(base_price or (Decimal("10000") + Decimal(ordinal * 7)))
    produced = 0
    gap_minute_index, zero_volume_minute_index = _quality_anomaly_positions(profile.minutes_per_day)
    for day_index in range(profile.trading_day_count):
        current_day = start_day + timedelta(days=day_index)
        month_slot = day_index // max(profile.trading_days_per_month, 1)
        day_start = datetime.combine(current_day, datetime.min.time()).replace(hour=9, tzinfo=KST)
        for minute_index in range(profile.minutes_per_day):
            if (
                include_quality_anomalies
                and ordinal == 1
                and day_index == 0
                and minute_index == gap_minute_index
            ):
                continue
            drift = Decimal(str(rng.uniform(-0.0010, 0.0014))) + Decimal(month_slot) * Decimal("0.000005")
            close = money(price * (Decimal("1") + drift))
            open_ = price
            spread = money(max(open_, close) * Decimal("0.0012"))
            high = money(max(open_, close) + spread)
            low = money(min(open_, close) - spread)
            volume = base_volume + ordinal * 3 + minute_index + rng.randint(0, 20)
            if base_volume == 0:
                volume = 0
            if (
                include_quality_anomalies
                and ordinal == 1
                and day_index == 0
                and minute_index == zero_volume_minute_index
            ):
                volume = 0
            yield Bar(
                symbol=symbol,
                timestamp=day_start + timedelta(minutes=minute_index),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                value=money(close * Decimal(volume)),
                source=source or profile.source,
            )
            price = close
            produced += 1

    if produced == 0:
        raise ValueError("large dummy profile generated no rows")


def _quality_anomaly_positions(minutes_per_day: int) -> tuple[int, int]:
    if minutes_per_day <= 0:
        return 0, 0
    gap_minute_index = min(3, minutes_per_day - 1)
    zero_volume_minute_index = min(5, minutes_per_day - 1)
    if zero_volume_minute_index == gap_minute_index and minutes_per_day > 1:
        zero_volume_minute_index = gap_minute_index - 1
    return gap_minute_index, zero_volume_minute_index


def _require_anomaly_capacity(profile: LargeDummyProfile) -> None:
    if profile.minutes_per_day < 2:
        raise ValueError("quality anomaly fixtures require at least 2 synthetic minutes per day")
