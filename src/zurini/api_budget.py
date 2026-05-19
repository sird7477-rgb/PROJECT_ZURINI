from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


def normalize_to_kst(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=KST)
    return timestamp.astimezone(KST)


@dataclass(frozen=True)
class ApiBudgetWindow:
    name: str
    total_limit_per_second: int
    scouter_limit_per_second: int
    reserved_limit_per_second: int


@dataclass(frozen=True)
class FieldApiBudgetPolicy:
    provider_limit_per_second: int = 20
    normal_total_limit_per_second: int = 15
    normal_scouter_limit_per_second: int = 10
    critical_total_limit_per_second: int = 7
    critical_scouter_limit_per_second: int = 5

    def window_for(self, timestamp: datetime) -> ApiBudgetWindow:
        current_time = normalize_to_kst(timestamp).time()
        if time(9, 0) <= current_time <= time(9, 10):
            return self._critical_window("open-burst")
        if time(15, 10) <= current_time <= time(15, 20):
            return self._critical_window("lock-step-1515")
        total = min(self.provider_limit_per_second, self.normal_total_limit_per_second)
        scouter = min(total, self.normal_scouter_limit_per_second)
        return ApiBudgetWindow(
            name="normal",
            total_limit_per_second=total,
            scouter_limit_per_second=scouter,
            reserved_limit_per_second=max(0, total - scouter),
        )

    def minimum_total_limit_for(self, timestamps: list[datetime]) -> int:
        if not timestamps:
            return min(self.provider_limit_per_second, self.normal_total_limit_per_second)
        return min(self.window_for(timestamp).total_limit_per_second for timestamp in timestamps)

    def _critical_window(self, name: str) -> ApiBudgetWindow:
        total = min(self.provider_limit_per_second, self.critical_total_limit_per_second)
        scouter = min(total, self.critical_scouter_limit_per_second)
        return ApiBudgetWindow(
            name=name,
            total_limit_per_second=total,
            scouter_limit_per_second=scouter,
            reserved_limit_per_second=max(0, total - scouter),
        )


@dataclass(frozen=True)
class ReadCallBudgetEvidence:
    provider: str
    source: str
    window: str
    provider_limit_per_second: int
    operating_limit_per_second: int
    scouter_limit_per_second: int
    reserved_limit_per_second: int
    measured_read_calls: int
    measured_peak_per_second: int
    latency_bucket: str
    throttle_flag: bool
    within_budget: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source": self.source,
            "window": self.window,
            "provider_limit_per_second": self.provider_limit_per_second,
            "operating_limit_per_second": self.operating_limit_per_second,
            "scouter_limit_per_second": self.scouter_limit_per_second,
            "reserved_limit_per_second": self.reserved_limit_per_second,
            "measured_read_calls": self.measured_read_calls,
            "measured_peak_per_second": self.measured_peak_per_second,
            "latency_bucket": self.latency_bucket,
            "throttle_flag": self.throttle_flag,
            "within_budget": self.within_budget,
        }


def build_read_call_budget_evidence(
    *,
    measured_read_calls: int,
    measured_peak_per_second: int,
    observed_at: datetime,
    source: str,
    provider: str = "KIS",
    observed_latency_ms: int | None = None,
    api_flags: tuple[str, ...] = (),
    policy: FieldApiBudgetPolicy | None = None,
) -> ReadCallBudgetEvidence:
    if measured_read_calls < 0:
        raise ValueError("measured_read_calls must be non-negative")
    if measured_peak_per_second < 0:
        raise ValueError("measured_peak_per_second must be non-negative")
    if observed_latency_ms is not None and observed_latency_ms < 0:
        raise ValueError("observed_latency_ms must be non-negative")

    active_policy = policy or FieldApiBudgetPolicy()
    window = active_policy.window_for(observed_at)
    throttle_flag = "api_rate_limit_risk" in api_flags
    within_budget = (
        measured_peak_per_second <= window.total_limit_per_second
        and measured_peak_per_second <= window.scouter_limit_per_second
        and measured_peak_per_second <= active_policy.provider_limit_per_second
        and not throttle_flag
    )
    return ReadCallBudgetEvidence(
        provider=provider,
        source=source,
        window=window.name,
        provider_limit_per_second=active_policy.provider_limit_per_second,
        operating_limit_per_second=window.total_limit_per_second,
        scouter_limit_per_second=window.scouter_limit_per_second,
        reserved_limit_per_second=window.reserved_limit_per_second,
        measured_read_calls=measured_read_calls,
        measured_peak_per_second=measured_peak_per_second,
        latency_bucket=_latency_bucket(observed_latency_ms),
        throttle_flag=throttle_flag,
        within_budget=within_budget,
    )


def estimate_index_poll_read_calls(
    *,
    index_count: int,
    session_minutes: int = 390,
    poll_interval_seconds: int = 10,
) -> int:
    if index_count < 0:
        raise ValueError("index_count must be non-negative")
    if session_minutes < 0:
        raise ValueError("session_minutes must be non-negative")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    session_seconds = session_minutes * 60
    polls_per_index = math.ceil(session_seconds / poll_interval_seconds)
    return index_count * polls_per_index


def _latency_bucket(observed_latency_ms: int | None) -> str:
    if observed_latency_ms is None:
        return "unknown"
    if observed_latency_ms <= 250:
        return "le_250ms"
    if observed_latency_ms <= 1000:
        return "le_1000ms"
    return "gt_1000ms"
