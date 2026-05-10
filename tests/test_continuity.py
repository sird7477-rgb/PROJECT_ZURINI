from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from zurini.data.continuity import assess_trade_continuity, summarize_trades_by_continuity
from zurini.market import Bar, Trade

KST = ZoneInfo("Asia/Seoul")


def _bar(symbol: str, timestamp: datetime) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=1,
        value=Decimal("100"),
        source="test",
    )


def _trade(symbol: str, entry_time: datetime, exit_time: datetime) -> Trade:
    return Trade(
        symbol=symbol,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        quantity=Decimal("1"),
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        reason="test",
    )


def test_trade_continuity_passes_when_entry_and_exit_windows_are_complete():
    entry = datetime(2026, 5, 4, 9, 10, tzinfo=KST)
    exit_ = datetime(2026, 5, 4, 9, 20, tzinfo=KST)
    bars = [_bar("A000001", entry + timedelta(minutes=offset)) for offset in range(-2, 13)]

    result = assess_trade_continuity(
        bars,
        [_trade("A000001", entry, exit_)],
        window_minutes=2,
        session_start=time(9, 0),
    )

    assert result.status == "passed"
    assert result.checked_points == 2
    assert result.failed_points == 0
    assert result.missing_minutes == 0


def test_trade_continuity_fails_when_trade_window_has_missing_minutes():
    entry = datetime(2026, 5, 4, 9, 10, tzinfo=KST)
    exit_ = datetime(2026, 5, 4, 9, 20, tzinfo=KST)
    bars = [
        _bar("A000001", entry),
        _bar("A000001", entry + timedelta(minutes=1)),
        _bar("A000001", exit_),
    ]

    result = assess_trade_continuity(
        bars,
        [_trade("A000001", entry, exit_)],
        window_minutes=2,
        session_start=time(9, 0),
    )

    assert result.status == "failed"
    assert result.checked_points == 2
    assert result.failed_points == 2
    assert result.missing_minutes == 7


def test_trade_continuity_ignores_minutes_outside_regular_session():
    entry = datetime(2026, 5, 4, 9, 0, tzinfo=KST)
    exit_ = datetime(2026, 5, 4, 15, 30, tzinfo=KST)
    bars = [
        _bar("A000001", entry + timedelta(minutes=1)),
        _bar("A000001", entry + timedelta(minutes=2)),
        _bar("A000001", exit_ - timedelta(minutes=1)),
        _bar("A000001", exit_ - timedelta(minutes=2)),
    ]

    result = assess_trade_continuity(
        bars,
        [_trade("A000001", entry, exit_)],
        window_minutes=2,
        session_start=time(9, 0),
    )

    assert result.status == "passed"
    assert result.checked_points == 2
    assert result.failed_points == 0
    assert result.missing_minutes == 0
    assert result.session_start == "09:00"
    assert result.session_end == "15:30"


def test_trade_continuity_uses_calendar_regular_session_start_by_default():
    entry = datetime(2026, 5, 4, 9, 0, tzinfo=KST)
    exit_ = datetime(2026, 5, 4, 9, 2, tzinfo=KST)
    bars = [_bar("A000001", exit_)]

    result = assess_trade_continuity(bars, [_trade("A000001", entry, exit_)], audit_mode="exact-bar")

    assert result.status == "failed"
    assert result.session_start == "09:01"
    assert result.checks[0].status == "out_of_session"


def test_trade_continuity_flags_out_of_session_trades():
    entry = datetime(2026, 5, 4, 8, 59, tzinfo=KST)
    exit_ = datetime(2026, 5, 4, 9, 2, tzinfo=KST)
    bars = [_bar("A000001", exit_ + timedelta(minutes=offset)) for offset in range(-2, 3)]

    result = assess_trade_continuity(bars, [_trade("A000001", entry, exit_)], window_minutes=2)

    assert result.status == "failed"
    assert result.failed_points == 1
    assert result.checks[0].status == "out_of_session"


def test_trade_continuity_checks_session_in_korean_time_for_utc_timestamps():
    entry = datetime(2026, 5, 4, 9, 10, tzinfo=KST).astimezone(UTC)
    exit_ = datetime(2026, 5, 4, 9, 20, tzinfo=KST).astimezone(UTC)
    bars = [_bar("A000001", entry + timedelta(minutes=offset)) for offset in range(-2, 13)]

    result = assess_trade_continuity(bars, [_trade("A000001", entry, exit_)], window_minutes=2)

    assert result.status == "passed"
    assert result.failed_points == 0


def test_trade_continuity_uses_known_special_session_end():
    entry = datetime(2025, 11, 13, 16, 28, tzinfo=KST)
    exit_ = datetime(2025, 11, 13, 16, 30, tzinfo=KST)
    bars = [_bar("A000001", entry), _bar("A000001", exit_)]

    result = assess_trade_continuity(bars, [_trade("A000001", entry, exit_)], audit_mode="exact-bar")

    assert result.status == "passed"
    assert result.failed_points == 0


def test_trade_continuity_trade_summary_splits_valid_and_invalid_trades():
    valid_entry = datetime(2026, 5, 4, 9, 10, tzinfo=KST)
    valid_exit = datetime(2026, 5, 4, 9, 20, tzinfo=KST)
    invalid_entry = datetime(2026, 5, 4, 10, 10, tzinfo=KST)
    invalid_exit = datetime(2026, 5, 4, 10, 20, tzinfo=KST)
    bars = [
        _bar("A000001", valid_entry + timedelta(minutes=offset))
        for offset in range(-2, 13)
    ] + [_bar("A000002", invalid_entry), _bar("A000002", invalid_exit)]
    trades = [
        _trade("A000001", valid_entry, valid_exit),
        _trade("A000002", invalid_entry, invalid_exit),
    ]

    continuity = assess_trade_continuity(bars, trades, window_minutes=2)
    summary = summarize_trades_by_continuity(trades, continuity)

    assert summary.total_trades == 2
    assert summary.valid_trades == 1
    assert summary.invalid_trades == 1
    assert summary.valid_net_pnl == Decimal("1")
    assert summary.invalid_net_pnl == Decimal("1")
    assert summary.invalid_reasons == {"test": 1}


def test_exact_bar_trade_continuity_passes_sparse_observed_entry_and_exit():
    entry = datetime(2026, 5, 4, 9, 10, tzinfo=KST)
    exit_ = datetime(2026, 5, 4, 9, 20, tzinfo=KST)
    bars = [_bar("A000001", entry), _bar("A000001", exit_)]

    result = assess_trade_continuity(bars, [_trade("A000001", entry, exit_)], audit_mode="exact-bar")

    assert result.status == "passed"
    assert result.failed_points == 0
    assert all(check.audit_mode == "exact-bar" for check in result.checks)
    assert all(check.exact_bar_present is True for check in result.checks)


def test_exact_bar_trade_continuity_fails_when_exact_entry_is_missing_even_with_neighbors():
    entry = datetime(2026, 5, 4, 9, 10, tzinfo=KST)
    exit_ = datetime(2026, 5, 4, 9, 20, tzinfo=KST)
    bars = [
        _bar("A000001", entry - timedelta(minutes=1)),
        _bar("A000001", entry + timedelta(minutes=1)),
        _bar("A000001", exit_),
    ]

    result = assess_trade_continuity(bars, [_trade("A000001", entry, exit_)], audit_mode="exact-bar")

    assert result.status == "failed"
    assert result.failed_points == 1
    assert result.checks[0].status == "missing_exact_bar"
    assert result.checks[0].exact_bar_present is False
    assert result.checks[0].previous_observed_distance_minutes == 1
    assert result.checks[0].next_observed_distance_minutes == 1


def test_trade_continuity_rejects_unknown_audit_mode():
    entry = datetime(2026, 5, 4, 9, 10, tzinfo=KST)

    try:
        assess_trade_continuity([], [_trade("A000001", entry, entry)], audit_mode="unknown")
    except ValueError as exc:
        assert "audit_mode" in str(exc)
    else:
        raise AssertionError("expected ValueError")
