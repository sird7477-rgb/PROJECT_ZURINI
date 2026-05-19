from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from zurini.research_minute_dataset import (
    normalize_research_minute_row,
    rows_within_rolling_window,
    select_canonical_minute_row,
)


KST = ZoneInfo("Asia/Seoul")


def _row(
    *,
    source: str = "legacy-daishin",
    vendor: str = "daishin",
    close: str = "100",
    timestamp: datetime | None = None,
):
    return normalize_research_minute_row(
        symbol="A005930",
        timestamp=timestamp or datetime(2026, 5, 15, 10, 0, tzinfo=KST),
        open_price=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=1000,
        value=Decimal("100000"),
        source=source,
        vendor=vendor,
        source_run_id="run-1",
        import_batch_id="batch-1",
    )


def test_normalize_research_minute_row_flags_missing_kis_fields() -> None:
    row = normalize_research_minute_row(
        symbol="A005930",
        timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=KST),
        open_price=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=None,
        value=None,
        source="kis-minute-poll",
        vendor="kis",
        source_run_id="run-1",
        import_batch_id="batch-1",
    )

    assert row.quality_flags == (
        "volume_missing",
        "value_missing",
        "bid_ask_ratio_missing",
        "kis_row_degraded",
    )
    assert row.as_dict()["close"] == "100"


def test_normalize_research_minute_row_keeps_operating_fields_nullable() -> None:
    row = normalize_research_minute_row(
        symbol="A005930",
        timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=KST),
        open_price=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=1000,
        value=Decimal("100000"),
        bid_ask_ratio=Decimal("2.3"),
        traded_value=Decimal("100000"),
        action="buy",
        passed=True,
        rank=1,
        reason="entry",
        score=Decimal("0.7"),
        strategy_group="day",
        input_flags=("fresh_quote",),
        data_origin="field-observation",
        source="field-monitor-local",
        vendor="kis",
        source_run_id="run-1",
        import_batch_id="batch-1",
    )

    payload = row.as_dict()
    assert payload["bid_ask_ratio"] == "2.3"
    assert payload["passed"] is True
    assert payload["input_flags"] == ["fresh_quote"]


def test_normalize_research_minute_row_infers_minute_data_origin_tags() -> None:
    legacy = _row()
    field = normalize_research_minute_row(
        symbol="A005930",
        timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=KST),
        open_price=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=1000,
        value=Decimal("100000"),
        source="kis-minute-poll",
        vendor="kis",
        source_run_id="run-1",
        import_batch_id="batch-1",
    )

    assert legacy.data_origin == "legacy-minute-backfill"
    assert legacy.interval == "1m"
    assert field.data_origin == "field-observation"
    assert field.interval == "1m"


def test_normalize_research_minute_row_rejects_unknown_origin_daily_source_and_bad_interval() -> None:
    with pytest.raises(ValueError, match="data_origin"):
        normalize_research_minute_row(
            symbol="A005930",
            timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=KST),
            open_price=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            value=Decimal("100000"),
            data_origin="other",
            source="manual",
            vendor="manual",
            source_run_id="run-1",
            import_batch_id="batch-1",
        )

    with pytest.raises(ValueError, match="universe_daily"):
        normalize_research_minute_row(
            symbol="A005930",
            timestamp=datetime(2026, 5, 14, 15, 15, tzinfo=KST),
            open_price=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            value=Decimal("100000"),
            source="kis-daily-bars",
            vendor="kis",
            source_run_id="run-1",
            import_batch_id="batch-1",
        )

    with pytest.raises(ValueError, match="interval"):
        normalize_research_minute_row(
            symbol="A005930",
            timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=KST),
            open_price=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=1000,
            value=Decimal("100000"),
            data_origin="field-observation",
            interval="1d-close",
            source="kis-minute-poll",
            vendor="kis",
            source_run_id="run-1",
            import_batch_id="batch-1",
        )


def test_select_canonical_minute_row_prefers_kis_and_flags_conflict() -> None:
    legacy = _row(close="100")
    kis = _row(source="kis-minute-poll", vendor="kis", close="101")

    selection = select_canonical_minute_row([legacy, kis])

    assert selection.row.source == "kis-minute-poll"
    assert selection.source_count == 2
    assert selection.conflict_flags == ("source_overlap_conflict",)
    assert selection.as_bar().source == "kis:kis-minute-poll"


def test_select_canonical_minute_row_keeps_complete_legacy_over_degraded_kis() -> None:
    legacy = _row(close="100")
    kis = normalize_research_minute_row(
        symbol="A005930",
        timestamp=legacy.timestamp,
        open_price=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=None,
        value=None,
        source="kis-minute-poll",
        vendor="kis",
        source_run_id="run-1",
        import_batch_id="batch-2",
    )

    selection = select_canonical_minute_row([kis, legacy])

    assert selection.row.source == "legacy-daishin"
    assert selection.row.volume == 1000
    assert selection.row.value == Decimal("100000")
    assert selection.conflict_flags == ("source_overlap_conflict",)


def test_select_canonical_minute_row_rejects_mixed_keys() -> None:
    with pytest.raises(ValueError, match="one symbol/timestamp/interval"):
        select_canonical_minute_row(
            [
                _row(timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=KST)),
                _row(timestamp=datetime(2026, 5, 15, 10, 1, tzinfo=KST)),
            ]
        )


def test_rows_within_rolling_window_keeps_latest_two_years() -> None:
    latest = datetime(2026, 5, 15, 10, 0, tzinfo=KST)
    rows = [
        _row(timestamp=latest - timedelta(days=731)),
        _row(timestamp=latest - timedelta(days=730)),
        _row(timestamp=latest),
    ]

    kept = rows_within_rolling_window(rows, latest_timestamp=latest)

    assert len(kept) == 2
    assert [row.timestamp for row in kept] == [latest - timedelta(days=730), latest]
