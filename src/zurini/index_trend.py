from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

from zurini.market import Bar


KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class IndexTrendState:
    index_code: str
    observed_at: datetime
    ret_open: Decimal | None
    ret_5m: Decimal | None
    ret_10m: Decimal | None
    ret_30m: Decimal | None
    reclaim_30m: Decimal | None
    stale: bool
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "index_code": self.index_code,
            "observed_at": self.observed_at.isoformat(),
            "ret_open": _decimal_or_none(self.ret_open),
            "ret_5m": _decimal_or_none(self.ret_5m),
            "ret_10m": _decimal_or_none(self.ret_10m),
            "ret_30m": _decimal_or_none(self.ret_30m),
            "reclaim_30m": _decimal_or_none(self.reclaim_30m),
            "stale": self.stale,
            "status": self.status,
        }


@dataclass(frozen=True)
class IndexTrendGateConfig:
    open_block_threshold: Decimal = Decimal("-0.010")
    ten_minute_block_threshold: Decimal = Decimal("-0.004")
    thirty_minute_block_threshold: Decimal = Decimal("-0.008")
    thirty_minute_reclaim_threshold: Decimal = Decimal("0.003")
    stale_after: timedelta = timedelta(seconds=30)


@dataclass(frozen=True)
class IndexTrendDecision:
    allowed: bool
    reason: str
    states: tuple[IndexTrendState, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "states": [state.as_dict() for state in self.states],
        }


IndexTrendProvider = Callable[[datetime, str], IndexTrendDecision]


def build_index_trend_state(
    *,
    index_code: str,
    bars: list[Bar],
    observed_at: datetime,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(seconds=30),
) -> IndexTrendState:
    if not bars:
        return IndexTrendState(
            index_code=index_code,
            observed_at=observed_at,
            ret_open=None,
            ret_5m=None,
            ret_10m=None,
            ret_30m=None,
            reclaim_30m=None,
            stale=True,
            status="missing",
        )
    ordered = sorted((bar for bar in bars if bar.symbol == index_code), key=lambda item: item.timestamp)
    active = [bar for bar in ordered if _as_kst(bar.timestamp) <= _as_kst(observed_at)]
    if not active:
        return IndexTrendState(
            index_code=index_code,
            observed_at=observed_at,
            ret_open=None,
            ret_5m=None,
            ret_10m=None,
            ret_30m=None,
            reclaim_30m=None,
            stale=True,
            status="missing",
        )
    session_date = _as_kst(observed_at).date()
    session_bars = [bar for bar in active if _as_kst(bar.timestamp).date() == session_date]
    if not session_bars:
        return IndexTrendState(
            index_code=index_code,
            observed_at=observed_at,
            ret_open=None,
            ret_5m=None,
            ret_10m=None,
            ret_30m=None,
            reclaim_30m=None,
            stale=True,
            status="missing",
        )
    current = session_bars[-1]
    reference_now = _as_kst(now or observed_at)
    stale = reference_now - _as_kst(current.timestamp) > stale_after
    open_price = session_bars[0].open
    ret_open = _return(current.close, open_price)
    ret_5m = _window_return(session_bars, observed_at, minutes=5)
    ret_10m = _window_return(session_bars, observed_at, minutes=10)
    ret_30m = _window_return(session_bars, observed_at, minutes=30)
    reclaim_30m = _reclaim_return(session_bars, observed_at, minutes=30)
    return IndexTrendState(
        index_code=index_code,
        observed_at=current.timestamp,
        ret_open=ret_open,
        ret_5m=ret_5m,
        ret_10m=ret_10m,
        ret_30m=ret_30m,
        reclaim_30m=reclaim_30m,
        stale=stale,
        status=_trend_status(stale=stale, ret_open=ret_open, ret_10m=ret_10m, ret_30m=ret_30m),
    )


def decide_day_entry_with_index_trend(
    *,
    states: tuple[IndexTrendState, ...],
    config: IndexTrendGateConfig | None = None,
) -> IndexTrendDecision:
    if not states:
        return IndexTrendDecision(False, "index-trend-missing", states)
    active_config = config or IndexTrendGateConfig()
    if any(state.stale or state.status == "missing" for state in states):
        return IndexTrendDecision(False, "index-trend-stale", states)
    if any(state.status == "warming-up" for state in states):
        return IndexTrendDecision(False, "index-trend-warming-up", states)
    if any(state.status == "bearish" for state in states):
        return IndexTrendDecision(False, "index-trend-bearish", states)

    open_block = (
        len(states) >= 2
        and all(
            state.ret_open is not None and state.ret_open <= active_config.open_block_threshold
            for state in states
        )
    )
    slope_block = any(
        (
            state.ret_10m is not None
            and state.ret_10m <= active_config.ten_minute_block_threshold
        )
        or (
            state.ret_30m is not None
            and state.ret_30m <= active_config.thirty_minute_block_threshold
        )
        for state in states
    )
    recovered = any(
        state.reclaim_30m is not None
        and state.reclaim_30m >= active_config.thirty_minute_reclaim_threshold
        and (state.ret_5m is None or state.ret_5m >= Decimal("0"))
        for state in states
    )
    if (open_block or slope_block) and not recovered:
        reason = "index-trend-open-block" if open_block else "index-trend-slope-block"
        return IndexTrendDecision(False, reason, states)
    return IndexTrendDecision(True, "index-trend-allowed", states)


def provider_from_index_bars(
    bars: list[Bar],
    *,
    index_codes: tuple[str, ...] = ("KOSPI", "KOSDAQ"),
    config: IndexTrendGateConfig | None = None,
    stale_after: timedelta = timedelta(seconds=30),
) -> IndexTrendProvider:
    def _provider(timestamp: datetime, _symbol: str) -> IndexTrendDecision:
        states = tuple(
            build_index_trend_state(
                index_code=index_code,
                bars=bars,
                observed_at=timestamp,
                now=timestamp,
                stale_after=stale_after,
            )
            for index_code in index_codes
        )
        return decide_day_entry_with_index_trend(states=states, config=config)

    return _provider


def _window_return(bars: list[Bar], observed_at: datetime, *, minutes: int) -> Decimal | None:
    cutoff = _as_kst(observed_at) - timedelta(minutes=minutes)
    prior = [bar for bar in bars if _as_kst(bar.timestamp) <= cutoff]
    if not prior:
        return None
    return _return(bars[-1].close, prior[-1].close)


def _reclaim_return(bars: list[Bar], observed_at: datetime, *, minutes: int) -> Decimal | None:
    cutoff = _as_kst(observed_at) - timedelta(minutes=minutes)
    window = [bar for bar in bars if cutoff <= _as_kst(bar.timestamp) <= _as_kst(observed_at)]
    if not window:
        return None
    low = min(bar.low for bar in window)
    return _return(window[-1].close, low)


def _return(current: Decimal, base: Decimal) -> Decimal | None:
    if base == 0:
        return None
    return (current - base) / base


def _trend_status(
    *,
    stale: bool,
    ret_open: Decimal | None,
    ret_10m: Decimal | None,
    ret_30m: Decimal | None,
) -> str:
    if stale:
        return "stale"
    if ret_10m is None or ret_30m is None:
        return "warming-up"
    if ret_open is not None and ret_open <= Decimal("-0.010"):
        return "bearish"
    if ret_10m is not None and ret_10m <= Decimal("-0.004"):
        return "bearish"
    if ret_30m is not None and ret_30m <= Decimal("-0.008"):
        return "bearish"
    return "neutral"


def _as_kst(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=KST)
    return timestamp.astimezone(KST)


def _decimal_or_none(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)
