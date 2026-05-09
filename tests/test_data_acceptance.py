from zurini.data.acceptance import CsvAcceptanceCriteria, assess_csv_scan
from zurini.data.csv_quality import CsvScanSummary


def _summary(**overrides):
    values = {
        "root": "data/raw/daishin/minute-bars",
        "file_count": 2,
        "ok_count": 2,
        "error_count": 0,
        "success_rate": 1.0,
        "row_count": 100,
        "duplicate_timestamp_count": 0,
        "gap_count": 0,
        "zero_volume_count": 0,
        "symbol_count": 2,
        "period_count": 24,
        "first_timestamp": "2024-01-02T09:00:00+09:00",
        "last_timestamp": "2025-12-30T15:30:00+09:00",
        "error_paths": [],
        "results": [],
    }
    values.update(overrides)
    return CsvScanSummary(**values)


def test_csv_acceptance_accepts_clean_scan_at_thresholds():
    result = assess_csv_scan(
        _summary(gap_count=3, zero_volume_count=1),
        CsvAcceptanceCriteria(max_gap_count=3, max_zero_volume_count=1, min_symbol_count=2, min_period_count=24),
    )

    assert result.accepted is True
    assert result.status == "accepted"
    assert result.failures == []


def test_csv_acceptance_reports_all_threshold_failures():
    result = assess_csv_scan(
        _summary(
            error_count=1,
            success_rate=0.5,
            duplicate_timestamp_count=2,
            gap_count=4,
            zero_volume_count=3,
            symbol_count=1,
            period_count=12,
        ),
        CsvAcceptanceCriteria(
            min_success_rate=1.0,
            max_error_count=0,
            max_duplicate_timestamp_count=0,
            max_gap_count=0,
            max_zero_volume_count=0,
            min_symbol_count=2,
            min_period_count=24,
        ),
    )

    assert result.accepted is False
    assert result.status == "rejected"
    assert result.failures == [
        "success_rate 0.5000 < 1.0000",
        "error_count 1 > 0",
        "duplicate_timestamp_count 2 > 0",
        "gap_count 4 > 0",
        "zero_volume_count 3 > 0",
        "symbol_count 1 < 2",
        "period_count 12 < 24",
    ]
