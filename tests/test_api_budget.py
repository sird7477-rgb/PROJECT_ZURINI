from __future__ import annotations

from datetime import datetime
from datetime import timezone
from zoneinfo import ZoneInfo

from zurini.api_budget import FieldApiBudgetPolicy, build_read_call_budget_evidence


def test_field_api_budget_uses_provider_limit_as_ceiling_not_target():
    policy = FieldApiBudgetPolicy(provider_limit_per_second=20)
    normal = policy.window_for(datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))

    assert normal.total_limit_per_second == 12
    assert normal.scouter_limit_per_second == 10
    assert normal.reserved_limit_per_second == 2


def test_field_api_budget_reduces_scouter_capacity_in_critical_windows():
    policy = FieldApiBudgetPolicy(provider_limit_per_second=20)

    open_window = policy.window_for(datetime(2026, 5, 11, 9, 5, tzinfo=ZoneInfo("Asia/Seoul")))
    lock_step = policy.window_for(datetime(2026, 5, 11, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")))

    assert open_window.name == "open-burst"
    assert open_window.total_limit_per_second == 7
    assert open_window.scouter_limit_per_second == 5
    assert lock_step.name == "lock-step-1515"
    assert lock_step.total_limit_per_second == 7
    assert lock_step.scouter_limit_per_second == 5


def test_field_api_budget_normalizes_utc_timestamps_to_kst_windows():
    policy = FieldApiBudgetPolicy(provider_limit_per_second=20)

    window = policy.window_for(datetime(2026, 5, 11, 0, 5, tzinfo=timezone.utc))

    assert window.name == "open-burst"
    assert window.total_limit_per_second == 7


def test_field_api_budget_respects_lower_provider_limits():
    policy = FieldApiBudgetPolicy(provider_limit_per_second=5)

    normal = policy.window_for(datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))
    critical = policy.window_for(datetime(2026, 5, 11, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")))

    assert normal.total_limit_per_second == 5
    assert normal.scouter_limit_per_second == 5
    assert critical.total_limit_per_second == 5
    assert critical.scouter_limit_per_second == 5


def test_read_call_budget_evidence_uses_measured_peak_not_provider_ceiling():
    evidence = build_read_call_budget_evidence(
        measured_read_calls=42,
        measured_peak_per_second=8,
        observed_at=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        source="kis-readonly-universe",
        observed_latency_ms=180,
    )

    assert evidence.provider_limit_per_second == 20
    assert evidence.operating_limit_per_second == 12
    assert evidence.measured_read_calls == 42
    assert evidence.measured_peak_per_second == 8
    assert evidence.latency_bucket == "le_250ms"
    assert evidence.within_budget is True


def test_read_call_budget_evidence_blocks_throttle_or_critical_window_breach():
    critical = build_read_call_budget_evidence(
        measured_read_calls=12,
        measured_peak_per_second=8,
        observed_at=datetime(2026, 5, 11, 15, 15, tzinfo=ZoneInfo("Asia/Seoul")),
        source="field-polling-smoke",
    )
    throttled = build_read_call_budget_evidence(
        measured_read_calls=2,
        measured_peak_per_second=1,
        observed_at=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        source="kis-readonly-universe",
        api_flags=("api_rate_limit_risk",),
    )

    assert critical.window == "lock-step-1515"
    assert critical.operating_limit_per_second == 7
    assert critical.within_budget is False
    assert throttled.throttle_flag is True
    assert throttled.within_budget is False


def test_read_call_budget_evidence_enforces_scouter_share_limit():
    evidence = build_read_call_budget_evidence(
        measured_read_calls=201,
        measured_peak_per_second=6,
        observed_at=datetime(2026, 5, 11, 9, 5, tzinfo=ZoneInfo("Asia/Seoul")),
        source="kis-readonly-universe",
    )

    assert evidence.window == "open-burst"
    assert evidence.operating_limit_per_second == 7
    assert evidence.scouter_limit_per_second == 5
    assert evidence.within_budget is False
