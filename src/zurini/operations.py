from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReportCheck:
    path: str
    exists: bool
    status: str
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LocalOpsStatus:
    status: str
    checked_reports: list[ReportCheck]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked_reports": [item.as_dict() for item in self.checked_reports],
        }


def build_local_ops_status(report_paths: list[Path]) -> LocalOpsStatus:
    checks = [_check_report(path) for path in report_paths]
    failed = [check for check in checks if check.status != "ok"]
    return LocalOpsStatus(status="review-required" if failed else "ok", checked_reports=checks)


def write_local_ops_status(status: LocalOpsStatus, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(status.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _check_report(path: Path) -> ReportCheck:
    if not path.exists():
        return ReportCheck(path=str(path), exists=False, status="missing", message="report does not exist")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ReportCheck(path=str(path), exists=True, status="invalid-json", message=str(exc))
    if not isinstance(payload, dict):
        return ReportCheck(path=str(path), exists=True, status="invalid-shape", message="report root must be an object")
    return ReportCheck(path=str(path), exists=True, status="ok")
