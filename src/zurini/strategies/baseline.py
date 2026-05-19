from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from zurini.index_trend import IndexTrendDecision, IndexTrendProvider
from zurini.market import Bar, SignalIntent


@dataclass(frozen=True)
class RiskState:
    nasdaq_future_return: Decimal | None = Decimal("0")
    blacklist_updated_at: datetime | None = None
    blacklisted_symbols: frozenset[str] = frozenset()
    index_trend_filter_enabled: bool = False
    index_trend_provider: IndexTrendProvider | None = None

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

    def block_reason(self, bar: Bar) -> str:
        if self.beta_multiplier() <= 0:
            return "risk-block:negative-beta-throttle"
        if bar.symbol in self.blacklisted_symbols:
            return "risk-block:blacklisted-symbol"
        if self.blacklist_updated_at is None:
            return "risk-block:missing-blacklist-heartbeat"
        if bar.timestamp - self.blacklist_updated_at > timedelta(minutes=5):
            return "risk-block:stale-blacklist-heartbeat"
        return "risk-block:unknown"

    def index_trend_decision(self, bar: Bar) -> IndexTrendDecision | None:
        if not self.index_trend_filter_enabled:
            return None
        if self.index_trend_provider is None:
            return IndexTrendDecision(allowed=False, reason="index-trend-missing")
        return self.index_trend_provider(bar.timestamp, bar.symbol)

    def allows_day_entry_by_index_trend(self, bar: Bar) -> bool:
        decision = self.index_trend_decision(bar)
        return True if decision is None else decision.allowed

    def index_trend_block_reason(self, bar: Bar) -> str:
        decision = self.index_trend_decision(bar)
        if decision is None or decision.allowed:
            return "risk-block:index-trend-allowed"
        return f"risk-block:{decision.reason}"


class VwapFirstPullbackStrategy:
    def __init__(
        self,
        *,
        pullback_band: Decimal = Decimal("0.005"),
        min_bid_ask_ratio: Decimal = Decimal("2.0"),
        entry_start: time | None = None,
        entry_end: time | None = None,
        entry_mode: str = "pullback",
        require_above_vwap: bool = False,
        impulse_threshold: Decimal = Decimal("0.01"),
        min_impulse_volume: int = 3000,
        impulse_volume_window: int = 0,
        impulse_volume_multiple: Decimal = Decimal("0"),
    ) -> None:
        self.pullback_band = pullback_band
        self.min_bid_ask_ratio = min_bid_ask_ratio
        self.entry_start = entry_start
        self.entry_end = entry_end
        self.entry_mode = entry_mode
        self.require_above_vwap = require_above_vwap
        self.impulse_threshold = impulse_threshold
        self.min_impulse_volume = min_impulse_volume
        self.impulse_volume_window = impulse_volume_window
        self.impulse_volume_multiple = impulse_volume_multiple
        self._cum_value = Decimal("0")
        self._cum_volume = Decimal("0")
        self._recent_volumes: deque[int] = deque(maxlen=max(impulse_volume_window, 1))
        self._saw_impulse = False
        self._entered = False
        self._session_date = None

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        self._reset_for_new_session(bar)
        previous_vwap = self.vwap
        self._cum_value += bar.value
        self._cum_volume += Decimal(bar.volume)

        if previous_vwap is None:
            self._recent_volumes.append(bar.volume)
            return SignalIntent("hold", reason="warming-up")

        if self._is_impulse(bar, previous_vwap):
            self._saw_impulse = True
            self._recent_volumes.append(bar.volume)
            if (
                self.entry_mode == "breakout"
                and not self._entered
                and self._within_entry_window(bar)
                and bar.bid_ask_ratio >= self.min_bid_ask_ratio
                and risk.allows_entry(bar)
            ):
                self._entered = True
                return SignalIntent("buy", weight=risk.beta_multiplier(), reason="vwap-breakout")
            return SignalIntent("hold", reason="impulse-detected")

        vwap_distance = (bar.close - previous_vwap) / previous_vwap
        near_vwap = abs(vwap_distance) <= self.pullback_band
        above_vwap_ok = not self.require_above_vwap or vwap_distance >= 0
        pressure_ok = bar.bid_ask_ratio >= self.min_bid_ask_ratio
        if (
            self._saw_impulse
            and not self._entered
            and near_vwap
            and above_vwap_ok
            and pressure_ok
            and self._within_entry_window(bar)
            and risk.allows_entry(bar)
        ):
            self._entered = True
            return SignalIntent("buy", weight=risk.beta_multiplier(), reason="vwap-first-pullback")

        self._recent_volumes.append(bar.volume)
        return SignalIntent("hold", reason="no-entry")

    @property
    def vwap(self) -> Decimal | None:
        if self._cum_volume == 0:
            return None
        return self._cum_value / self._cum_volume

    def _reset_for_new_session(self, bar: Bar) -> None:
        session_date = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()
        if session_date == self._session_date:
            return
        self._session_date = session_date
        self._cum_value = Decimal("0")
        self._cum_volume = Decimal("0")
        self._recent_volumes.clear()
        self._saw_impulse = False
        self._entered = False

    def _within_entry_window(self, bar: Bar) -> bool:
        current = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).time()
        if self.entry_start is not None and current < self.entry_start:
            return False
        if self.entry_end is not None and current > self.entry_end:
            return False
        return True

    def _is_impulse(self, bar: Bar, previous_vwap: Decimal) -> bool:
        if bar.close < previous_vwap * (Decimal("1") + self.impulse_threshold):
            return False
        if bar.volume < self.min_impulse_volume:
            return False
        if self.impulse_volume_window <= 0 or self.impulse_volume_multiple <= 0:
            return True
        if len(self._recent_volumes) < self.impulse_volume_window:
            return False
        average_volume = Decimal(sum(self._recent_volumes)) / Decimal(len(self._recent_volumes))
        return Decimal(bar.volume) >= average_volume * self.impulse_volume_multiple


class DefensivePullbackDayStrategy:
    def __init__(
        self,
        *,
        sma_window: int = 20,
        atr_window: int = 14,
        value_window: int = 5,
        min_average_value: Decimal = Decimal("50000000000"),
        min_atr_ratio: Decimal = Decimal("0.03"),
        pullback_band: Decimal = Decimal("0.006"),
        max_opening_gap: Decimal = Decimal("0.05"),
        min_session_value: Decimal = Decimal("0"),
        min_bid_ask_ratio: Decimal = Decimal("2.0"),
        entry_start: time | None = time(9, 5),
        entry_end: time | None = time(15, 0),
    ) -> None:
        self.sma_window = sma_window
        self.atr_window = atr_window
        self.value_window = value_window
        self.min_average_value = min_average_value
        self.min_atr_ratio = min_atr_ratio
        self.pullback_band = pullback_band
        self.max_opening_gap = max_opening_gap
        self.min_session_value = min_session_value
        self.min_bid_ask_ratio = min_bid_ask_ratio
        self.entry_start = entry_start
        self.entry_end = entry_end
        self._session_date: date | None = None
        self._day_open: Decimal | None = None
        self._day_high: Decimal | None = None
        self._day_low: Decimal | None = None
        self._day_close: Decimal | None = None
        self._day_value = Decimal("0")
        self._cum_value = Decimal("0")
        self._cum_volume = Decimal("0")
        self._daily_highs: deque[Decimal] = deque(maxlen=atr_window + 1)
        self._daily_lows: deque[Decimal] = deque(maxlen=atr_window + 1)
        self._daily_closes: deque[Decimal] = deque(maxlen=max(sma_window, atr_window + 1))
        self._daily_values: deque[Decimal] = deque(maxlen=value_window)
        self._entered = False

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        self._roll_session(bar)
        previous_vwap = self.vwap
        self._update_intraday_state(bar)

        if self._entered:
            return SignalIntent("hold", reason="already-entered")
        if previous_vwap is None:
            return SignalIntent("hold", reason="warming-up")
        if not self._prior_universe_ok():
            return SignalIntent("hold", reason="universe-filter")
        if not self._within_entry_window(bar):
            return SignalIntent("hold", reason="entry-window")
        if not risk.allows_entry(bar):
            return SignalIntent("hold", reason=risk.block_reason(bar))
        if bar.bid_ask_ratio < self.min_bid_ask_ratio:
            return SignalIntent("hold", reason="weak-pressure")
        if self._day_open is None or self._daily_closes[-1] == 0:
            return SignalIntent("hold", reason="warming-up")
        opening_gap = abs((self._day_open - self._daily_closes[-1]) / self._daily_closes[-1])
        if opening_gap > self.max_opening_gap:
            return SignalIntent("hold", reason="opening-gap")
        if self._day_value < self.min_session_value:
            return SignalIntent("hold", reason="session-liquidity")

        vwap_distance = (bar.close - previous_vwap) / previous_vwap
        controlled_pullback = abs(vwap_distance) <= self.pullback_band and bar.close >= self._day_open
        if controlled_pullback:
            self._entered = True
            return SignalIntent(
                "buy",
                weight=risk.beta_multiplier(),
                reason="a-day-v2-controlled-pullback",
                score=_signal_score(bar.bid_ask_ratio, vwap_distance),
            )
        return SignalIntent("hold", reason="no-entry")

    @property
    def vwap(self) -> Decimal | None:
        if self._cum_volume == 0:
            return None
        return self._cum_value / self._cum_volume

    def _roll_session(self, bar: Bar) -> None:
        session_date = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()
        if self._session_date is None:
            self._start_session(bar, session_date)
            return
        if session_date == self._session_date:
            return
        if self._day_high is not None and self._day_low is not None and self._day_close is not None:
            self._daily_highs.append(self._day_high)
            self._daily_lows.append(self._day_low)
            self._daily_closes.append(self._day_close)
            self._daily_values.append(self._day_value)
        self._start_session(bar, session_date)

    def _start_session(self, bar: Bar, session_date: date) -> None:
        self._session_date = session_date
        self._day_open = bar.open
        self._day_high = None
        self._day_low = None
        self._day_close = None
        self._day_value = Decimal("0")
        self._cum_value = Decimal("0")
        self._cum_volume = Decimal("0")
        self._entered = False

    def _update_intraday_state(self, bar: Bar) -> None:
        self._day_high = bar.high if self._day_high is None else max(self._day_high, bar.high)
        self._day_low = bar.low if self._day_low is None else min(self._day_low, bar.low)
        self._day_close = bar.close
        self._day_value += bar.value
        self._cum_value += bar.value
        self._cum_volume += Decimal(bar.volume)

    def _prior_universe_ok(self) -> bool:
        if (
            len(self._daily_closes) < self.sma_window
            or len(self._daily_values) < self.value_window
            or len(self._daily_highs) < self.atr_window
        ):
            return False
        prior_close = self._daily_closes[-1]
        if prior_close <= 0:
            return False
        sma = sum(list(self._daily_closes)[-self.sma_window :], Decimal("0")) / Decimal(self.sma_window)
        average_value = sum(self._daily_values, Decimal("0")) / Decimal(len(self._daily_values))
        atr = _atr(list(self._daily_highs), list(self._daily_lows), list(self._daily_closes), self.atr_window)
        return (
            average_value >= self.min_average_value
            and prior_close > sma
            and atr / prior_close >= self.min_atr_ratio
        )

    def _within_entry_window(self, bar: Bar) -> bool:
        current = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).time()
        if self.entry_start is not None and current < self.entry_start:
            return False
        if self.entry_end is not None and current > self.entry_end:
            return False
        return True


class ConfirmedPullbackDayStrategy(DefensivePullbackDayStrategy):
    def __init__(
        self,
        *,
        reclaim_threshold: Decimal = Decimal("0.002"),
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.reclaim_threshold = reclaim_threshold
        self._armed_pullback_price: Decimal | None = None
        self._previous_high: Decimal | None = None

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        previous_session = self._session_date
        previous_high = self._previous_high
        self._roll_session(bar)
        if previous_session != self._session_date:
            previous_high = None
            self._armed_pullback_price = None
        previous_vwap = self.vwap
        self._update_intraday_state(bar)
        self._previous_high = bar.high

        if self._entered:
            return SignalIntent("hold", reason="already-entered")
        if previous_vwap is None:
            return SignalIntent("hold", reason="warming-up")
        if not self._prior_universe_ok():
            return SignalIntent("hold", reason="universe-filter")
        if not self._within_entry_window(bar):
            return SignalIntent("hold", reason="entry-window")
        if not risk.allows_entry(bar):
            return SignalIntent("hold", reason=risk.block_reason(bar))
        if bar.bid_ask_ratio < self.min_bid_ask_ratio:
            return SignalIntent("hold", reason="weak-pressure")
        if self._day_open is None or self._daily_closes[-1] == 0:
            return SignalIntent("hold", reason="warming-up")
        opening_gap = abs((self._day_open - self._daily_closes[-1]) / self._daily_closes[-1])
        if opening_gap > self.max_opening_gap:
            return SignalIntent("hold", reason="opening-gap")
        if self._day_value < self.min_session_value:
            return SignalIntent("hold", reason="session-liquidity")

        if self._armed_pullback_price is not None:
            rebound_from_pullback = bar.close >= self._armed_pullback_price * (Decimal("1") + self.reclaim_threshold)
            reclaimed_reference = bar.close >= previous_vwap and (previous_high is None or bar.close >= previous_high)
            if rebound_from_pullback and reclaimed_reference:
                self._entered = True
                reclaim_distance = (bar.close - self._armed_pullback_price) / self._armed_pullback_price
                return SignalIntent(
                    "buy",
                    weight=risk.beta_multiplier(),
                    reason="confirmed-day-pullback",
                    score=_signal_score(bar.bid_ask_ratio, reclaim_distance),
                )

        vwap_distance = (bar.close - previous_vwap) / previous_vwap
        controlled_pullback = abs(vwap_distance) <= self.pullback_band and bar.close >= self._day_open
        if controlled_pullback:
            self._armed_pullback_price = bar.close
            return SignalIntent("hold", reason="pullback-armed")
        return SignalIntent("hold", reason="no-entry")


class OpeningRangeBreakoutDayStrategy(DefensivePullbackDayStrategy):
    def __init__(
        self,
        *,
        range_minutes: int = 30,
        breakout_buffer: Decimal = Decimal("0.003"),
        max_range_ratio: Decimal = Decimal("0.06"),
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.range_minutes = range_minutes
        self.breakout_buffer = breakout_buffer
        self.max_range_ratio = max_range_ratio
        self._range_high: Decimal | None = None
        self._range_low: Decimal | None = None

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        previous_session = self._session_date
        self._roll_session(bar)
        if previous_session != self._session_date:
            self._range_high = None
            self._range_low = None
        self._update_intraday_state(bar)

        if self._day_open is None:
            return SignalIntent("hold", reason="warming-up")
        minutes_from_open = int((bar.timestamp - bar.timestamp.replace(hour=9, minute=0, second=0, microsecond=0)).total_seconds() // 60)
        if minutes_from_open <= self.range_minutes:
            self._range_high = bar.high if self._range_high is None else max(self._range_high, bar.high)
            self._range_low = bar.low if self._range_low is None else min(self._range_low, bar.low)
            return SignalIntent("hold", reason="opening-range")

        if self._entered:
            return SignalIntent("hold", reason="already-entered")
        if self._range_high is None or self._range_low is None:
            return SignalIntent("hold", reason="opening-range")
        if not self._prior_universe_ok():
            return SignalIntent("hold", reason="universe-filter")
        if not self._within_entry_window(bar):
            return SignalIntent("hold", reason="entry-window")
        if not risk.allows_entry(bar):
            return SignalIntent("hold", reason=risk.block_reason(bar))
        if bar.bid_ask_ratio < self.min_bid_ask_ratio:
            return SignalIntent("hold", reason="weak-pressure")
        if self._daily_closes[-1] == 0:
            return SignalIntent("hold", reason="warming-up")
        opening_gap = abs((self._day_open - self._daily_closes[-1]) / self._daily_closes[-1])
        if opening_gap > self.max_opening_gap:
            return SignalIntent("hold", reason="opening-gap")
        if self._day_value < self.min_session_value:
            return SignalIntent("hold", reason="session-liquidity")

        range_ratio = (self._range_high - self._range_low) / self._range_low if self._range_low else Decimal("999")
        breakout_price = self._range_high * (Decimal("1") + self.breakout_buffer)
        if range_ratio <= self.max_range_ratio and bar.close >= breakout_price:
            self._entered = True
            breakout_distance = (bar.close - breakout_price) / breakout_price
            return SignalIntent(
                "buy",
                weight=risk.beta_multiplier(),
                reason="opening-range-breakout",
                score=_signal_score(bar.bid_ask_ratio, breakout_distance) - range_ratio,
            )
        return SignalIntent("hold", reason="no-entry")


class IntradayMomentumContinuationStrategy(DefensivePullbackDayStrategy):
    def __init__(
        self,
        *,
        min_day_return: Decimal = Decimal("0.03"),
        max_day_return: Decimal = Decimal("0.12"),
        min_vwap_distance: Decimal = Decimal("0.003"),
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.min_day_return = min_day_return
        self.max_day_return = max_day_return
        self.min_vwap_distance = min_vwap_distance

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        self._roll_session(bar)
        previous_vwap = self.vwap
        self._update_intraday_state(bar)

        if self._entered:
            return SignalIntent("hold", reason="already-entered")
        if previous_vwap is None:
            return SignalIntent("hold", reason="warming-up")
        if not self._prior_universe_ok():
            return SignalIntent("hold", reason="universe-filter")
        if not self._within_entry_window(bar):
            return SignalIntent("hold", reason="entry-window")
        if not risk.allows_entry(bar):
            return SignalIntent("hold", reason=risk.block_reason(bar))
        if bar.bid_ask_ratio < self.min_bid_ask_ratio:
            return SignalIntent("hold", reason="weak-pressure")
        if self._day_open is None or self._daily_closes[-1] == 0:
            return SignalIntent("hold", reason="warming-up")
        opening_gap = abs((self._day_open - self._daily_closes[-1]) / self._daily_closes[-1])
        if opening_gap > self.max_opening_gap:
            return SignalIntent("hold", reason="opening-gap")
        if self._day_value < self.min_session_value:
            return SignalIntent("hold", reason="session-liquidity")

        day_return = (bar.close - self._day_open) / self._day_open
        vwap_distance = (bar.close - previous_vwap) / previous_vwap
        if (
            self.min_day_return <= day_return <= self.max_day_return
            and vwap_distance >= self.min_vwap_distance
        ):
            self._entered = True
            return SignalIntent(
                "buy",
                weight=risk.beta_multiplier(),
                reason="intraday-momentum-continuation",
                score=_signal_score(bar.bid_ask_ratio, day_return + vwap_distance),
            )
        return SignalIntent("hold", reason="no-entry")


class PriorMomentumContinuationStrategy(DefensivePullbackDayStrategy):
    def __init__(
        self,
        *,
        min_prior_return: Decimal = Decimal("0.04"),
        max_prior_return: Decimal = Decimal("0.15"),
        min_confirm_above_prior_close: Decimal = Decimal("0.005"),
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.min_prior_return = min_prior_return
        self.max_prior_return = max_prior_return
        self.min_confirm_above_prior_close = min_confirm_above_prior_close

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        self._roll_session(bar)
        self._update_intraday_state(bar)

        if self._entered:
            return SignalIntent("hold", reason="already-entered")
        if len(self._daily_closes) < max(self.sma_window, 2):
            return SignalIntent("hold", reason="warming-up")
        if not self._prior_universe_ok():
            return SignalIntent("hold", reason="universe-filter")
        if not self._within_entry_window(bar):
            return SignalIntent("hold", reason="entry-window")
        if not risk.allows_entry(bar):
            return SignalIntent("hold", reason=risk.block_reason(bar))
        if bar.bid_ask_ratio < self.min_bid_ask_ratio:
            return SignalIntent("hold", reason="weak-pressure")
        if self._day_open is None or self._daily_closes[-1] == 0 or self._daily_closes[-2] == 0:
            return SignalIntent("hold", reason="warming-up")
        opening_gap = abs((self._day_open - self._daily_closes[-1]) / self._daily_closes[-1])
        if opening_gap > self.max_opening_gap:
            return SignalIntent("hold", reason="opening-gap")
        if self._day_value < self.min_session_value:
            return SignalIntent("hold", reason="session-liquidity")

        prior_return = (self._daily_closes[-1] - self._daily_closes[-2]) / self._daily_closes[-2]
        confirm_price = self._daily_closes[-1] * (Decimal("1") + self.min_confirm_above_prior_close)
        if self.min_prior_return <= prior_return <= self.max_prior_return and bar.close >= confirm_price:
            self._entered = True
            confirm_distance = (bar.close - confirm_price) / confirm_price
            return SignalIntent(
                "buy",
                weight=risk.beta_multiplier(),
                reason="prior-momentum-continuation",
                score=_signal_score(bar.bid_ask_ratio, prior_return + confirm_distance),
            )
        return SignalIntent("hold", reason="no-entry")


class GapReboundDayStrategy(DefensivePullbackDayStrategy):
    def __init__(
        self,
        *,
        min_gap_down: Decimal = Decimal("0.005"),
        max_gap_down: Decimal = Decimal("0.04"),
        reclaim_over_prior_close: Decimal = Decimal("0.001"),
        min_vwap_distance: Decimal = Decimal("0"),
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.min_gap_down = min_gap_down
        self.max_gap_down = max_gap_down
        self.reclaim_over_prior_close = reclaim_over_prior_close
        self.min_vwap_distance = min_vwap_distance

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        self._roll_session(bar)
        previous_vwap = self.vwap
        self._update_intraday_state(bar)

        if self._entered:
            return SignalIntent("hold", reason="already-entered")
        if previous_vwap is None:
            return SignalIntent("hold", reason="warming-up")
        if not self._prior_universe_ok():
            return SignalIntent("hold", reason="universe-filter")
        if not self._within_entry_window(bar):
            return SignalIntent("hold", reason="entry-window")
        if not risk.allows_entry(bar):
            return SignalIntent("hold", reason=risk.block_reason(bar))
        if bar.bid_ask_ratio < self.min_bid_ask_ratio:
            return SignalIntent("hold", reason="weak-pressure")
        if self._day_open is None or self._daily_closes[-1] == 0:
            return SignalIntent("hold", reason="warming-up")
        if self._day_value < self.min_session_value:
            return SignalIntent("hold", reason="session-liquidity")

        gap = (self._day_open - self._daily_closes[-1]) / self._daily_closes[-1]
        if gap >= 0:
            return SignalIntent("hold", reason="not-gap-down")
        gap_down = abs(gap)
        if not (self.min_gap_down <= gap_down <= self.max_gap_down):
            return SignalIntent("hold", reason="gap-out-of-range")

        reclaim_price = self._daily_closes[-1] * (Decimal("1") + self.reclaim_over_prior_close)
        vwap_distance = (bar.close - previous_vwap) / previous_vwap
        if bar.close >= reclaim_price and vwap_distance >= self.min_vwap_distance:
            self._entered = True
            return SignalIntent(
                "buy",
                weight=risk.beta_multiplier(),
                reason="gap-rebound",
                score=_signal_score(bar.bid_ask_ratio, gap_down + vwap_distance),
            )
        return SignalIntent("hold", reason="no-entry")


class SwingSupportStrategy:
    def __init__(
        self,
        *,
        decision_time: time = time(15, 15),
        sma_window: int = 20,
        volume_window: int = 5,
        support_band: Decimal = Decimal("0.02"),
        max_volume_ratio: Decimal = Decimal("0.50"),
        max_rsi: Decimal = Decimal("40"),
    ) -> None:
        self.decision_time = decision_time
        self.sma_window = sma_window
        self.volume_window = volume_window
        self.support_band = support_band
        self.max_volume_ratio = max_volume_ratio
        self.max_rsi = max_rsi
        self._session_date: date | None = None
        self._day_volume = 0
        self._day_close: Decimal | None = None
        self._daily_closes: deque[Decimal] = deque(maxlen=max(sma_window, 14) + 1)
        self._daily_volumes: deque[int] = deque(maxlen=volume_window)
        self._entered = False

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        self._roll_session(bar)
        self._day_volume += bar.volume
        self._day_close = bar.close

        current_time = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).time()
        if current_time < self.decision_time:
            return SignalIntent("hold", reason="no-entry")
        if self._entered:
            return SignalIntent("hold", reason="already-entered")
        if not self._has_history():
            return SignalIntent("hold", reason="warming-up")
        if not risk.allows_entry(bar):
            return SignalIntent("hold", reason=risk.block_reason(bar))

        closes = [*self._daily_closes, bar.close]
        sma = sum(closes[-self.sma_window :], Decimal("0")) / Decimal(self.sma_window)
        distance = abs((bar.close - sma) / sma)
        average_volume = Decimal(sum(self._daily_volumes)) / Decimal(len(self._daily_volumes))
        volume_ratio = Decimal(self._day_volume) / average_volume if average_volume else Decimal("999")
        rsi = _rsi(closes[-15:])

        if (
            distance <= self.support_band
            and volume_ratio <= self.max_volume_ratio
            and rsi < self.max_rsi
        ):
            self._entered = True
            support_score = self.support_band - distance + (self.max_rsi - rsi) / Decimal("100")
            volume_score = self.max_volume_ratio - volume_ratio
            return SignalIntent(
                "buy",
                weight=risk.beta_multiplier(),
                reason="swing-support",
                score=_signal_score(Decimal("1") + volume_score, support_score),
            )
        return SignalIntent("hold", reason="no-entry")

    def _has_history(self) -> bool:
        return len(self._daily_closes) >= self.sma_window - 1 and len(self._daily_volumes) >= self.volume_window

    def _roll_session(self, bar: Bar) -> None:
        session_date = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()
        if self._session_date is None:
            self._session_date = session_date
            return
        if session_date == self._session_date:
            return
        if self._day_close is not None:
            self._daily_closes.append(self._day_close)
            self._daily_volumes.append(self._day_volume)
        self._session_date = session_date
        self._day_volume = 0
        self._day_close = None
        self._entered = False


class DaySupportPullbackStrategy:
    def __init__(
        self,
        *,
        entry_start: time = time(13, 30),
        entry_end: time = time(14, 45),
        sma_window: int = 20,
        volume_window: int = 5,
        support_band: Decimal = Decimal("0.02"),
        max_volume_ratio: Decimal = Decimal("0.50"),
        max_rsi: Decimal = Decimal("40"),
        min_bid_ask_ratio: Decimal = Decimal("1.5"),
    ) -> None:
        self.entry_start = entry_start
        self.entry_end = entry_end
        self.sma_window = sma_window
        self.volume_window = volume_window
        self.support_band = support_band
        self.max_volume_ratio = max_volume_ratio
        self.max_rsi = max_rsi
        self.min_bid_ask_ratio = min_bid_ask_ratio
        self._session_date: date | None = None
        self._day_volume = 0
        self._day_close: Decimal | None = None
        self._daily_closes: deque[Decimal] = deque(maxlen=max(sma_window, 14) + 1)
        self._daily_volumes: deque[int] = deque(maxlen=volume_window)
        self._entered = False

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        self._roll_session(bar)
        self._day_volume += bar.volume
        self._day_close = bar.close

        if self._entered:
            return SignalIntent("hold", reason="already-entered")
        if not self._within_entry_window(bar):
            return SignalIntent("hold", reason="entry-window")
        if not self._has_history():
            return SignalIntent("hold", reason="warming-up")
        if not risk.allows_entry(bar):
            return SignalIntent("hold", reason=risk.block_reason(bar))
        if bar.bid_ask_ratio < self.min_bid_ask_ratio:
            return SignalIntent("hold", reason="weak-pressure")

        closes = [*self._daily_closes, bar.close]
        sma = sum(closes[-self.sma_window :], Decimal("0")) / Decimal(self.sma_window)
        distance = abs((bar.close - sma) / sma)
        average_volume = Decimal(sum(self._daily_volumes)) / Decimal(len(self._daily_volumes))
        volume_ratio = Decimal(self._day_volume) / average_volume if average_volume else Decimal("999")
        rsi = _rsi(closes[-15:])

        if (
            distance <= self.support_band
            and volume_ratio <= self.max_volume_ratio
            and rsi < self.max_rsi
        ):
            self._entered = True
            support_score = self.support_band - distance + (self.max_rsi - rsi) / Decimal("100")
            return SignalIntent(
                "buy",
                weight=risk.beta_multiplier(),
                reason="day-support-pullback",
                score=_signal_score(bar.bid_ask_ratio, support_score),
            )
        return SignalIntent("hold", reason="no-entry")

    def _has_history(self) -> bool:
        return len(self._daily_closes) >= self.sma_window - 1 and len(self._daily_volumes) >= self.volume_window

    def _within_entry_window(self, bar: Bar) -> bool:
        current = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).time()
        return self.entry_start <= current <= self.entry_end

    def _roll_session(self, bar: Bar) -> None:
        session_date = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()
        if self._session_date is None:
            self._session_date = session_date
            return
        if session_date == self._session_date:
            return
        if self._day_close is not None:
            self._daily_closes.append(self._day_close)
            self._daily_volumes.append(self._day_volume)
        self._session_date = session_date
        self._day_volume = 0
        self._day_close = None
        self._entered = False


class IntradayMomentumSwingSupportPortfolioStrategy:
    def __init__(self, *, regimes: dict[date, object] | None = None, allowed_regimes: frozenset[str] = frozenset()) -> None:
        self.day = IntradayMomentumContinuationStrategy(
            min_average_value=Decimal("50000000000"),
            min_atr_ratio=Decimal("0.03"),
            min_session_value=Decimal("1000000000"),
            min_bid_ask_ratio=Decimal("2.0"),
            entry_start=time(10, 0),
            entry_end=time(13, 30),
            min_day_return=Decimal("0.035"),
            max_day_return=Decimal("0.12"),
            min_vwap_distance=Decimal("0.004"),
        )
        self.swing = SwingSupportStrategy(
            sma_window=20,
            volume_window=5,
            support_band=Decimal("0.018"),
            max_volume_ratio=Decimal("0.2"),
            max_rsi=Decimal("58"),
        )
        self.regimes = regimes or {}
        self.allowed_regimes = allowed_regimes

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        day_signal = self.day.on_bar(bar, risk)
        swing_signal = self.swing.on_bar(bar, risk)
        if day_signal.action == "buy" and not self._day_regime_allows(bar):
            day_signal = SignalIntent("hold", reason="portfolio-day-regime-block")
        candidates = [
            _with_exit_policy(
                day_signal,
                profit_target=Decimal("0.08"),
                hard_stop=Decimal("-0.018"),
                max_holding_minutes=180,
                day_end_exit=True,
                group="day",
            ),
            _with_exit_policy(
                swing_signal,
                profit_target=Decimal("0.03"),
                hard_stop=Decimal("-0.03"),
                max_holding_minutes=10080,
                day_end_exit=False,
                group="swing",
            ),
        ]
        buy_candidates = [signal for signal in candidates if signal.action == "buy" and signal.weight > 0]
        if not buy_candidates:
            return SignalIntent(
                "hold",
                reason=f"portfolio-no-entry(day={day_signal.reason or 'unknown'},swing={swing_signal.reason or 'unknown'})",
            )
        return max(buy_candidates, key=lambda signal: signal.score)

    def _day_regime_allows(self, bar: Bar) -> bool:
        if not self.allowed_regimes:
            return True
        session_date = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()
        regime = self.regimes.get(session_date)
        return regime is not None and getattr(regime, "name", None) in self.allowed_regimes


def _with_exit_policy(
    signal: SignalIntent,
    *,
    profit_target: Decimal,
    hard_stop: Decimal,
    max_holding_minutes: int,
    day_end_exit: bool,
    group: str = "",
) -> SignalIntent:
    if signal.action != "buy":
        return signal
    return SignalIntent(
        signal.action,
        weight=signal.weight,
        reason=signal.reason,
        score=signal.score,
        profit_target=profit_target,
        hard_stop=hard_stop,
        max_holding_minutes=max_holding_minutes,
        day_end_exit=day_end_exit,
        group=group,
    )


def _rsi(closes: list[Decimal]) -> Decimal:
    if len(closes) < 15:
        return Decimal("100")
    gains = Decimal("0")
    losses = Decimal("0")
    for previous, current in zip(closes, closes[1:]):
        change = current - previous
        if change >= 0:
            gains += change
        else:
            losses += abs(change)
    if losses == 0:
        return Decimal("100")
    rs = gains / losses
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def _signal_score(pressure: Decimal, edge: Decimal) -> Decimal:
    return pressure + edge * Decimal("100")


def _atr(highs: list[Decimal], lows: list[Decimal], closes: list[Decimal], window: int) -> Decimal:
    if len(highs) < window or len(lows) < window or len(closes) < window:
        return Decimal("0")
    start = max(0, len(highs) - window)
    ranges: list[Decimal] = []
    for index in range(start, len(highs)):
        high = highs[index]
        low = lows[index]
        previous_close = closes[index - 1] if index > 0 else closes[index]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    if not ranges:
        return Decimal("0")
    return sum(ranges, Decimal("0")) / Decimal(len(ranges))


class SwingMomentumStrategy:
    def __init__(
        self,
        *,
        decision_time: time = time(15, 15),
        sma_window: int = 20,
        volume_window: int = 5,
        min_sma_distance: Decimal = Decimal("0.01"),
        min_volume_ratio: Decimal = Decimal("1.00"),
        min_rsi: Decimal = Decimal("55"),
    ) -> None:
        self.decision_time = decision_time
        self.sma_window = sma_window
        self.volume_window = volume_window
        self.min_sma_distance = min_sma_distance
        self.min_volume_ratio = min_volume_ratio
        self.min_rsi = min_rsi
        self._session_date: date | None = None
        self._day_volume = 0
        self._day_close: Decimal | None = None
        self._daily_closes: deque[Decimal] = deque(maxlen=max(sma_window, 14) + 1)
        self._daily_volumes: deque[int] = deque(maxlen=volume_window)
        self._entered = False

    def on_bar(self, bar: Bar, risk: RiskState | None = None) -> SignalIntent:
        risk = risk or RiskState()
        self._roll_session(bar)
        self._day_volume += bar.volume
        self._day_close = bar.close

        current_time = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).time()
        if current_time < self.decision_time:
            return SignalIntent("hold", reason="no-entry")
        if self._entered:
            return SignalIntent("hold", reason="already-entered")
        if len(self._daily_closes) < self.sma_window - 1 or len(self._daily_volumes) < self.volume_window:
            return SignalIntent("hold", reason="warming-up")
        if not risk.allows_entry(bar):
            return SignalIntent("hold", reason=risk.block_reason(bar))

        closes = [*self._daily_closes, bar.close]
        sma = sum(closes[-self.sma_window :], Decimal("0")) / Decimal(self.sma_window)
        sma_distance = (bar.close - sma) / sma
        average_volume = Decimal(sum(self._daily_volumes)) / Decimal(len(self._daily_volumes))
        volume_ratio = Decimal(self._day_volume) / average_volume if average_volume else Decimal("0")
        rsi = _rsi(closes[-15:])

        if (
            sma_distance >= self.min_sma_distance
            and volume_ratio >= self.min_volume_ratio
            and rsi >= self.min_rsi
        ):
            self._entered = True
            momentum_score = sma_distance + (rsi - self.min_rsi) / Decimal("100")
            return SignalIntent(
                "buy",
                weight=risk.beta_multiplier(),
                reason="swing-momentum",
                score=_signal_score(volume_ratio, momentum_score),
            )
        return SignalIntent("hold", reason="no-entry")

    def _roll_session(self, bar: Bar) -> None:
        session_date = bar.timestamp.astimezone(ZoneInfo("Asia/Seoul")).date()
        if self._session_date is None:
            self._session_date = session_date
            return
        if session_date == self._session_date:
            return
        if self._day_close is not None:
            self._daily_closes.append(self._day_close)
            self._daily_volumes.append(self._day_volume)
        self._session_date = session_date
        self._day_volume = 0
        self._day_close = None
        self._entered = False
