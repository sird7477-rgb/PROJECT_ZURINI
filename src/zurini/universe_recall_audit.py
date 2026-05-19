from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class SignalObservation:
    symbol: str
    timestamp: datetime
    candidate_id: str
    score: Decimal = Decimal("0")

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        payload["score"] = str(self.score)
        return payload


@dataclass(frozen=True)
class UniverseRecallReport:
    universe_id: str
    universe_size: int
    signal_count: int
    captured_count: int
    missed_count: int
    captured_symbols: tuple[str, ...]
    missed_symbols: tuple[str, ...]

    def recall_ratio(self) -> Decimal:
        if self.signal_count == 0:
            return Decimal("0")
        return Decimal(self.captured_count) / Decimal(self.signal_count)

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["captured_symbols"] = list(self.captured_symbols)
        payload["missed_symbols"] = list(self.missed_symbols)
        payload["recall_ratio"] = str(self.recall_ratio())
        return payload


def audit_universe_recall(
    *,
    universe_id: str,
    universe_symbols: set[str],
    observations: list[SignalObservation],
) -> UniverseRecallReport:
    signal_symbols = {observation.symbol for observation in observations}
    captured = tuple(sorted(signal_symbols & universe_symbols))
    missed = tuple(sorted(signal_symbols - universe_symbols))
    return UniverseRecallReport(
        universe_id=universe_id,
        universe_size=len(universe_symbols),
        signal_count=len(signal_symbols),
        captured_count=len(captured),
        missed_count=len(missed),
        captured_symbols=captured,
        missed_symbols=missed,
    )


def compare_universe_recalls(reports: list[UniverseRecallReport]) -> list[UniverseRecallReport]:
    return sorted(
        reports,
        key=lambda report: (
            -report.recall_ratio(),
            report.universe_size,
            report.universe_id,
        ),
    )
