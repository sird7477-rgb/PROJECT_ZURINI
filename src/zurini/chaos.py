from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChaosScenario:
    name: str
    target: str
    safety_boundary: str
    expected_detection: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChaosPlan:
    status: str
    execution_mode: str
    scenarios: list[ChaosScenario]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "execution_mode": self.execution_mode,
            "scenarios": [scenario.as_dict() for scenario in self.scenarios],
        }


def build_safe_chaos_plan() -> ChaosPlan:
    scenarios = [
        ChaosScenario(
            name="missing-minute-bar",
            target="fixture CSV coverage",
            safety_boundary="local files only; no broker, account, network, or order side effects",
            expected_detection="phase2-coverage reports missing_minutes_count and review-required for index-grid",
        ),
        ChaosScenario(
            name="missing-trading-day",
            target="calendar day-set gate",
            safety_boundary="local files only; no broker, no raw data deletion",
            expected_detection="phase2-coverage --require-day-set reports missing_trading_days",
        ),
        ChaosScenario(
            name="invalid-backtest-report",
            target="phase2 batch summarizer",
            safety_boundary="synthetic report fixture only",
            expected_detection="phase2-summarize-runs rejects missing required report fields",
        ),
    ]
    return ChaosPlan(status="planned", execution_mode="manual-local-fixture", scenarios=scenarios)


def write_safe_chaos_plan(plan: ChaosPlan, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
