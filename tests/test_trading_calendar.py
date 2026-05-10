from __future__ import annotations

from datetime import date, time

from zurini.data.calendar import load_trading_calendar


def test_trading_calendar_excludes_weekends_and_seeded_holidays():
    calendar = load_trading_calendar()

    assert calendar.is_trading_day(date(2026, 5, 4)) is True
    assert calendar.is_trading_day(date(2026, 5, 1)) is False
    assert calendar.is_trading_day(date(2026, 5, 5)) is False
    assert calendar.is_trading_day(date(2026, 5, 9)) is False


def test_trading_calendar_returns_special_session_window():
    calendar = load_trading_calendar()

    assert calendar.session_window_for(date(2025, 11, 13)) == (time(10, 1), time(16, 30))
    assert calendar.session_window_for(date(2026, 5, 4)) == (time(9, 1), time(15, 30))


def test_trading_calendar_default_path_resolves_outside_repo_root(tmp_path, monkeypatch):
    load_trading_calendar.cache_clear()
    monkeypatch.chdir(tmp_path)

    calendar = load_trading_calendar()

    assert calendar.version == "krx-korean-equity-v1"
