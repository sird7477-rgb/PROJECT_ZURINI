from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from zurini.blacklist import AsyncBlacklistEntry, AsyncBlacklistSnapshot, load_async_blacklist
from zurini.cli import main
from zurini.news_adapter import collect_news_risk_events
from zurini.news_blacklist_collector import load_news_risk_events, update_blacklist_from_news_events


def test_news_risk_events_update_blacklist_without_api_calls(tmp_path):
    event_path = tmp_path / "news-event.json"
    event_path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "symbol": "A005930",
                        "reason": "negative-news",
                        "severity": "block",
                        "source": "webhook",
                        "observed_at": "2026-05-11T09:01:00+09:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    events = load_news_risk_events(event_path)

    snapshot = update_blacklist_from_news_events(
        existing=None,
        events=events,
        now=datetime(2026, 5, 11, 9, 2, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    evaluation = snapshot.evaluation(now=datetime(2026, 5, 11, 9, 2, tzinfo=ZoneInfo("Asia/Seoul")))
    assert snapshot.heartbeat_at == datetime(2026, 5, 11, 9, 2, tzinfo=ZoneInfo("Asia/Seoul"))
    assert evaluation.flags == ("blacklist_active",)
    assert evaluation.blocks_symbol("005930") is True


def test_news_blacklist_cli_merges_existing_and_expires_old_entries(tmp_path):
    old_entry = AsyncBlacklistEntry(
        symbol="000660",
        reason="old-risk",
        severity="block",
        source="manual",
        observed_at=datetime(2026, 5, 11, 8, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        expires_at=datetime(2026, 5, 11, 8, 30, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    existing = AsyncBlacklistSnapshot(
        heartbeat_at=datetime(2026, 5, 11, 8, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        entries=(old_entry,),
    )
    existing_path = tmp_path / "existing.json"
    from zurini.blacklist import write_async_blacklist

    write_async_blacklist(existing, existing_path)
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            [
                {
                    "symbol": "A005930",
                    "reason": "dart-risk",
                    "source": "dart-webhook",
                    "observed_at": "2026-05-11T09:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "blacklist.json"

    exit_code = main(
        [
            "update-news-blacklist",
            "--existing",
            str(existing_path),
            "--event-json",
            str(event_path),
            "--now",
            "2026-05-11T09:01:00+09:00",
            "--ttl-minutes",
            "30",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    snapshot = load_async_blacklist(output)
    assert [entry.symbol for entry in snapshot.entries] == ["005930"]
    assert snapshot.entries[0].expires_at == datetime(2026, 5, 11, 9, 30, tzinfo=ZoneInfo("Asia/Seoul"))


def test_news_collector_does_not_let_expired_replay_clear_active_entry():
    existing = AsyncBlacklistSnapshot(
        heartbeat_at=datetime(2026, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        entries=(
            AsyncBlacklistEntry(
                symbol="005930",
                reason="active-risk",
                severity="block",
                source="manual",
                observed_at=datetime(2026, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                expires_at=datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            ),
        ),
    )
    stale_replay = load_news_risk_events_from_rows(
        [
            {
                "symbol": "A005930",
                "reason": "stale-replay",
                "source": "webhook",
                "observed_at": "2026-05-11T08:00:00+09:00",
                "expires_at": "2026-05-11T08:30:00+09:00",
            }
        ]
    )

    snapshot = update_blacklist_from_news_events(
        existing=existing,
        events=stale_replay,
        now=datetime(2026, 5, 11, 9, 5, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].reason == "active-risk"
    assert snapshot.evaluation(now=datetime(2026, 5, 11, 9, 5, tzinfo=ZoneInfo("Asia/Seoul"))).blocks_symbol("A005930")


def test_news_blacklist_cli_rejects_empty_heartbeat_without_explicit_flag(tmp_path):
    with pytest.raises(ValueError, match="requires --event-json"):
        main(
            [
                "update-news-blacklist",
                "--now",
                "2026-05-11T09:01:00+09:00",
                "--output",
                str(tmp_path / "blacklist.json"),
            ]
        )


def test_news_blacklist_cli_allows_explicit_empty_heartbeat(tmp_path):
    output = tmp_path / "blacklist.json"

    exit_code = main(
        [
            "update-news-blacklist",
            "--allow-empty-heartbeat",
            "--now",
            "2026-05-11T09:01:00+09:00",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    snapshot = load_async_blacklist(output)
    assert snapshot.heartbeat_at == datetime(2026, 5, 11, 9, 1, tzinfo=ZoneInfo("Asia/Seoul"))
    assert snapshot.entries == ()


def test_news_adapter_collects_dart_and_news_risk_events(tmp_path):
    news_path = tmp_path / "news.json"
    news_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "symbol": "A005930",
                        "title": "삼성전자 횡령 의혹 보도",
                        "published_at": "2026-05-11T09:00:00+09:00",
                    },
                    {"symbol": "000660", "title": "일반 기사"},
                ]
            }
        ),
        encoding="utf-8",
    )
    dart_path = tmp_path / "dart.json"
    dart_path.write_text(
        json.dumps(
            {
                "list": [
                    {
                        "stock_code": "000660",
                        "report_nm": "주요사항보고서(유상증자결정)",
                        "rcept_dt": "20260511",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = collect_news_risk_events(
        news_json_paths=(news_path,),
        dart_json_paths=(dart_path,),
        now=datetime(2026, 5, 11, 9, 5, tzinfo=ZoneInfo("Asia/Seoul")),
        source_max_age_minutes=1440,
    )

    assert report.source_count == 2
    assert report.item_count == 3
    assert report.event_count == 2
    assert [event.symbol for event in report.events] == ["000660", "005930"]
    assert report.flags == ()


def test_collect_news_risk_events_cli_writes_event_and_report_files(tmp_path):
    news_path = tmp_path / "news.json"
    news_path.write_text(
        json.dumps(
            [
                {
                    "symbol": "005930",
                    "headline": "거래정지 가능성 보도",
                    "published_at": "2026-05-11T09:00:00+09:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    events_output = tmp_path / "events.json"
    report_output = tmp_path / "report.json"

    exit_code = main(
        [
            "collect-news-risk-events",
            "--news-json",
            str(news_path),
            "--now",
            "2026-05-11T09:05:00+09:00",
            "--events-output",
            str(events_output),
            "--report-output",
            str(report_output),
        ]
    )

    assert exit_code == 0
    events_payload = json.loads(events_output.read_text(encoding="utf-8"))
    report_payload = json.loads(report_output.read_text(encoding="utf-8"))
    assert events_payload["events"][0]["symbol"] == "005930"
    assert report_payload["event_count"] == 1


def test_collect_news_risk_events_rejects_missing_source_timestamp(tmp_path):
    news_path = tmp_path / "news.json"
    news_path.write_text(
        json.dumps([{"symbol": "005930", "headline": "거래정지 가능성 보도"}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="timestamp is required"):
        collect_news_risk_events(
            news_json_paths=(news_path,),
            now=datetime(2026, 5, 11, 9, 5, tzinfo=ZoneInfo("Asia/Seoul")),
        )


def test_collect_news_risk_events_fetches_rss_url(monkeypatch):
    rss_payload = """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel><item>
<title>005930 거래정지 가능성 보도</title>
<description>삼성전자 관련 리스크</description>
<pubDate>2026-05-11T09:05:00+09:00</pubDate>
</item></channel></rss>"""

    def fake_urlopen(request, timeout):
        class Response:
            headers = type("Headers", (), {"get_content_charset": lambda self: "utf-8"})()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return rss_payload.encode("utf-8")

        assert request.full_url == "https://example.test/rss.xml"
        assert timeout == 3.0
        return Response()

    monkeypatch.setattr("zurini.news_adapter.urlopen", fake_urlopen)

    report = collect_news_risk_events(
        rss_urls=("https://example.test/rss.xml",),
        now=datetime(2026, 5, 11, 9, 6, tzinfo=ZoneInfo("Asia/Seoul")),
        allow_network_fetches=True,
        timeout_seconds=3.0,
    )

    assert report.source_count == 1
    assert report.item_count == 1
    assert report.event_count == 1
    assert report.events[0].symbol == "005930"
    assert report.events[0].source == "rss-url:rss.xml"


def test_collect_news_risk_events_requires_library_network_gate_for_urls():
    with pytest.raises(ValueError, match="allow_network_fetches=True"):
        collect_news_risk_events(
            rss_urls=("https://example.test/rss.xml",),
            now=datetime(2026, 5, 11, 9, 6, tzinfo=ZoneInfo("Asia/Seoul")),
        )


def test_collect_news_risk_events_rejects_plaintext_external_urls():
    with pytest.raises(ValueError, match="external URL source must use https"):
        collect_news_risk_events(
            rss_urls=("http://example.test/rss.xml",),
            now=datetime(2026, 5, 11, 9, 6, tzinfo=ZoneInfo("Asia/Seoul")),
            allow_network_fetches=True,
        )


def test_collect_news_risk_events_cli_requires_network_gate_for_urls(tmp_path):
    with pytest.raises(ValueError, match="URL sources require --allow-network --run-network"):
        main(
            [
                "collect-news-risk-events",
                "--rss-url",
                "https://example.test/rss.xml",
                "--events-output",
                str(tmp_path / "events.json"),
                "--report-output",
                str(tmp_path / "report.json"),
            ]
        )


def test_collect_news_risk_events_cli_writes_url_fetch_output(tmp_path, monkeypatch):
    rss_payload = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel><item><title>005930 거래정지 가능성 보도</title><pubDate>2026-05-11T09:05:00+09:00</pubDate></item></channel></rss>"""

    def fake_urlopen(request, timeout):
        class Response:
            headers = type("Headers", (), {"get_content_charset": lambda self: "utf-8"})()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return rss_payload.encode("utf-8")

        return Response()

    monkeypatch.setattr("zurini.news_adapter.urlopen", fake_urlopen)
    events_output = tmp_path / "events.json"
    report_output = tmp_path / "report.json"

    exit_code = main(
        [
            "collect-news-risk-events",
            "--allow-network",
            "--run-network",
            "--rss-url",
            "https://example.test/rss.xml",
            "--now",
            "2026-05-11T09:06:00+09:00",
            "--events-output",
            str(events_output),
            "--report-output",
            str(report_output),
        ]
    )

    assert exit_code == 0
    events_payload = json.loads(events_output.read_text(encoding="utf-8"))
    report_payload = json.loads(report_output.read_text(encoding="utf-8"))
    assert events_payload["events"][0]["symbol"] == "005930"
    assert report_payload["sources"] == ["https://example.test/rss.xml"]
    assert report_payload["event_count"] == 1


def load_news_risk_events_from_rows(rows):
    path = Path("/tmp/zurini-news-risk-event-test.json")
    path.write_text(json.dumps(rows), encoding="utf-8")
    return load_news_risk_events(path)
