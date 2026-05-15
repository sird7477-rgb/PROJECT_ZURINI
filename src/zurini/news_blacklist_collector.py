from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from zurini.api_budget import KST, normalize_to_kst
from zurini.blacklist import AsyncBlacklistEntry, AsyncBlacklistSnapshot, normalize_symbol


@dataclass(frozen=True)
class NewsRiskEvent:
    symbol: str
    reason: str
    severity: str
    source: str
    observed_at: datetime
    expires_at: datetime | None = None


def load_news_risk_events(path: Path) -> tuple[NewsRiskEvent, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("events", payload) if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = [rows]
    return tuple(_event_from_dict(row) for row in rows)


def update_blacklist_from_news_events(
    *,
    existing: AsyncBlacklistSnapshot | None,
    events: tuple[NewsRiskEvent, ...],
    now: datetime,
    ttl: timedelta = timedelta(minutes=60),
    source: str = "news-webhook-collector",
) -> AsyncBlacklistSnapshot:
    now_kst = normalize_to_kst(now)
    retained = tuple(
        entry
        for entry in (existing.entries if existing is not None else ())
        if entry.expires_at is None or normalize_to_kst(entry.expires_at) >= now_kst
    )
    new_entries = tuple(
        entry
        for entry in (_entry_from_event(event, ttl=ttl) for event in events)
        if entry.expires_at is None or normalize_to_kst(entry.expires_at) >= now_kst
    )
    by_symbol: dict[str, AsyncBlacklistEntry] = {}
    for entry in (*retained, *new_entries):
        symbol = normalize_symbol(entry.symbol)
        by_symbol[symbol] = _more_conservative_entry(by_symbol.get(symbol), entry)
    return AsyncBlacklistSnapshot(
        heartbeat_at=now_kst,
        entries=tuple(sorted(by_symbol.values(), key=lambda item: normalize_symbol(item.symbol))),
        source=source,
    )


def _event_from_dict(payload: dict[str, Any]) -> NewsRiskEvent:
    observed_raw = payload.get("observed_at")
    if not observed_raw:
        raise ValueError("news risk event observed_at is required")
    return NewsRiskEvent(
        symbol=str(payload["symbol"]),
        reason=str(payload.get("reason") or "news-risk"),
        severity=str(payload.get("severity") or "block"),
        source=str(payload.get("source") or "webhook"),
        observed_at=_parse_datetime(str(observed_raw)),
        expires_at=_parse_datetime(str(payload["expires_at"])) if payload.get("expires_at") else None,
    )


def _entry_from_event(event: NewsRiskEvent, *, ttl: timedelta) -> AsyncBlacklistEntry:
    observed_at = normalize_to_kst(event.observed_at)
    expires_at = normalize_to_kst(event.expires_at) if event.expires_at else observed_at + ttl
    return AsyncBlacklistEntry(
        symbol=normalize_symbol(event.symbol),
        reason=event.reason,
        severity=event.severity,
        source=event.source,
        observed_at=observed_at,
        expires_at=expires_at,
    )


def _more_conservative_entry(
    current: AsyncBlacklistEntry | None,
    candidate: AsyncBlacklistEntry,
) -> AsyncBlacklistEntry:
    if current is None:
        return candidate
    if current.expires_at is None:
        return current
    if candidate.expires_at is None:
        return candidate
    return candidate if normalize_to_kst(candidate.expires_at) > normalize_to_kst(current.expires_at) else current


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed
