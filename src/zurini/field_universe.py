from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from zurini.market import Bar

KST = ZoneInfo("Asia/Seoul")
REQUIRED_MINUTE_COLUMNS = {"date", "time", "open", "high", "low", "close", "volume"}


@dataclass(frozen=True)
class FieldUniverseMember:
    symbol: str
    kis_symbol: str
    included: bool
    reason: str
    prior_close: Decimal | None
    sma: Decimal | None
    average_value: Decimal | None
    atr_ratio: Decimal | None
    observed_days: int
    source: str


@dataclass(frozen=True)
class FieldUniverseReport:
    universe_id: str
    target_date: date
    generated_at: datetime
    mode: str
    construction_rule: str
    prior_only_cutoff: date
    included_symbols: tuple[str, ...]
    kis_symbols: tuple[str, ...]
    excluded_symbols: tuple[tuple[str, str], ...]
    members: tuple[FieldUniverseMember, ...]
    parameters: dict[str, Any]
    safety_boundary: str
    latest_prior_date: date | None = None
    latest_prior_lag_days: int | None = None
    source_date_lag_days: int | None = None
    source_fresh: bool = True

    def summary(self) -> dict[str, Any]:
        return {
            "universe_id": self.universe_id,
            "target_date": self.target_date,
            "mode": self.mode,
            "included_count": len(self.included_symbols),
            "excluded_count": len(self.excluded_symbols),
            "ready_for_broker_or_order_transmission": False,
            "latest_prior_date": self.latest_prior_date,
            "latest_prior_lag_days": self.latest_prior_lag_days,
            "source_date_lag_days": self.source_date_lag_days,
            "source_fresh": self.source_fresh,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": _json_safe(self.summary()),
            "report": _json_safe(asdict(self)),
        }


def build_prior_only_field_universe(
    bars: list[Bar],
    *,
    target_date: date,
    universe_id: str = "field-u1-prior-only",
    value_window: int = 5,
    sma_window: int = 20,
    atr_window: int = 14,
    min_average_value: Decimal = Decimal("50000000000"),
    min_atr_ratio: Decimal = Decimal("0.03"),
    require_close_above_sma: bool = True,
    max_symbols: int | None = 100,
    min_prior_trading_days: int = 60,
    max_prior_data_lag_days: int | None = None,
    expected_prior_date: date | None = None,
) -> FieldUniverseReport:
    if value_window <= 0 or sma_window <= 0 or atr_window <= 0:
        raise ValueError("universe windows must be positive")
    if max_symbols is not None and max_symbols <= 0:
        raise ValueError("max_symbols must be positive")
    if min_prior_trading_days <= 0:
        raise ValueError("min_prior_trading_days must be positive")
    if max_prior_data_lag_days is not None and max_prior_data_lag_days < 0:
        raise ValueError("max_prior_data_lag_days must be non-negative")

    grouped: dict[str, list[Bar]] = {}
    prior_bars = [bar for bar in bars if _bar_date(bar.timestamp) < target_date]
    for bar in prior_bars:
        grouped.setdefault(bar.symbol, []).append(bar)
    sorted_grouped = {
        symbol: sorted(symbol_bars, key=lambda item: item.timestamp)
        for symbol, symbol_bars in sorted(grouped.items())
    }
    latest_prior_by_symbol = {
        symbol: max((_bar_date(bar.timestamp) for bar in symbol_bars), default=None)
        for symbol, symbol_bars in sorted_grouped.items()
    }
    lag_days_by_symbol = {
        symbol: (target_date - latest_prior_date).days if latest_prior_date is not None else None
        for symbol, latest_prior_date in latest_prior_by_symbol.items()
    }
    latest_prior_date = max(
        (latest_date for latest_date in latest_prior_by_symbol.values() if latest_date is not None),
        default=None,
    )
    latest_prior_lag_days = (target_date - latest_prior_date).days if latest_prior_date is not None else None
    source_date_lag_days = max(
        (lag_days for lag_days in lag_days_by_symbol.values() if lag_days is not None),
        default=None,
    )
    stale_source_symbols = {
        symbol
        for symbol, lag_days in lag_days_by_symbol.items()
        if lag_days is None or (
            max_prior_data_lag_days is not None and lag_days > max_prior_data_lag_days
        )
    }
    unexpected_prior_symbols = {
        symbol
        for symbol, latest_prior_date in latest_prior_by_symbol.items()
        if expected_prior_date is not None and latest_prior_date != expected_prior_date
    }
    if (
        (
            max_prior_data_lag_days is not None
            and (source_date_lag_days is None or stale_source_symbols)
        )
        or unexpected_prior_symbols
    ):
        members = tuple(
            _excluded(
                symbol,
                _kis_symbol(symbol),
                (
                    "source-data-unexpected-prior-date"
                    if symbol in unexpected_prior_symbols
                    else "source-data-stale"
                    if symbol in stale_source_symbols
                    else "source-fleet-stale-fail-closed"
                ),
                len(_daily_bars(symbol_bars)),
                symbol_bars[-1].source if symbol_bars else "",
            )
            for symbol, symbol_bars in sorted_grouped.items()
        )
        return FieldUniverseReport(
            universe_id=universe_id,
            target_date=target_date,
            generated_at=datetime.now(timezone.utc),
            mode="prior-only-read-only",
            construction_rule="U1: common numeric symbol, prior average value, prior close above SMA, ATR ratio",
            prior_only_cutoff=target_date,
            included_symbols=(),
            kis_symbols=(),
            excluded_symbols=tuple((member.symbol, member.reason) for member in members),
            members=members,
            parameters={
                "value_window": value_window,
                "sma_window": sma_window,
                "atr_window": atr_window,
                "min_average_value": str(min_average_value),
                "min_atr_ratio": str(min_atr_ratio),
                "require_close_above_sma": require_close_above_sma,
                "max_symbols": max_symbols,
                "min_prior_trading_days": min_prior_trading_days,
                "max_prior_data_lag_days": max_prior_data_lag_days,
                "expected_prior_date": expected_prior_date,
            },
            safety_boundary="read-only prior-data universe; no broker order, account, balance, credential, or real-fill calls",
            latest_prior_date=latest_prior_date,
            latest_prior_lag_days=latest_prior_lag_days,
            source_date_lag_days=source_date_lag_days,
            source_fresh=False,
        )

    members = [
        _build_member(
            symbol=symbol,
            bars=symbol_bars,
            value_window=value_window,
            sma_window=sma_window,
            atr_window=atr_window,
            min_average_value=min_average_value,
            min_atr_ratio=min_atr_ratio,
            require_close_above_sma=require_close_above_sma,
            min_prior_trading_days=min_prior_trading_days,
        )
        for symbol, symbol_bars in sorted_grouped.items()
    ]
    included = [member for member in members if member.included]
    included.sort(
        key=lambda member: (
            -(member.average_value or Decimal("0")),
            -(member.atr_ratio or Decimal("0")),
            member.symbol,
        )
    )
    if max_symbols is not None:
        included_symbols_set = {member.symbol for member in included[:max_symbols]}
        members = tuple(
            member
            if not member.included or member.symbol in included_symbols_set
            else FieldUniverseMember(
                symbol=member.symbol,
                kis_symbol=member.kis_symbol,
                included=False,
                reason="max-symbols-rank-cutoff",
                prior_close=member.prior_close,
                sma=member.sma,
                average_value=member.average_value,
                atr_ratio=member.atr_ratio,
                observed_days=member.observed_days,
                source=member.source,
            )
            for member in members
        )
    else:
        members = tuple(members)

    included_members = tuple(member for member in members if member.included)
    excluded_symbols = tuple((member.symbol, member.reason) for member in members if not member.included)
    return FieldUniverseReport(
        universe_id=universe_id,
        target_date=target_date,
        generated_at=datetime.now(timezone.utc),
        mode="prior-only-read-only",
        construction_rule="U1: common numeric symbol, prior average value, prior close above SMA, ATR ratio",
        prior_only_cutoff=target_date,
        included_symbols=tuple(member.symbol for member in included_members),
        kis_symbols=tuple(member.kis_symbol for member in included_members),
        excluded_symbols=excluded_symbols,
        members=members,
        parameters={
            "value_window": value_window,
            "sma_window": sma_window,
            "atr_window": atr_window,
            "min_average_value": str(min_average_value),
            "min_atr_ratio": str(min_atr_ratio),
            "require_close_above_sma": require_close_above_sma,
            "max_symbols": max_symbols,
            "min_prior_trading_days": min_prior_trading_days,
            "max_prior_data_lag_days": max_prior_data_lag_days,
            "expected_prior_date": expected_prior_date,
        },
        safety_boundary="read-only prior-data universe; no broker order, account, balance, credential, or real-fill calls",
        latest_prior_date=latest_prior_date,
        latest_prior_lag_days=latest_prior_lag_days,
        source_date_lag_days=source_date_lag_days,
        source_fresh=True,
    )


def write_field_universe_report(report: FieldUniverseReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_kis_symbol_list(report: FieldUniverseReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(report.kis_symbols) + ("\n" if report.kis_symbols else ""), encoding="utf-8")


def load_reusable_field_universe_artifact(
    path: Path,
    *,
    target_date: date,
    expected_prior_date: date | None = None,
    max_prior_data_lag_days: int | None = None,
    as_of: datetime | None = None,
    max_artifact_age_minutes: int | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"standby artifact not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"standby artifact is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("standby artifact must be a JSON object")

    summary = payload.get("summary")
    report = payload.get("report")
    if not isinstance(summary, dict) or not isinstance(report, dict):
        raise ValueError("standby artifact must contain summary and report objects")
    expected_target_date = target_date.isoformat()
    if report.get("target_date") != expected_target_date:
        raise ValueError("standby artifact target_date does not match requested target date")
    if summary.get("target_date") != expected_target_date:
        raise ValueError("standby artifact summary target_date does not match requested target date")
    if report.get("mode") != "prior-only-read-only":
        raise ValueError("standby artifact mode must be prior-only-read-only")
    if summary.get("ready_for_broker_or_order_transmission") is not False:
        raise ValueError("standby artifact must remain broker/order blocked")

    safety_boundary = str(report.get("safety_boundary") or "").lower()
    if "read-only" not in safety_boundary:
        raise ValueError("standby artifact safety boundary must be read-only")
    if summary.get("source_fresh") is not True or report.get("source_fresh") is not True:
        raise ValueError("standby artifact source freshness must be true")
    if summary.get("latest_prior_date") is None or report.get("latest_prior_date") is None:
        raise ValueError("standby artifact must include latest_prior_date freshness evidence")
    if summary.get("latest_prior_lag_days") is None or report.get("latest_prior_lag_days") is None:
        raise ValueError("standby artifact must include latest_prior_lag_days freshness evidence")
    if summary.get("source_date_lag_days") is None or report.get("source_date_lag_days") is None:
        raise ValueError("standby artifact must include source_date_lag_days freshness evidence")
    latest_prior_date = date.fromisoformat(str(report["latest_prior_date"]))
    if expected_prior_date is not None and latest_prior_date != expected_prior_date:
        raise ValueError("standby artifact latest_prior_date does not match expected prior date")
    latest_prior_lag_days = int(report["latest_prior_lag_days"])
    expected_latest_prior_lag_days = (target_date - latest_prior_date).days
    if latest_prior_lag_days != expected_latest_prior_lag_days:
        raise ValueError("standby artifact latest_prior_lag_days does not match target/latest prior dates")
    source_date_lag_days = int(report["source_date_lag_days"])
    if max_prior_data_lag_days is not None and source_date_lag_days > max_prior_data_lag_days:
        raise ValueError("standby artifact source_date_lag_days exceeds active freshness policy")
    generated_raw = report.get("generated_at")
    if max_artifact_age_minutes is not None:
        if max_artifact_age_minutes <= 0:
            raise ValueError("max_artifact_age_minutes must be positive")
        if not generated_raw:
            raise ValueError("standby artifact must include generated_at freshness evidence")
        generated_at = datetime.fromisoformat(str(generated_raw).replace("Z", "+00:00"))
        reference_at = as_of or datetime.now(timezone.utc)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        if reference_at.tzinfo is None:
            reference_at = reference_at.replace(tzinfo=timezone.utc)
        if generated_at > reference_at + timedelta(seconds=60):
            raise ValueError("standby artifact generated_at is after as-of")
        if reference_at - generated_at > timedelta(minutes=max_artifact_age_minutes):
            raise ValueError("standby artifact generated_at is stale")

    included_symbols = _string_list(report.get("included_symbols"), "included_symbols")
    kis_symbols = _string_list(report.get("kis_symbols"), "kis_symbols")
    if not included_symbols or not kis_symbols:
        raise ValueError("standby artifact must include non-empty included_symbols and kis_symbols")
    if len(included_symbols) != len(kis_symbols):
        raise ValueError("standby artifact included_symbols and kis_symbols must be aligned")
    if any(not re.fullmatch(r"\d{6}", symbol) for symbol in kis_symbols):
        raise ValueError("standby artifact kis_symbols must be six-digit KIS symbols")
    return payload


def write_reused_field_universe_artifact(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_reused_kis_symbol_list(payload: dict[str, Any], output: Path) -> None:
    report = payload["report"]
    kis_symbols = _string_list(report.get("kis_symbols"), "kis_symbols")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(kis_symbols) + "\n", encoding="utf-8")


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"standby artifact {field} must be a string list")
    return value


def load_prior_daily_bars_from_minute_csvs(
    paths: list[Path],
    *,
    target_date: date,
    source: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[Bar]:
    """Load minute CSVs as prior-day daily OHLCV bars for universe screening."""
    bars: list[Bar] = []
    for path in paths:
        symbol = path.stem
        minute_bars_by_day: dict[date, list[Bar]] = {}
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = sorted(REQUIRED_MINUTE_COLUMNS.difference(reader.fieldnames or []))
            if missing:
                raise ValueError(f"missing required CSV columns in {path}: {', '.join(missing)}")
            for row in reader:
                bar = _minute_row_to_bar(row, symbol=symbol, source=source)
                bar_date = _bar_date(bar.timestamp)
                if bar_date >= target_date:
                    continue
                if start_date is not None and bar_date < start_date:
                    continue
                if end_date is not None and bar_date > end_date:
                    continue
                minute_bars_by_day.setdefault(bar_date, []).append(bar)
        bars.extend(_aggregate_daily_bar(minute_bars_by_day[item]) for item in sorted(minute_bars_by_day))
    return bars


def _build_member(
    *,
    symbol: str,
    bars: list[Bar],
    value_window: int,
    sma_window: int,
    atr_window: int,
    min_average_value: Decimal,
    min_atr_ratio: Decimal,
    require_close_above_sma: bool,
    min_prior_trading_days: int,
) -> FieldUniverseMember:
    daily = _daily_bars(bars)
    kis_symbol = _kis_symbol(symbol)
    source = bars[-1].source if bars else ""
    if not re.fullmatch(r"A?\d{6}", symbol):
        return _excluded(symbol, kis_symbol, "non-common-symbol-format", len(daily), source)
    if len(daily) < min_prior_trading_days:
        return _excluded(symbol, kis_symbol, "insufficient-prior-source-days", len(daily), source)
    if len(daily) < max(value_window, sma_window, atr_window):
        return _excluded(symbol, kis_symbol, "insufficient-prior-history", len(daily), source)

    closes = [item.close for item in daily]
    values = [item.value for item in daily]
    average_value = sum(values[-value_window:], Decimal("0")) / Decimal(value_window)
    sma = sum(closes[-sma_window:], Decimal("0")) / Decimal(sma_window)
    prior_close = closes[-1]
    atr = _atr(daily[-atr_window:])
    atr_ratio = Decimal("0") if prior_close == 0 else atr / prior_close

    if average_value < min_average_value:
        return _excluded(
            symbol,
            kis_symbol,
            "average-value-below-threshold",
            len(daily),
            source,
            prior_close=prior_close,
            sma=sma,
            average_value=average_value,
            atr_ratio=atr_ratio,
        )
    if require_close_above_sma and prior_close <= sma:
        return _excluded(
            symbol,
            kis_symbol,
            "prior-close-not-above-sma",
            len(daily),
            source,
            prior_close=prior_close,
            sma=sma,
            average_value=average_value,
            atr_ratio=atr_ratio,
        )
    if atr_ratio < min_atr_ratio:
        return _excluded(
            symbol,
            kis_symbol,
            "atr-ratio-below-threshold",
            len(daily),
            source,
            prior_close=prior_close,
            sma=sma,
            average_value=average_value,
            atr_ratio=atr_ratio,
        )

    return FieldUniverseMember(
        symbol=symbol,
        kis_symbol=kis_symbol,
        included=True,
        reason="included",
        prior_close=prior_close,
        sma=sma,
        average_value=average_value,
        atr_ratio=atr_ratio,
        observed_days=len(daily),
        source=source,
    )


def _daily_bars(bars: list[Bar]) -> list[Bar]:
    bars_by_day: dict[date, list[Bar]] = {}
    for bar in bars:
        bars_by_day.setdefault(_bar_date(bar.timestamp), []).append(bar)
    return [_aggregate_daily_bar(bars_by_day[item]) for item in sorted(bars_by_day)]


def _bar_date(timestamp: datetime) -> date:
    if timestamp.tzinfo is None:
        return timestamp.date()
    return timestamp.astimezone(KST).date()


def _aggregate_daily_bar(bars: list[Bar]) -> Bar:
    if not bars:
        raise ValueError("cannot aggregate empty daily bar set")
    ordered = sorted(bars, key=lambda item: item.timestamp)
    first = ordered[0]
    last = ordered[-1]
    return Bar(
        symbol=first.symbol,
        timestamp=last.timestamp,
        open=first.open,
        high=max(item.high for item in ordered),
        low=min(item.low for item in ordered),
        close=last.close,
        volume=sum(item.volume for item in ordered),
        value=sum((item.value for item in ordered), Decimal("0")),
        bid_ask_ratio=last.bid_ask_ratio,
        source=last.source,
    )


def _atr(daily: list[Bar]) -> Decimal:
    if not daily:
        return Decimal("0")
    ranges: list[Decimal] = []
    for index, item in enumerate(daily):
        previous_close = daily[index - 1].close if index > 0 else item.close
        ranges.append(max(item.high - item.low, abs(item.high - previous_close), abs(item.low - previous_close)))
    return sum(ranges, Decimal("0")) / Decimal(len(ranges))


def _excluded(
    symbol: str,
    kis_symbol: str,
    reason: str,
    observed_days: int,
    source: str,
    *,
    prior_close: Decimal | None = None,
    sma: Decimal | None = None,
    average_value: Decimal | None = None,
    atr_ratio: Decimal | None = None,
) -> FieldUniverseMember:
    return FieldUniverseMember(
        symbol=symbol,
        kis_symbol=kis_symbol,
        included=False,
        reason=reason,
        prior_close=prior_close,
        sma=sma,
        average_value=average_value,
        atr_ratio=atr_ratio,
        observed_days=observed_days,
        source=source,
    )


def _kis_symbol(symbol: str) -> str:
    return symbol[1:] if symbol.startswith("A") and len(symbol) == 7 else symbol.zfill(6)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _minute_row_to_bar(row: dict[str, str], *, symbol: str, source: str) -> Bar:
    try:
        timestamp = datetime.strptime(
            f"{str(row['date']).strip()}{str(row['time']).strip().zfill(4)}",
            "%Y%m%d%H%M",
        ).replace(tzinfo=KST)
        open_ = _money(row["open"])
        high = _money(row["high"])
        low = _money(row["low"])
        close = _money(row["close"])
        volume = int(row["volume"])
        value = _money(row["value"]) if str(row.get("value") or "").strip() else _money(close * Decimal(volume))
    except (KeyError, ValueError, ArithmeticError) as exc:
        row_id = f"{row.get('date', '')} {row.get('time', '')}".strip()
        raise ValueError(f"invalid minute CSV row for {symbol} at {row_id}: {exc}") from exc
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        value=value,
        source=source,
    )


def _money(value: Decimal | str | int) -> Decimal:
    return Decimal(str(value))
