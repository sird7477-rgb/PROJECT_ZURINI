from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from zurini.api_budget import KST


@dataclass(frozen=True)
class AsyncBlacklistEntry:
    symbol: str
    reason: str
    severity: str
    source: str
    observed_at: datetime
    expires_at: datetime | None = None

    @property
    def normalized_symbol(self) -> str:
        return normalize_symbol(self.symbol)

    def is_active(self, now: datetime) -> bool:
        return self.expires_at is None or self.expires_at >= now


@dataclass(frozen=True)
class AsyncBlacklistSnapshot:
    heartbeat_at: datetime | None
    entries: tuple[AsyncBlacklistEntry, ...]
    source: str = "async-blacklist"

    def evaluation(self, *, now: datetime, max_age: timedelta = timedelta(minutes=5)) -> BlacklistEvaluation:
        stale = self.heartbeat_at is None or now - self.heartbeat_at > max_age
        active_symbols = tuple(
            sorted({entry.normalized_symbol for entry in self.entries if entry.is_active(now)})
        )
        flags: list[str] = []
        if stale:
            flags.append("blacklist_stale")
        if active_symbols:
            flags.append("blacklist_active")
        return BlacklistEvaluation(
            stale=stale,
            active_symbols=active_symbols,
            flags=tuple(flags),
            reason="blacklist heartbeat stale" if stale else "blacklist heartbeat fresh",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "heartbeat_at": self.heartbeat_at.isoformat() if self.heartbeat_at else None,
            "source": self.source,
            "entries": [_entry_as_dict(entry) for entry in self.entries],
        }


@dataclass(frozen=True)
class BlacklistEvaluation:
    stale: bool
    active_symbols: tuple[str, ...]
    flags: tuple[str, ...]
    reason: str

    def blocks_symbol(self, symbol: str) -> bool:
        return self.stale or normalize_symbol(symbol) in set(self.active_symbols)

    def block_reason(self, symbol: str) -> str:
        if self.stale:
            return "blacklist-stale-fail-closed"
        if normalize_symbol(symbol) in set(self.active_symbols):
            return "blacklist-symbol-blocked"
        return "blacklist-clear"


def normalize_symbol(symbol: str) -> str:
    text = symbol.strip().upper()
    if re.fullmatch(r"A\d{6}", text):
        return text[1:]
    return text


def load_async_blacklist(path: Path) -> AsyncBlacklistSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    heartbeat_raw = payload.get("heartbeat_at")
    heartbeat_at = _parse_datetime(heartbeat_raw) if heartbeat_raw else None
    entries = tuple(_entry_from_dict(item) for item in payload.get("entries", []))
    return AsyncBlacklistSnapshot(
        heartbeat_at=heartbeat_at,
        entries=entries,
        source=str(payload.get("source") or "async-blacklist"),
    )


def write_async_blacklist(snapshot: AsyncBlacklistSnapshot, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _entry_from_dict(payload: dict[str, Any]) -> AsyncBlacklistEntry:
    return AsyncBlacklistEntry(
        symbol=str(payload["symbol"]),
        reason=str(payload.get("reason") or "unspecified"),
        severity=str(payload.get("severity") or "block"),
        source=str(payload.get("source") or "unknown"),
        observed_at=_parse_datetime(payload["observed_at"]),
        expires_at=_parse_datetime(payload["expires_at"]) if payload.get("expires_at") else None,
    )


def _entry_as_dict(entry: AsyncBlacklistEntry) -> dict[str, Any]:
    payload = asdict(entry)
    payload["observed_at"] = entry.observed_at.isoformat()
    payload["expires_at"] = entry.expires_at.isoformat() if entry.expires_at else None
    return payload


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed
