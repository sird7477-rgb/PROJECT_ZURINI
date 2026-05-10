from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_KEY_PATTERN = re.compile(r"(secret|token|password|passwd|api[_-]?key|app[_-]?secret|cert)", re.IGNORECASE)
SECRET_MESSAGE_PATTERN = re.compile(
    r"(?i)((?:secret|token|password|passwd|api[_-]?key|app[_-]?secret|cert|토큰|비밀번호|시크릿|인증서)\s*[:=]\s*)\S+"
)
REDACTED = "<redacted>"


@dataclass(frozen=True)
class OperationalEvent:
    run_id: str
    event_type: str
    component: str
    status: str
    severity: str = "info"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: int | None = None
    exit_code: int | None = None
    message: str = ""
    calendar_version: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): REDACTED if SECRET_KEY_PATTERN.search(str(key)) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def redact_message(value: str) -> str:
    return SECRET_MESSAGE_PATTERN.sub(r"\1<redacted>", value)


def build_event(
    *,
    run_id: str,
    event_type: str,
    component: str,
    status: str,
    severity: str = "info",
    duration_ms: int | None = None,
    exit_code: int | None = None,
    message: str = "",
    calendar_version: str = "",
    artifact_paths: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> OperationalEvent:
    return OperationalEvent(
        run_id=run_id,
        event_type=event_type,
        component=component,
        status=status,
        severity=severity,
        duration_ms=duration_ms,
        exit_code=exit_code,
        message=redact_message(message),
        calendar_version=calendar_version,
        artifact_paths=artifact_paths or [],
        payload=redact_payload(payload or {}),
    )


def append_event_jsonl(path: Path | str, event: OperationalEvent) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
