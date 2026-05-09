from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from zurini.data.csv_quality import CsvScanSummary


@dataclass(frozen=True)
class CsvAcceptanceCriteria:
    min_success_rate: float = 1.0
    max_error_count: int = 0
    max_duplicate_timestamp_count: int = 0
    max_gap_count: int | None = None
    max_zero_volume_count: int | None = None
    min_symbol_count: int | None = None
    min_period_count: int | None = None


@dataclass(frozen=True)
class CsvAcceptanceResult:
    status: str
    failures: list[str]
    criteria: CsvAcceptanceCriteria

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["criteria"] = asdict(self.criteria)
        return payload


def assess_csv_scan(summary: CsvScanSummary, criteria: CsvAcceptanceCriteria) -> CsvAcceptanceResult:
    failures: list[str] = []
    if summary.success_rate < criteria.min_success_rate:
        failures.append(f"success_rate {summary.success_rate:.4f} < {criteria.min_success_rate:.4f}")
    if summary.error_count > criteria.max_error_count:
        failures.append(f"error_count {summary.error_count} > {criteria.max_error_count}")
    if summary.duplicate_timestamp_count > criteria.max_duplicate_timestamp_count:
        failures.append(
            "duplicate_timestamp_count "
            f"{summary.duplicate_timestamp_count} > {criteria.max_duplicate_timestamp_count}"
        )
    if criteria.max_gap_count is not None and summary.gap_count > criteria.max_gap_count:
        failures.append(f"gap_count {summary.gap_count} > {criteria.max_gap_count}")
    if criteria.max_zero_volume_count is not None and summary.zero_volume_count > criteria.max_zero_volume_count:
        failures.append(f"zero_volume_count {summary.zero_volume_count} > {criteria.max_zero_volume_count}")
    if criteria.min_symbol_count is not None and summary.symbol_count < criteria.min_symbol_count:
        failures.append(f"symbol_count {summary.symbol_count} < {criteria.min_symbol_count}")
    if criteria.min_period_count is not None and summary.period_count < criteria.min_period_count:
        failures.append(f"period_count {summary.period_count} < {criteria.min_period_count}")
    return CsvAcceptanceResult(
        status="rejected" if failures else "accepted",
        failures=failures,
        criteria=criteria,
    )
