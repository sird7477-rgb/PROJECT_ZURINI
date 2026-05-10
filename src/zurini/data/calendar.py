from __future__ import annotations

import calendar as py_calendar
import json
from dataclasses import dataclass
from datetime import date, time
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_CALENDAR_VERSION = "krx-korean-equity-v1"
DEFAULT_CALENDAR_PATH = Path("data/trading-calendar/krx-korean-equity-v1.json")


@dataclass(frozen=True)
class TradingCalendar:
    version: str
    market: str
    timezone: ZoneInfo
    default_start: time
    default_end: time
    non_trading_dates: frozenset[date]
    special_sessions: dict[date, tuple[time, time, str]]
    source_note: str
    certified: bool = False

    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5 and value not in self.non_trading_dates

    def session_window_for(self, value: date) -> tuple[time, time]:
        special = self.special_sessions.get(value)
        if special:
            return special[0], special[1]
        return self.default_start, self.default_end

    def trading_days_in_month(self, yyyymm: str) -> list[date]:
        if len(yyyymm) != 6 or not yyyymm.isdigit():
            raise ValueError("yyyymm must be YYYYMM")
        year = int(yyyymm[:4])
        month = int(yyyymm[4:])
        if not 1 <= month <= 12:
            raise ValueError("yyyymm month must be 01..12")
        days = py_calendar.monthrange(year, month)[1]
        return [day for day in (date(year, month, item) for item in range(1, days + 1)) if self.is_trading_day(day)]

    def as_metadata(self) -> dict[str, str]:
        return {
            "version": self.version,
            "market": self.market,
            "timezone": str(self.timezone),
            "source_note": self.source_note,
            "certified": str(self.certified).lower(),
        }


@lru_cache(maxsize=8)
def load_trading_calendar(path: str | Path = DEFAULT_CALENDAR_PATH) -> TradingCalendar:
    calendar_path = _resolve_calendar_path(Path(path))
    raw = json.loads(calendar_path.read_text(encoding="utf-8"))
    return _calendar_from_payload(raw)


def _resolve_calendar_path(path: Path) -> Path:
    if path.exists():
        return path
    if path == DEFAULT_CALENDAR_PATH:
        repo_relative = Path(__file__).resolve().parents[3] / DEFAULT_CALENDAR_PATH
        if repo_relative.exists():
            return repo_relative
    return path


def _calendar_from_payload(raw: dict[str, Any]) -> TradingCalendar:
    timezone = ZoneInfo(str(raw.get("timezone", "Asia/Seoul")))
    default_session = raw.get("default_session") or {}
    special_sessions: dict[date, tuple[time, time, str]] = {}
    for day, item in (raw.get("special_sessions") or {}).items():
        special_sessions[_date(day)] = (
            _time(str(item["start"])),
            _time(str(item["end"])),
            str(item.get("reason", "")),
        )
    return TradingCalendar(
        version=str(raw["version"]),
        market=str(raw.get("market", "")),
        timezone=timezone,
        default_start=_time(str(default_session.get("start", "09:01"))),
        default_end=_time(str(default_session.get("end", "15:30"))),
        non_trading_dates=frozenset(_date(item) for item in raw.get("non_trading_dates", [])),
        special_sessions=special_sessions,
        source_note=str(raw.get("source_note", "")),
        certified=bool(raw.get("certified", False)),
    )


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _time(value: str) -> time:
    hour, minute = value.split(":", maxsplit=1)
    return time(int(hour), int(minute))
