from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from zurini.market import Bar, SignalIntent


@dataclass(frozen=True)
class RiskState:
    nasdaq_future_return: Decimal | None = Decimal("0")
    blacklist_updated_at: datetime | None = None
    blacklisted_symbols: frozenset[str] = frozenset()

    def beta_multiplier(self) -> Decimal:
        if self.nasdaq_future_return is None:
            return Decimal("0.50")
        raw = Decimal("1.0") + self.nasdaq_future_return * Decimal("20")
        return min(Decimal("1.0"), max(Decimal("0.0"), raw))

    def allows_entry(self, bar: Bar) -> bool:
        if self.beta_multiplier() <= 0:
            return False
        if bar.symbol in self.blacklisted_symbols:
            return False
        if self.blacklist_updated_at is None:
            return False
        return bar.timestamp - self.blacklist_updated_at <= timedelta(minutes=5)


class VwapFirstPullbackStrategy:
    def __init__(
        self,
        *,
        pullback_band: Decimal = Decimal("0.005"),
        min_bid_ask_ratio: Decimal = Decimal("2.0"),
    ) -> None:
        self.pullback_band = pullback_band
        self.min_bid_ask_ratio = min_bid_ask_ratio
        self._cum_value = Decimal("0")
        self._cum_volume = Decimal("0")
        self._saw_impulse = False
        self._entered = False

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        previous_vwap = self.vwap
        self._cum_value += bar.value
        self._cum_volume += Decimal(bar.volume)

        if previous_vwap is None:
            return SignalIntent("hold", reason="warming-up")

        if bar.close >= previous_vwap * Decimal("1.01") and bar.volume >= 3000:
            self._saw_impulse = True
            return SignalIntent("hold", reason="impulse-detected")

        near_vwap = abs(bar.close - previous_vwap) / previous_vwap <= self.pullback_band
        pressure_ok = bar.bid_ask_ratio >= self.min_bid_ask_ratio
        if (
            self._saw_impulse
            and not self._entered
            and near_vwap
            and pressure_ok
            and risk.allows_entry(bar)
        ):
            self._entered = True
            return SignalIntent("buy", weight=risk.beta_multiplier(), reason="vwap-first-pullback")

        return SignalIntent("hold", reason="no-entry")

    @property
    def vwap(self) -> Decimal | None:
        if self._cum_volume == 0:
            return None
        return self._cum_value / self._cum_volume
