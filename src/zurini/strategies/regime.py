from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from zurini.data.csv_loader import load_daishin_minute_csv
from zurini.market import Bar, SignalIntent
from zurini.strategies.baseline import RiskState

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class RegimeState:
    name: str
    sma5: Decimal
    sma20: Decimal
    sma60: Decimal


class RegimeFilteredStrategy:
    def __init__(
        self,
        inner_factory: Callable[[], object],
        *,
        regimes: dict[date, RegimeState],
        allowed_regimes: frozenset[str],
    ) -> None:
        self.inner = inner_factory()
        self.regimes = regimes
        self.allowed_regimes = allowed_regimes

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        session_date = bar.timestamp.astimezone(KST).date()
        regime = self.regimes.get(session_date)
        if regime is None:
            return SignalIntent("hold", reason="regime-unknown")
        if regime.name not in self.allowed_regimes:
            return SignalIntent("hold", reason=f"regime-blocked-{regime.name}")
        return self.inner.on_bar(bar, risk)


class RelativeStrengthFilteredStrategy:
    def __init__(
        self,
        inner_factory: Callable[[], object],
        *,
        index_bars: dict[object, Bar],
        min_relative_return: Decimal,
    ) -> None:
        self.inner = inner_factory()
        self.index_bars = index_bars
        self.min_relative_return = min_relative_return
        self._symbol_session_open: dict[date, Decimal] = {}
        self._index_session_open: dict[date, Decimal] = {}

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        index_bar = self.index_bars.get(bar.timestamp)
        if index_bar is None:
            return SignalIntent("hold", reason="relative-strength-index-missing")
        session_date = bar.timestamp.astimezone(KST).date()
        self._symbol_session_open.setdefault(session_date, bar.open)
        self._index_session_open.setdefault(session_date, index_bar.open)
        symbol_return = (bar.close - self._symbol_session_open[session_date]) / self._symbol_session_open[session_date]
        index_return = (index_bar.close - self._index_session_open[session_date]) / self._index_session_open[session_date]
        if symbol_return - index_return < self.min_relative_return:
            return SignalIntent("hold", reason="relative-strength-blocked")
        return self.inner.on_bar(bar, risk)


def load_regime_states(
    *,
    index_root: Path,
    symbol: str = "U001",
) -> dict[date, RegimeState]:
    paths = sorted(index_root.glob(f"*/{symbol}.csv"))
    if not paths:
        raise FileNotFoundError(f"no index CSV files matched {index_root}/*/{symbol}.csv")
    bars: list[Bar] = []
    for path in paths:
        bars.extend(load_daishin_minute_csv(path, symbol=symbol, source="daishin-index"))
    daily_closes = _daily_closes(bars)
    return build_regime_states(daily_closes)


def load_index_bars(
    *,
    index_root: Path,
    symbol: str = "U001",
) -> dict[object, Bar]:
    paths = sorted(index_root.glob(f"*/{symbol}.csv"))
    if not paths:
        raise FileNotFoundError(f"no index CSV files matched {index_root}/*/{symbol}.csv")
    bars: list[Bar] = []
    for path in paths:
        bars.extend(load_daishin_minute_csv(path, symbol=symbol, source="daishin-index"))
    return {bar.timestamp: bar for bar in bars}


def build_regime_states(daily_closes: list[tuple[date, Decimal]]) -> dict[date, RegimeState]:
    ordered = sorted(daily_closes)
    regimes: dict[date, RegimeState] = {}
    for index, (session_date, _close) in enumerate(ordered):
        history = [close for _day, close in ordered[:index]]
        if len(history) < 60:
            continue
        sma5 = _sma(history[-5:])
        sma20 = _sma(history[-20:])
        sma60 = _sma(history[-60:])
        regimes[session_date] = RegimeState(
            name=_classify_regime(sma5=sma5, sma20=sma20, sma60=sma60),
            sma5=sma5,
            sma20=sma20,
            sma60=sma60,
        )
    return regimes


def allowed_regimes(policy: str) -> frozenset[str]:
    if policy == "bull-only":
        return frozenset({"bull"})
    if policy == "non-bear":
        return frozenset({"bull", "range"})
    raise ValueError(f"unsupported regime filter policy: {policy}")


def _daily_closes(bars: list[Bar]) -> list[tuple[date, Decimal]]:
    closes: dict[date, tuple[object, Decimal]] = {}
    for bar in sorted(bars, key=lambda item: item.timestamp):
        session_date = bar.timestamp.astimezone(KST).date()
        closes[session_date] = (bar.timestamp, bar.close)
    return [(session_date, close) for session_date, (_timestamp, close) in sorted(closes.items())]


def _classify_regime(*, sma5: Decimal, sma20: Decimal, sma60: Decimal) -> str:
    if sma5 > sma20 and sma20 > sma60:
        return "bull"
    if sma5 > sma20 and sma20 <= sma60:
        return "range"
    if sma5 < sma20:
        return "bear"
    return "range"


def _sma(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))
