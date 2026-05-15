from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from zurini.api_budget import KST, normalize_to_kst
from zurini.blacklist import normalize_symbol
from zurini.news_blacklist_collector import NewsRiskEvent


DEFAULT_NEGATIVE_KEYWORDS = (
    "유상증자",
    "감자",
    "횡령",
    "배임",
    "상장폐지",
    "거래정지",
    "의견거절",
    "관리종목",
    "불성실공시",
    "회생절차",
)


@dataclass(frozen=True)
class NewsAdapterReport:
    source_count: int
    item_count: int
    event_count: int
    heartbeat_at: datetime
    sources: tuple[str, ...]
    flags: tuple[str, ...]
    events: tuple[NewsRiskEvent, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["heartbeat_at"] = self.heartbeat_at.isoformat()
        payload["events"] = [
            {
                "symbol": event.symbol,
                "reason": event.reason,
                "severity": event.severity,
                "source": event.source,
                "observed_at": event.observed_at.isoformat(),
                "expires_at": event.expires_at.isoformat() if event.expires_at else None,
            }
            for event in self.events
        ]
        return payload


def collect_news_risk_events(
    *,
    news_json_paths: tuple[Path, ...] = (),
    dart_json_paths: tuple[Path, ...] = (),
    rss_paths: tuple[Path, ...] = (),
    news_json_urls: tuple[str, ...] = (),
    dart_json_urls: tuple[str, ...] = (),
    rss_urls: tuple[str, ...] = (),
    now: datetime,
    keywords: tuple[str, ...] = DEFAULT_NEGATIVE_KEYWORDS,
    allow_network_fetches: bool = False,
    timeout_seconds: float = 10.0,
    source_max_age_minutes: int = 60,
) -> NewsAdapterReport:
    if source_max_age_minutes <= 0:
        raise ValueError("source_max_age_minutes must be positive")
    now_kst = normalize_to_kst(now)
    events: list[NewsRiskEvent] = []
    item_count = 0
    sources: list[str] = []
    network_sources = (*news_json_urls, *dart_json_urls, *rss_urls)
    if network_sources and not allow_network_fetches:
        raise ValueError("URL sources require allow_network_fetches=True")

    for path in news_json_paths:
        sources.append(str(path))
        loaded = _load_json_rows(path)
        item_count += len(loaded)
        events.extend(_events_from_generic_rows(loaded, source=f"news-json:{path.name}", now=now_kst, keywords=keywords, source_max_age=timedelta(minutes=source_max_age_minutes)))
    for path in dart_json_paths:
        sources.append(str(path))
        loaded = _load_dart_rows(path)
        item_count += len(loaded)
        events.extend(_events_from_dart_rows(loaded, source=f"dart-json:{path.name}", now=now_kst, keywords=keywords, source_max_age=timedelta(minutes=source_max_age_minutes)))
    for path in rss_paths:
        sources.append(str(path))
        loaded = _load_rss_rows(path)
        item_count += len(loaded)
        events.extend(_events_from_generic_rows(loaded, source=f"rss:{path.name}", now=now_kst, keywords=keywords, source_max_age=timedelta(minutes=source_max_age_minutes)))
    for url in news_json_urls:
        sources.append(url)
        loaded = _load_json_rows_from_text(_fetch_text(url, timeout_seconds=timeout_seconds))
        item_count += len(loaded)
        events.extend(_events_from_generic_rows(loaded, source=f"news-json-url:{_source_name(url)}", now=now_kst, keywords=keywords, source_max_age=timedelta(minutes=source_max_age_minutes)))
    for url in dart_json_urls:
        sources.append(url)
        loaded = _load_dart_rows_from_text(_fetch_text(url, timeout_seconds=timeout_seconds))
        item_count += len(loaded)
        events.extend(_events_from_dart_rows(loaded, source=f"dart-json-url:{_source_name(url)}", now=now_kst, keywords=keywords, source_max_age=timedelta(minutes=source_max_age_minutes)))
    for url in rss_urls:
        sources.append(url)
        loaded = _load_rss_rows_from_text(_fetch_text(url, timeout_seconds=timeout_seconds))
        item_count += len(loaded)
        events.extend(_events_from_generic_rows(loaded, source=f"rss-url:{_source_name(url)}", now=now_kst, keywords=keywords, source_max_age=timedelta(minutes=source_max_age_minutes)))

    unique_events = tuple(_dedupe_events(events))
    flags = ()
    if not sources:
        flags = ("news_adapter_no_sources",)
    elif not unique_events:
        flags = ("news_adapter_no_risk_events",)
    return NewsAdapterReport(
        source_count=len(sources),
        item_count=item_count,
        event_count=len(unique_events),
        heartbeat_at=now_kst,
        sources=tuple(sources),
        flags=flags,
        events=unique_events,
    )


def write_news_adapter_report(report: NewsAdapterReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_news_adapter_events(report: NewsAdapterReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"events": report.as_dict()["events"]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    return _load_json_rows_from_text(path.read_text(encoding="utf-8"))


def _load_json_rows_from_text(text: str) -> list[dict[str, Any]]:
    payload = json.loads(text)
    rows = payload.get("events", payload.get("items", payload)) if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = [rows]
    return [row for row in rows if isinstance(row, dict)]


def _load_dart_rows(path: Path) -> list[dict[str, Any]]:
    return _load_dart_rows_from_text(path.read_text(encoding="utf-8"))


def _load_dart_rows_from_text(text: str) -> list[dict[str, Any]]:
    payload = json.loads(text)
    rows = payload.get("list", payload.get("items", payload)) if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = [rows]
    return [row for row in rows if isinstance(row, dict)]


def _load_rss_rows(path: Path) -> list[dict[str, Any]]:
    return _load_rss_rows_from_text(path.read_text(encoding="utf-8"))


def _load_rss_rows_from_text(text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(text)
    rows: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        rows.append(
            {
                "title": _xml_text(item, "title"),
                "description": _xml_text(item, "description"),
                "pubDate": _xml_text(item, "pubDate"),
            }
        )
    return rows


def _fetch_text(url: str, *, timeout_seconds: float) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("news adapter external URL source must use https://")
    if parsed.scheme not in {"https", "http"}:
        raise ValueError("news adapter URL source must start with https:// or local http://")
    request = Request(url, headers={"User-Agent": "PROJECT-ZURINI-news-adapter/1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"news adapter HTTP error for {_source_name(url)}: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"news adapter network error for {_source_name(url)}: {exc.reason}") from exc


def _source_name(source: str) -> str:
    return source.rsplit("/", 1)[-1].split("?", 1)[0] or "source"


def _events_from_generic_rows(
    rows: list[dict[str, Any]],
    *,
    source: str,
    now: datetime,
    keywords: tuple[str, ...],
    source_max_age: timedelta,
) -> list[NewsRiskEvent]:
    events: list[NewsRiskEvent] = []
    for row in rows:
        symbol = _row_symbol(row)
        if not symbol:
            continue
        text = _row_text(row)
        matched = _matched_keyword(text, keywords)
        if matched is None:
            continue
        observed_at = _row_observed_at(row, now, source_max_age=source_max_age)
        events.append(
            NewsRiskEvent(
                symbol=normalize_symbol(symbol),
                reason=f"news-risk:{matched}",
                severity="block",
                source=str(row.get("source") or source),
                observed_at=observed_at,
            )
        )
    return events


def _events_from_dart_rows(
    rows: list[dict[str, Any]],
    *,
    source: str,
    now: datetime,
    keywords: tuple[str, ...],
    source_max_age: timedelta,
) -> list[NewsRiskEvent]:
    events: list[NewsRiskEvent] = []
    for row in rows:
        symbol = _row_symbol(row)
        if not symbol:
            continue
        title = str(row.get("report_nm") or row.get("title") or "")
        matched = _matched_keyword(title, keywords)
        if matched is None:
            continue
        observed_at = _row_observed_at(row, now, source_max_age=source_max_age)
        events.append(
            NewsRiskEvent(
                symbol=normalize_symbol(symbol),
                reason=f"dart-risk:{matched}",
                severity="block",
                source=str(row.get("source") or source),
                observed_at=observed_at,
            )
        )
    return events


def _row_symbol(row: dict[str, Any]) -> str:
    explicit = str(row.get("symbol") or row.get("stock_code") or row.get("isu_cd") or "").strip()
    if explicit:
        return explicit
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", _row_text(row))
    return match.group(1) if match else ""


def _row_text(row: dict[str, Any]) -> str:
    return " ".join(str(row.get(key) or "") for key in ("title", "headline", "description", "summary", "body", "report_nm"))


def _matched_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    for keyword in keywords:
        if keyword and keyword in text:
            return keyword
    return None


def _row_observed_at(row: dict[str, Any], now: datetime, *, source_max_age: timedelta) -> datetime:
    for key in ("observed_at", "datetime", "published_at", "rcept_dt", "pubDate"):
        value = row.get(key)
        if not value:
            continue
        parsed = _try_parse_datetime(str(value))
        if parsed is not None:
            age = normalize_to_kst(now) - parsed
            if age < -timedelta(minutes=1):
                raise ValueError("news source item timestamp is after collection time")
            if age > source_max_age:
                raise ValueError("news source item timestamp is stale")
            return parsed
    raise ValueError("news source item timestamp is required")


def _try_parse_datetime(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            return normalize_to_kst(parsed)
        except ValueError:
            pass
    try:
        return normalize_to_kst(datetime.fromisoformat(normalized.replace("Z", "+00:00")))
    except ValueError:
        return None


def _dedupe_events(events: list[NewsRiskEvent]) -> list[NewsRiskEvent]:
    by_key: dict[tuple[str, str, str], NewsRiskEvent] = {}
    for event in events:
        key = (normalize_symbol(event.symbol), event.reason, event.source)
        by_key.setdefault(key, event)
    return [by_key[key] for key in sorted(by_key)]


def _xml_text(item: ET.Element, name: str) -> str:
    child = item.find(name)
    text = child.text if child is not None else ""
    return re.sub(r"\s+", " ", text or "").strip()
