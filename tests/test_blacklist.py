from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from zurini.blacklist import (
    AsyncBlacklistEntry,
    AsyncBlacklistSnapshot,
    load_async_blacklist,
    write_async_blacklist,
)


def test_async_blacklist_normalizes_symbols_and_expires_entries(tmp_path):
    now = datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)
    snapshot = AsyncBlacklistSnapshot(
        heartbeat_at=now,
        entries=(
            AsyncBlacklistEntry(
                symbol="A005930",
                reason="negative-news",
                severity="block",
                source="manual",
                observed_at=now,
            ),
            AsyncBlacklistEntry(
                symbol="000660",
                reason="expired-news",
                severity="block",
                source="manual",
                observed_at=now - timedelta(hours=2),
                expires_at=now - timedelta(minutes=1),
            ),
        ),
    )

    output = tmp_path / "blacklist.json"
    write_async_blacklist(snapshot, output)
    loaded = load_async_blacklist(output)
    evaluation = loaded.evaluation(now=now)

    assert evaluation.stale is False
    assert evaluation.active_symbols == ("005930",)
    assert evaluation.blocks_symbol("A005930") is True
    assert evaluation.blocks_symbol("000660") is False


def test_async_blacklist_stale_heartbeat_fails_closed():
    now = datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)
    snapshot = AsyncBlacklistSnapshot(
        heartbeat_at=now - timedelta(minutes=6),
        entries=(),
    )

    evaluation = snapshot.evaluation(now=now)

    assert evaluation.stale is True
    assert evaluation.flags == ("blacklist_stale",)
    assert evaluation.blocks_symbol("005930") is True
    assert evaluation.block_reason("005930") == "blacklist-stale-fail-closed"


def test_async_blacklist_treats_naive_json_timestamps_as_kst(tmp_path):
    path = tmp_path / "blacklist.json"
    path.write_text(
        """
{
  "heartbeat_at": "2026-05-11T09:00:00",
  "entries": [
    {
      "symbol": "A005930",
      "reason": "manual-risk",
      "severity": "block",
      "source": "manual",
      "observed_at": "2026-05-11T09:00:00",
      "expires_at": "2026-05-11T09:10:00"
    }
  ]
}
""",
        encoding="utf-8",
    )

    snapshot = load_async_blacklist(path)
    now = datetime(2026, 5, 11, 9, 4, tzinfo=ZoneInfo("Asia/Seoul"))
    evaluation = snapshot.evaluation(now=now)

    assert snapshot.heartbeat_at == datetime(2026, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert evaluation.stale is False
    assert evaluation.active_symbols == ("005930",)
