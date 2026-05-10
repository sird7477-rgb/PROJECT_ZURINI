from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from zurini.data.calendar import TradingCalendar, load_trading_calendar
from zurini.market import Bar, Trade

DEFAULT_SESSION_START = time(9, 1)
DEFAULT_SESSION_END = time(15, 30)
DEFAULT_SESSION_TIMEZONE = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class TradeContinuityCheck:
    symbol: str
    trade_time: str
    kind: str
    window_minutes: int
    missing_minutes: int
    status: str
    audit_mode: str = "dense-window"
    exact_bar_present: bool | None = None
    previous_observed_distance_minutes: int | None = None
    next_observed_distance_minutes: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradeContinuitySummary:
    status: str
    window_minutes: int
    session_start: str
    session_end: str
    checked_points: int
    failed_points: int
    missing_minutes: int
    checks: list[TradeContinuityCheck]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [check.as_dict() for check in self.checks]
        return payload


@dataclass(frozen=True)
class TradeContinuityTradeSummary:
    total_trades: int
    valid_trades: int
    invalid_trades: int
    valid_net_pnl: Decimal
    invalid_net_pnl: Decimal
    invalid_reasons: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_trade_continuity(
    bars: list[Bar],
    trades: list[Trade],
    *,
    window_minutes: int = 5,
    audit_mode: str = "dense-window",
    session_start: time = DEFAULT_SESSION_START,
    session_end: time = DEFAULT_SESSION_END,
    session_timezone: ZoneInfo = DEFAULT_SESSION_TIMEZONE,
    calendar: TradingCalendar | None = None,
) -> TradeContinuitySummary:
    if audit_mode not in {"dense-window", "exact-bar"}:
        raise ValueError("audit_mode must be 'dense-window' or 'exact-bar'")
    timestamps_by_symbol = _timestamps_by_symbol(bars)
    calendar = calendar or load_trading_calendar()
    effective_session_start, effective_session_end = _effective_session_window(session_start, session_end, calendar)
    checks: list[TradeContinuityCheck] = []
    for trade in trades:
        checks.append(
            _check_trade_time(
                symbol=trade.symbol,
                trade_time=trade.entry_time,
                kind="entry",
                timestamps=timestamps_by_symbol.get(trade.symbol, set()),
                window_minutes=window_minutes,
                audit_mode=audit_mode,
                session_start=effective_session_start,
                session_end=effective_session_end,
                session_timezone=session_timezone,
                calendar=calendar,
            )
        )
        checks.append(
            _check_trade_time(
                symbol=trade.symbol,
                trade_time=trade.exit_time,
                kind="exit",
                timestamps=timestamps_by_symbol.get(trade.symbol, set()),
                window_minutes=window_minutes,
                audit_mode=audit_mode,
                session_start=effective_session_start,
                session_end=effective_session_end,
                session_timezone=session_timezone,
                calendar=calendar,
            )
        )
    failed = [check for check in checks if check.status != "passed"]
    missing_minutes = sum(check.missing_minutes for check in checks)
    return TradeContinuitySummary(
        status="passed" if not failed else "failed",
        window_minutes=window_minutes,
        session_start=effective_session_start.isoformat(timespec="minutes"),
        session_end=effective_session_end.isoformat(timespec="minutes"),
        checked_points=len(checks),
        failed_points=len(failed),
        missing_minutes=missing_minutes,
        checks=checks,
    )


def summarize_trades_by_continuity(
    trades: list[Trade],
    continuity: TradeContinuitySummary,
) -> TradeContinuityTradeSummary:
    failed_points = {
        (check.symbol, check.trade_time)
        for check in continuity.checks
        if check.status != "passed"
    }
    valid_trades = 0
    invalid_trades = 0
    valid_net_pnl = Decimal("0")
    invalid_net_pnl = Decimal("0")
    invalid_reasons: dict[str, int] = {}

    for trade in trades:
        invalid = (
            (trade.symbol, trade.entry_time.isoformat()) in failed_points
            or (trade.symbol, trade.exit_time.isoformat()) in failed_points
        )
        if invalid:
            invalid_trades += 1
            invalid_net_pnl += trade.net_pnl
            invalid_reasons[trade.reason] = invalid_reasons.get(trade.reason, 0) + 1
        else:
            valid_trades += 1
            valid_net_pnl += trade.net_pnl

    return TradeContinuityTradeSummary(
        total_trades=len(trades),
        valid_trades=valid_trades,
        invalid_trades=invalid_trades,
        valid_net_pnl=valid_net_pnl,
        invalid_net_pnl=invalid_net_pnl,
        invalid_reasons=dict(sorted(invalid_reasons.items())),
    )


def _timestamps_by_symbol(bars: list[Bar]) -> dict[str, set[datetime]]:
    result: dict[str, set[datetime]] = {}
    for bar in bars:
        result.setdefault(bar.symbol, set()).add(bar.timestamp)
    return result


def _effective_session_window(
    session_start: time,
    session_end: time,
    calendar: TradingCalendar,
) -> tuple[time, time]:
    if session_start == DEFAULT_SESSION_START and session_end == DEFAULT_SESSION_END:
        return calendar.default_start, calendar.default_end
    return session_start, session_end


def _check_trade_time(
    *,
    symbol: str,
    trade_time: datetime,
    kind: str,
    timestamps: set[datetime],
    window_minutes: int,
    audit_mode: str,
    session_start: time,
    session_end: time,
    session_timezone: ZoneInfo,
    calendar: TradingCalendar,
) -> TradeContinuityCheck:
    previous_distance, next_distance = _nearest_observed_distances(trade_time, timestamps)
    if not _in_session(trade_time, session_start, session_end, session_timezone, calendar):
        return TradeContinuityCheck(
            symbol=symbol,
            trade_time=trade_time.isoformat(),
            kind=kind,
            window_minutes=window_minutes,
            missing_minutes=0,
            status="out_of_session",
            audit_mode=audit_mode,
            exact_bar_present=trade_time in timestamps,
            previous_observed_distance_minutes=previous_distance,
            next_observed_distance_minutes=next_distance,
        )
    exact_bar_present = trade_time in timestamps
    if audit_mode == "exact-bar":
        return TradeContinuityCheck(
            symbol=symbol,
            trade_time=trade_time.isoformat(),
            kind=kind,
            window_minutes=window_minutes,
            missing_minutes=0 if exact_bar_present else 1,
            status="passed" if exact_bar_present else "missing_exact_bar",
            audit_mode=audit_mode,
            exact_bar_present=exact_bar_present,
            previous_observed_distance_minutes=previous_distance,
            next_observed_distance_minutes=next_distance,
        )
    expected: list[datetime] = []
    for offset in range(-window_minutes, window_minutes + 1):
        if offset == 0:
            continue
        candidate = trade_time + timedelta(minutes=offset)
        if _same_session_date(candidate, trade_time, session_timezone) and _in_session(
            candidate, session_start, session_end, session_timezone, calendar
        ):
            expected.append(candidate)
    missing = sum(1 for timestamp in expected if timestamp not in timestamps)
    return TradeContinuityCheck(
        symbol=symbol,
        trade_time=trade_time.isoformat(),
        kind=kind,
        window_minutes=window_minutes,
        missing_minutes=missing,
        status="passed" if missing == 0 else "failed",
        audit_mode=audit_mode,
        exact_bar_present=exact_bar_present,
        previous_observed_distance_minutes=previous_distance,
        next_observed_distance_minutes=next_distance,
    )


def _in_session(
    timestamp: datetime,
    session_start: time,
    session_end: time,
    session_timezone: ZoneInfo,
    calendar: TradingCalendar,
) -> bool:
    local = timestamp.astimezone(session_timezone) if timestamp.tzinfo else timestamp
    special = calendar.special_sessions.get(local.date())
    day_start, day_end = (special[0], special[1]) if special else (session_start, session_end)
    return day_start <= local.time() <= day_end


def _same_session_date(left: datetime, right: datetime, session_timezone: ZoneInfo) -> bool:
    return _session_local_date(left, session_timezone) == _session_local_date(right, session_timezone)


def _session_local_time(timestamp: datetime, session_timezone: ZoneInfo) -> time:
    if timestamp.tzinfo is None:
        return timestamp.time()
    return timestamp.astimezone(session_timezone).time()


def _session_local_date(timestamp: datetime, session_timezone: ZoneInfo):
    if timestamp.tzinfo is None:
        return timestamp.date()
    return timestamp.astimezone(session_timezone).date()


def _nearest_observed_distances(trade_time: datetime, timestamps: set[datetime]) -> tuple[int | None, int | None]:
    previous = [
        int((trade_time - timestamp).total_seconds() // 60)
        for timestamp in timestamps
        if timestamp < trade_time
    ]
    next_ = [
        int((timestamp - trade_time).total_seconds() // 60)
        for timestamp in timestamps
        if timestamp > trade_time
    ]
    return (min(previous) if previous else None, min(next_) if next_ else None)
