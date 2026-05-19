import json
import io
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.client import IncompleteRead
from urllib.error import URLError
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import pytest

import zurini.api_smoke as api_smoke
import zurini.cli as cli
from zurini.api_smoke import (
    KisTokenCache,
    JsonHttpClient,
    JsonHttpResponse,
    build_api_smoke_plan,
    build_kis_daily_bars,
    build_kis_daily_bars_plan,
    build_kis_holiday_calendar,
    build_kis_read_only_depth,
    build_kis_read_only_depth_plan,
    build_kis_read_only_universe,
    build_kis_read_only_universe_plan,
    run_api_smoke_network,
)
from zurini.stock_master import build_kis_stock_master, build_kis_stock_master_plan
from zurini.cli import _kis_quote_interval, main


class FakeHttpClient:
    def __init__(self):
        self.post_calls = []
        self.get_calls = []

    def post_json(self, url, *, headers=None, payload=None, timeout_seconds=10.0):
        self.post_calls.append({"url": url, "headers": headers or {}, "payload": payload or {}})
        if "tokenP" in url:
            return JsonHttpResponse(200, {"access_token": "fake-token", "expires_in": 3600})
        if "generateContent" in url:
            return JsonHttpResponse(200, {"candidates": [{"content": {"parts": [{"text": "ZURINI_API_OK"}]}}]})
        return JsonHttpResponse(404, {"error": {"message": "unexpected post"}})

    def get_json(self, url, *, headers=None, timeout_seconds=10.0):
        self.get_calls.append({"url": url, "headers": headers or {}})
        if "api.telegram.org" in url:
            return JsonHttpResponse(200, {"ok": True, "result": {"username": "zurini_test_bot"}})
        if "inquire-price" in url:
            return JsonHttpResponse(200, {"rt_cd": "0", "msg1": "정상처리 되었습니다.", "output": {"stck_prpr": "70000"}})
        return JsonHttpResponse(404, {"error": {"message": "unexpected get"}})


class FakeKisUniverseClient:
    def __init__(self, quote_payloads):
        self.quote_payloads = list(quote_payloads)
        self.post_calls = []
        self.get_calls = []

    def post_json(self, url, *, headers=None, payload=None, timeout_seconds=10.0):
        self.post_calls.append({"url": url, "headers": headers or {}, "payload": payload or {}})
        return JsonHttpResponse(200, {"access_token": "fake-token", "expires_in": 3600})

    def get_json(self, url, *, headers=None, timeout_seconds=10.0):
        self.get_calls.append({"url": url, "headers": headers or {}})
        response = self.quote_payloads.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeKisAuthFailureClient:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.post_calls = []
        self.get_calls = []

    def post_json(self, url, *, headers=None, payload=None, timeout_seconds=10.0):
        self.post_calls.append({"url": url, "headers": headers or {}, "payload": payload or {}})
        if self.exc:
            raise self.exc
        return self.response

    def get_json(self, url, *, headers=None, timeout_seconds=10.0):
        self.get_calls.append({"url": url, "headers": headers or {}})
        return JsonHttpResponse(200, {"rt_cd": "0", "output": {"stck_prpr": "70000"}})


class FakeUrlopenResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"<html>not json</html>"


class FakeIncompleteReadResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        raise IncompleteRead(b"", 1836)


def _stock_master_zip(file_name, row):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(file_name, row.encode("cp949"))
    return buffer.getvalue()


def _stock_master_row(symbol, standard_code, name, *, market):
    if market == "KOSPI":
        widths = [
            2, 1, 4, 4, 4,
            1, 1, 1, 1, 1,
            1, 1, 1, 1, 1,
            1, 1, 1, 1, 1,
            1, 1, 1, 1, 1,
            1, 1, 1, 1, 1,
            1, 9, 5, 5, 1,
            1, 1, 2, 1, 1,
            1, 2, 2, 2, 3,
            1, 3, 12, 12, 8,
            15, 21, 2, 7, 1,
            1, 1, 1, 1, 9,
            9, 9, 5, 9, 8,
            9, 3, 1, 1, 1,
        ]
    else:
        widths = [
            2, 1, 4, 4, 4,
            1, 1, 1, 1, 1,
            1, 1, 1, 1, 1,
            1, 1, 1, 1, 1,
            1, 1, 1, 1, 1,
            1, 9, 5, 5, 1,
            1, 1, 2, 1, 1,
            1, 2, 2, 2, 3,
            1, 3, 12, 12, 8,
            15, 21, 2, 7, 1,
            1, 1, 1, 9, 9,
            9, 5, 9, 8, 9,
            3, 1, 1, 1,
        ]
    fields = [""] * len(widths)
    fields[0] = "ST"
    suffix = "".join(value.ljust(width)[:width] for value, width in zip(fields, widths))
    prefix = f"{symbol:<9}{standard_code:<12}{name}"
    return prefix + suffix + "\n"


def test_api_smoke_plan_reports_missing_env_without_secret_values():
    payload = build_api_smoke_plan(environ={})

    assert payload["status"] == "missing-env"
    assert payload["mode"] == "network-disabled"
    assert "secret values" in payload["safety_boundary"]
    assert {probe["name"] for probe in payload["probes"]} == {
        "telegram",
        "gemini",
        "kis-paper-auth",
        "kis-paper-market-data",
    }
    assert all(probe["enabled"] is False for probe in payload["probes"])


def test_api_smoke_plan_can_enable_read_only_network_probes_from_environment_names_only():
    payload = build_api_smoke_plan(
        allow_network=True,
        environ={
            "TELEGRAM_BOT_TOKEN": "present",
            "TELEGRAM_CHAT_ID": "present",
            "GEMINI_API_KEY": "present",
            "KIS_PAPER_APP_KEY": "present",
            "KIS_PAPER_APP_SECRET": "present",
        },
    )

    assert payload["status"] == "ready"
    assert payload["mode"] == "network-contract-only"
    assert all(probe["enabled"] is True for probe in payload["probes"])
    assert "present" not in json.dumps(payload)


def test_api_smoke_plan_treats_empty_environment_values_as_missing():
    payload = build_api_smoke_plan(
        allow_network=True,
        environ={
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "present",
            "GEMINI_API_KEY": "",
            "KIS_PAPER_APP_KEY": "present",
            "KIS_PAPER_APP_SECRET": "",
        },
    )

    probes = {probe["name"]: probe for probe in payload["probes"]}
    assert payload["status"] == "missing-env"
    assert probes["telegram"]["missing_env"] == ("TELEGRAM_BOT_TOKEN",)
    assert probes["gemini"]["missing_env"] == ("GEMINI_API_KEY",)
    assert probes["kis-paper-auth"]["missing_env"] == ("KIS_PAPER_APP_SECRET",)


def test_api_smoke_cli_writes_offline_plan(tmp_path):
    output = tmp_path / "api-smoke.json"

    exit_code = main(["api-smoke", "--output", str(output)])

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "network-disabled"
    assert payload["status"] in {"missing-env", "ready"}


def test_api_smoke_cli_allow_network_fails_when_env_is_missing(tmp_path, monkeypatch):
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "GEMINI_API_KEY",
        "KIS_PAPER_APP_KEY",
        "KIS_PAPER_APP_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    output = tmp_path / "api-smoke.json"

    exit_code = main(["api-smoke", "--allow-network", "--output", str(output)])

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "network-contract-only"
    assert payload["status"] == "missing-env"


def test_api_smoke_network_uses_sanitized_read_only_probes():
    client = FakeHttpClient()
    env = {
        "TELEGRAM_BOT_TOKEN": "telegram-secret",
        "TELEGRAM_CHAT_ID": "chat-secret",
        "GEMINI_API_KEY": "gemini-secret",
        "KIS_PAPER_APP_KEY": "kis-key-secret",
        "KIS_PAPER_APP_SECRET": "kis-secret",
    }

    payload = run_api_smoke_network(environ=env, client=client, symbol="005930")

    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "passed"
    assert {probe["name"] for probe in payload["probes"]} == {
        "telegram",
        "gemini",
        "kis-paper-auth",
        "kis-paper-market-data",
    }
    assert all(probe["status"] == "passed" for probe in payload["probes"])
    assert "fake-token" not in serialized
    assert "telegram-secret" not in serialized
    assert "gemini-secret" not in serialized
    assert "kis-key-secret" not in serialized
    assert "kis-secret" not in serialized


def test_api_smoke_network_reuses_kis_token_for_market_data():
    client = FakeHttpClient()
    env = {
        "TELEGRAM_BOT_TOKEN": "telegram-secret",
        "TELEGRAM_CHAT_ID": "chat-secret",
        "GEMINI_API_KEY": "gemini-secret",
        "KIS_PAPER_APP_KEY": "kis-key-secret",
        "KIS_PAPER_APP_SECRET": "kis-secret",
    }

    payload = run_api_smoke_network(environ=env, client=client, symbol="005930")

    token_calls = [call for call in client.post_calls if "tokenP" in call["url"]]
    price_calls = [call for call in client.get_calls if "inquire-price" in call["url"]]
    assert payload["status"] == "passed"
    assert len(token_calls) == 1
    assert len(price_calls) == 1
    assert price_calls[0]["headers"]["Authorization"] == "Bearer fake-token"


def test_kis_token_cache_does_not_reuse_or_persist_runtime_token(tmp_path):
    forbidden_token_file = tmp_path / "unexpected-token-file.json"
    client = FakeHttpClient()
    cache = KisTokenCache(
        app_key="key",
        app_secret="secret",
        client=client,
        base_url="https://openapi.koreainvestment.com:9443",
    )

    token, reused, response = cache.get_token()

    assert token == "fake-token"
    assert reused is False
    assert response is not None
    assert not forbidden_token_file.exists()
    assert len(client.post_calls) == 1


def test_kis_token_cache_throttles_failed_reissue_for_one_minute():
    client = FakeKisAuthFailureClient(JsonHttpResponse(200, {"msg1": "missing token"}))
    cache = KisTokenCache(
        app_key="key",
        app_secret="secret",
        client=client,
        base_url="https://example.invalid",
    )
    first = datetime(2026, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    token, from_cache, response = cache.get_token(now=first)
    retry_token, retry_from_cache, retry_response = cache.get_token(now=first.replace(second=30))

    assert token == ""
    assert from_cache is False
    assert response is not None
    assert retry_token == ""
    assert retry_from_cache is False
    assert retry_response is not None
    assert retry_response.payload == {"auth_cooldown": True}
    assert len(client.post_calls) == 1


def test_kis_token_cache_cools_down_after_expired_success():
    client = FakeKisAuthFailureClient(JsonHttpResponse(200, {"access_token": "short-token", "expires_in": 0}))
    cache = KisTokenCache(
        app_key="key",
        app_secret="secret",
        client=client,
        base_url="https://example.invalid",
    )
    first = datetime(2026, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    token, from_cache, response = cache.get_token(now=first)
    retry_token, retry_from_cache, retry_response = cache.get_token(now=first.replace(second=30))

    assert token == ""
    assert from_cache is False
    assert response is not None
    assert retry_token == ""
    assert retry_from_cache is False
    assert retry_response is not None
    assert retry_response.payload == {"auth_cooldown": True}
    assert len(client.post_calls) == 1


def test_kis_token_cache_handles_malformed_expires_in_without_crash():
    client = FakeKisAuthFailureClient(JsonHttpResponse(200, {"access_token": "bad-expiry-token", "expires_in": ""}))
    cache = KisTokenCache(
        app_key="key",
        app_secret="secret",
        client=client,
        base_url="https://example.invalid",
    )
    first = datetime(2026, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    token, from_cache, response = cache.get_token(now=first)

    assert token == ""
    assert from_cache is False
    assert response is not None
    assert response.payload["token_expired_immediately"] is True


def test_kis_token_cache_cools_down_after_network_auth_failure():
    client = FakeKisAuthFailureClient(exc=URLError("timed out"))
    cache = KisTokenCache(
        app_key="key",
        app_secret="secret",
        client=client,
        base_url="https://example.invalid",
    )
    first = datetime(2026, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    with pytest.raises(URLError):
        cache.get_token(now=first)
    retry_token, retry_from_cache, retry_response = cache.get_token(now=first.replace(second=30))

    assert retry_token == ""
    assert retry_from_cache is False
    assert retry_response is not None
    assert retry_response.payload == {"auth_cooldown": True}
    assert len(client.post_calls) == 1


def test_api_smoke_network_classifies_kis_schema_mismatch():
    client = FakeKisUniverseClient([JsonHttpResponse(200, {"rt_cd": "0", "output": {}})])
    env = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "GEMINI_API_KEY": "",
        "KIS_PAPER_APP_KEY": "kis-key-secret",
        "KIS_PAPER_APP_SECRET": "kis-secret",
    }

    payload = run_api_smoke_network(environ=env, client=client, symbol="005930")

    probes = {probe["name"]: probe for probe in payload["probes"]}
    assert probes["kis-paper-market-data"]["diagnostics"]["flags"] == ["api_schema_mismatch"]
    assert payload["api_flags"] == ["api_schema_mismatch"]


def test_api_smoke_network_classifies_kis_auth_failure_flags():
    client = FakeKisAuthFailureClient(JsonHttpResponse(401, {"error_description": "bad auth"}))
    env = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "GEMINI_API_KEY": "",
        "KIS_PAPER_APP_KEY": "kis-key-secret",
        "KIS_PAPER_APP_SECRET": "kis-secret",
    }

    payload = run_api_smoke_network(environ=env, client=client, symbol="005930")

    probes = {probe["name"]: probe for probe in payload["probes"]}
    assert probes["kis-paper-auth"]["status"] == "failed"
    assert probes["kis-paper-auth"]["diagnostics"]["flags"] == ["api_auth_error"]
    assert payload["api_flags"] == ["api_auth_error"]
    assert client.get_calls == []


def test_api_smoke_network_sanitizes_kis_auth_provider_message():
    client = FakeKisAuthFailureClient(
        JsonHttpResponse(401, {"msg1": "remote echoed app_key=kis-paper-key-secret account=12345678"})
    )
    env = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "GEMINI_API_KEY": "",
        "KIS_PAPER_APP_KEY": "kis-paper-key-secret",
        "KIS_PAPER_APP_SECRET": "kis-paper-secret",
    }

    payload = run_api_smoke_network(environ=env, client=client, symbol="005930")
    serialized = json.dumps(payload, ensure_ascii=False)
    probes = {probe["name"]: probe for probe in payload["probes"]}

    assert probes["kis-paper-auth"]["message"] == "api auth error"
    assert probes["kis-paper-auth"]["diagnostics"]["reason"] == "api auth error"
    assert "kis-paper-key-secret" not in serialized
    assert "kis-paper-secret" not in serialized
    assert "12345678" not in serialized
    assert "remote echoed" not in serialized


def test_api_smoke_network_classifies_kis_auth_timeout_without_crash():
    client = FakeKisAuthFailureClient(exc=URLError("timed out"))
    env = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "GEMINI_API_KEY": "",
        "KIS_PAPER_APP_KEY": "kis-key-secret",
        "KIS_PAPER_APP_SECRET": "kis-secret",
    }

    payload = run_api_smoke_network(environ=env, client=client, symbol="005930")

    probes = {probe["name"]: probe for probe in payload["probes"]}
    assert probes["kis-paper-auth"]["diagnostics"]["flags"] == ["api_timeout"]
    assert payload["api_flags"] == ["api_timeout"]
    assert client.get_calls == []


def test_kis_readonly_universe_plan_normalizes_symbols_without_network():
    payload = build_kis_read_only_universe_plan(symbols=("A005930", "000660", ""))

    assert payload["status"] == "ready"
    assert payload["mode"] == "network-disabled"
    assert payload["symbols"] == ["005930", "000660"]
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_kis_readonly_universe_plan_rejects_malformed_symbols():
    with pytest.raises(ValueError, match="invalid KIS stock symbol"):
        build_kis_read_only_universe_plan(symbols=("ABC",))


def test_kis_readonly_universe_builds_included_and_diagnostic_exclusions():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "70000",
                        "stck_oprc": "69000",
                        "stck_hgpr": "70500",
                        "stck_lwpr": "68500",
                        "acml_vol": "123456",
                        "acml_tr_pbmn": "8641920000",
                        "prdy_ctrt": "1.45",
                        "total_askp_rsqn": "1000",
                        "total_bidp_rsqn": "2500",
                    },
                },
            ),
            JsonHttpResponse(200, {"rt_cd": "0", "output": {}}),
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("A005930", "000660"),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "degraded"
    assert payload["mode"] == "network-read-only-prod"
    assert payload["ready_for_broker_or_order_transmission"] is False
    assert payload["included_symbols"] == ("005930",)
    assert payload["members"][0]["open"] == "69000"
    assert payload["members"][0]["high"] == "70500"
    assert payload["members"][0]["low"] == "68500"
    assert payload["members"][0]["volume"] == "123456"
    assert payload["members"][0]["traded_value"] == "8641920000"
    assert payload["members"][0]["previous_day_change_rate"] == "1.45"
    assert payload["members"][0]["ask_volume"] == "1000"
    assert payload["members"][0]["bid_volume"] == "2500"
    assert payload["members"][0]["bid_ask_ratio"] == "2.500000"
    assert "field_data_flags" not in payload["members"][0]
    assert "observed_at" in payload["members"][0]
    assert payload["excluded_symbols"] == (("000660", "schema mismatch: missing output.stck_prpr"),)
    assert payload["members"][1]["field_data_flags"] == (
        "field_data_incomplete:stck_prpr,stck_oprc,stck_hgpr,stck_lwpr,acml_vol,acml_tr_pbmn",
        "bid_ask_placeholder",
    )
    assert payload["api_flags"] == ("api_schema_mismatch",)
    assert payload["read_call_count"] == 3
    assert payload["budget_evidence"]["source"] == "kis-readonly-universe-prod"
    assert payload["budget_evidence"]["measured_read_calls"] == 3
    assert payload["budget_evidence"]["within_budget"] is True
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "fake-token" not in serialized
    assert "kis-live-key-secret" not in serialized
    assert "kis-live-secret" not in serialized


def test_kis_readonly_universe_budget_evidence_peak_uses_observed_timestamps():
    start = datetime(2026, 5, 11, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    timestamps = tuple(start.replace(microsecond=0) + timedelta(milliseconds=100 * index) for index in range(10))

    assert api_smoke._observed_peak_per_second(timestamps) == 10


def test_kis_readonly_depth_plan_is_network_disabled():
    payload = build_kis_read_only_depth_plan(symbols=("A005930",))

    assert payload["status"] == "ready"
    assert payload["mode"] == "network-disabled"
    assert payload["symbols"] == ["005930"]
    assert payload["ready_for_broker_or_order_transmission"] is False
    assert "separate read-only stream" in payload["parallel_collection_note"]


def test_kis_readonly_depth_collects_bid_ask_ratio_and_pairing_gap():
    price_time = datetime(2026, 5, 13, 9, 30, tzinfo=timezone.utc).isoformat()
    depth_time = datetime(2026, 5, 13, 9, 30, 5, tzinfo=timezone.utc)
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output1": {
                        "total_askp_rsqn": "1000",
                        "total_bidp_rsqn": "2500",
                    },
                },
            )
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    original_datetime = api_smoke.datetime

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return depth_time if tz is not None else depth_time.replace(tzinfo=None)

    api_smoke.datetime = FixedDatetime
    try:
        result = build_kis_read_only_depth(
            symbols=("005930",),
            environ=env,
            client=client,
            endpoint_profile="prod",
            confirm_prod_readonly=True,
            paired_price_report={"members": [{"symbol": "005930", "observed_at": price_time}]},
        )
    finally:
        api_smoke.datetime = original_datetime

    payload = result.as_dict()
    assert payload["status"] == "passed"
    assert payload["mode"] == "network-read-only-depth-prod"
    assert payload["ready_for_broker_or_order_transmission"] is False
    assert payload["included_symbols"] == ("005930",)
    assert payload["members"][0]["ask_volume"] == "1000"
    assert payload["members"][0]["bid_volume"] == "2500"
    assert payload["members"][0]["bid_ask_ratio"] == "2.500000"
    assert payload["read_call_count"] == 2
    assert payload["budget_evidence"]["source"] == "kis-readonly-depth-prod"
    assert payload["paired_snapshot_evidence"]["max_gap_seconds"] == 5.0
    assert payload["paired_snapshot_evidence"]["fresh_pairing"] is True
    assert "inquire-asking-price-exp-ccn" in client.get_calls[0]["url"]
    assert client.get_calls[0]["headers"]["tr_id"] == "FHKST01010200"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "fake-token" not in serialized
    assert "kis-live-key-secret" not in serialized
    assert "kis-live-secret" not in serialized


def test_kis_daily_bars_plan_is_network_disabled():
    payload = build_kis_daily_bars_plan(
        symbols=("A005930",),
        start_date=datetime(2026, 5, 8).date(),
        end_date=datetime(2026, 5, 13).date(),
    )

    assert payload["status"] == "ready"
    assert payload["mode"] == "network-disabled"
    assert payload["symbols"] == ["005930"]
    assert payload["ready_for_broker_or_order_transmission"] is False


def test_kis_holiday_calendar_derives_expected_prior_open_trading_day():
    holiday_response = JsonHttpResponse(
        200,
        {
            "rt_cd": "0",
            "output": [
                {
                    "bass_dt": "20260515",
                    "wday_dvsn_cd": "5",
                    "bzdy_yn": "Y",
                    "tr_day_yn": "Y",
                    "opnd_yn": "Y",
                    "sttl_day_yn": "Y",
                },
                {
                    "bass_dt": "20260514",
                    "wday_dvsn_cd": "4",
                    "bzdy_yn": "Y",
                    "tr_day_yn": "Y",
                    "opnd_yn": "Y",
                    "sttl_day_yn": "Y",
                },
                {
                    "bass_dt": "20260513",
                    "wday_dvsn_cd": "3",
                    "bzdy_yn": "N",
                    "tr_day_yn": "Y",
                    "opnd_yn": "N",
                    "sttl_day_yn": "N",
                },
            ],
        },
    )
    client = FakeKisUniverseClient(
        [holiday_response for _ in range(7)]
    )

    result = build_kis_holiday_calendar(
        target_date=datetime(2026, 5, 15).date(),
        environ={
            "KIS_LIVE_APP_KEY": "kis-live-key-secret",
            "KIS_LIVE_APP_SECRET": "kis-live-secret",
        },
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )

    payload = result.as_dict()
    assert payload["status"] == "passed"
    assert payload["expected_prior_date"] == "2026-05-14"
    assert payload["read_call_count"] == 8
    assert "chk-holiday" in client.get_calls[0]["url"]
    assert "BASS_DT=20260115" in client.get_calls[0]["url"]
    assert client.get_calls[0]["headers"]["tr_id"] == "CTCA0903R"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "fake-token" not in serialized
    assert "kis-live-secret" not in serialized


def test_kis_holiday_calendar_fails_closed_on_trading_open_mismatch():
    holiday_response = JsonHttpResponse(
        200,
        {
            "rt_cd": "0",
            "output": [
                {
                    "bass_dt": "20260514",
                    "wday_dvsn_cd": "4",
                    "bzdy_yn": "Y",
                    "tr_day_yn": "Y",
                    "opnd_yn": "N",
                    "sttl_day_yn": "Y",
                },
            ],
        },
    )
    client = FakeKisUniverseClient(
        [holiday_response for _ in range(7)]
    )

    result = build_kis_holiday_calendar(
        target_date=datetime(2026, 5, 15).date(),
        environ={
            "KIS_LIVE_APP_KEY": "kis-live-key-secret",
            "KIS_LIVE_APP_SECRET": "kis-live-secret",
        },
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )

    assert result.as_dict()["status"] == "failed"
    assert "holiday_calendar_business_open_mismatch" in result.as_dict()["api_flags"]


def test_kis_daily_bars_collects_period_ohlcv_fields():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output2": [
                        {
                            "stck_bsop_date": "20260513",
                            "stck_oprc": "70000",
                            "stck_hgpr": "72000",
                            "stck_lwpr": "69000",
                            "stck_clpr": "71000",
                            "acml_vol": "123456",
                            "acml_tr_pbmn": "8765376000",
                        },
                        {
                            "stck_bsop_date": "20260512",
                            "stck_oprc": "68000",
                            "stck_hgpr": "70500",
                            "stck_lwpr": "67500",
                            "stck_clpr": "70000",
                            "acml_vol": "100000",
                            "acml_tr_pbmn": "7000000000",
                        },
                    ],
                },
            )
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_daily_bars(
        symbols=("A005930",),
        start_date=datetime(2026, 5, 8).date(),
        end_date=datetime(2026, 5, 13).date(),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        min_trading_days=1,
    )
    payload = result.as_dict()

    assert payload["status"] == "passed"
    assert payload["mode"] == "network-read-only-daily-bars-prod"
    assert payload["included_symbols"] == ("005930",)
    assert payload["members"][0]["rows"][0]["trading_date"] == "2026-05-12"
    assert payload["members"][0]["rows"][0]["open"] == "68000"
    assert payload["members"][0]["rows"][1]["traded_value"] == "8765376000"
    assert payload["latest_prior_date"] == "2026-05-13"
    assert payload["source_fresh"] is True
    assert payload["read_call_count"] == 2
    assert "inquire-daily-itemchartprice" in client.get_calls[0]["url"]
    assert "FID_INPUT_DATE_1=20260508" in client.get_calls[0]["url"]
    assert client.get_calls[0]["headers"]["tr_id"] == "FHKST03010100"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "fake-token" not in serialized
    assert "kis-live-key-secret" not in serialized
    assert "kis-live-secret" not in serialized


def test_kis_daily_bars_reuses_prewarmed_token_cache():
    class FakeTokenCache:
        def get_token(self):
            return "prewarmed-token", True, None

    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output2": [
                        {
                            "stck_bsop_date": "20260513",
                            "stck_oprc": "70000",
                            "stck_hgpr": "72000",
                            "stck_lwpr": "69000",
                            "stck_clpr": "71000",
                            "acml_vol": "123456",
                            "acml_tr_pbmn": "8765376000",
                        },
                    ],
                },
            )
        ]
    )

    result = build_kis_daily_bars(
        symbols=("A005930",),
        start_date=datetime(2026, 5, 13).date(),
        end_date=datetime(2026, 5, 13).date(),
        environ={
            "KIS_LIVE_APP_KEY": "kis-live-key-secret",
            "KIS_LIVE_APP_SECRET": "kis-live-secret",
        },
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        min_trading_days=1,
        token_cache=FakeTokenCache(),
    )

    payload = result.as_dict()
    assert payload["status"] == "passed"
    assert client.post_calls == []
    assert client.get_calls[0]["headers"]["Authorization"] == "Bearer prewarmed-token"


def test_kis_daily_bars_fails_on_missing_required_ohlcv_fields():
    client = FakeKisUniverseClient([JsonHttpResponse(200, {"rt_cd": "0", "output2": [{"stck_bsop_date": "20260513"}]})])
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_daily_bars(
        symbols=("005930",),
        start_date=datetime(2026, 5, 8).date(),
        end_date=datetime(2026, 5, 13).date(),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )

    payload = result.as_dict()
    assert payload["status"] == "failed"
    assert payload["members"][0]["field_data_flags"] == (
        "daily_bar_field_incomplete:stck_oprc,stck_hgpr,stck_lwpr,stck_clpr,acml_vol,acml_tr_pbmn",
    )


def test_kis_daily_bars_requires_sixty_trading_days_by_default():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output2": [
                        {
                            "stck_bsop_date": "20260513",
                            "stck_oprc": "70000",
                            "stck_hgpr": "72000",
                            "stck_lwpr": "69000",
                            "stck_clpr": "71000",
                            "acml_vol": "123456",
                            "acml_tr_pbmn": "8765376000",
                        }
                    ],
                },
            )
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_daily_bars(
        symbols=("005930",),
        start_date=datetime(2026, 5, 8).date(),
        end_date=datetime(2026, 5, 13).date(),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )

    payload = result.as_dict()
    assert payload["status"] == "failed"
    assert payload["excluded_symbols"] == (("005930", "insufficient KIS daily rows: 1 < 60"),)


def test_kis_daily_bars_rejects_duplicate_or_stale_daily_dates():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output2": [
                        {
                            "stck_bsop_date": "20260512",
                            "stck_oprc": "70000",
                            "stck_hgpr": "72000",
                            "stck_lwpr": "69000",
                            "stck_clpr": "71000",
                            "acml_vol": "123456",
                            "acml_tr_pbmn": "8765376000",
                        },
                        {
                            "stck_bsop_date": "20260512",
                            "stck_oprc": "70000",
                            "stck_hgpr": "72000",
                            "stck_lwpr": "69000",
                            "stck_clpr": "71000",
                            "acml_vol": "123456",
                            "acml_tr_pbmn": "8765376000",
                        },
                    ],
                },
            )
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_daily_bars(
        symbols=("005930",),
        start_date=datetime(2026, 5, 8).date(),
        end_date=datetime(2026, 5, 13).date(),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        min_trading_days=1,
    )

    payload = result.as_dict()
    assert payload["status"] == "failed"
    assert payload["source_fresh"] is False
    assert "daily_bar_duplicate_date" in payload["api_flags"]
    assert "daily_bar_latest_prior_mismatch" in payload["api_flags"]


def test_kis_daily_bars_cli_writes_offline_plan(tmp_path):
    output = tmp_path / "kis-daily-bars.json"

    exit_code = main(
        [
            "kis-daily-bars",
            "--symbol",
            "A005930",
            "--start-date",
            "2026-02-13",
            "--end-date",
            "2026-05-13",
            "--report-output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["mode"] == "network-disabled"
    assert payload["symbols"] == ["005930"]
    assert payload["start_date"] == "2026-02-13"
    assert payload["end_date"] == "2026-05-13"


def test_kis_daily_bars_cli_network_requires_prod_confirmation(tmp_path):
    with pytest.raises(ValueError, match="confirm-prod-readonly"):
        main(
            [
                "kis-daily-bars",
                "--symbol",
                "005930",
                "--start-date",
                "2026-02-13",
                "--end-date",
                "2026-05-13",
                "--allow-network",
                "--run-network",
                "--endpoint-profile",
                "prod",
                "--report-output",
                str(tmp_path / "kis-daily-bars.json"),
            ]
        )


def test_kis_daily_bars_cli_does_not_write_partial_csvs_on_failure(tmp_path, monkeypatch):
    for name in ("KIS_PAPER_APP_KEY", "KIS_PAPER_APP_SECRET"):
        monkeypatch.delenv(name, raising=False)
    output_root = tmp_path / "daily-bars"
    report = tmp_path / "kis-daily-bars.json"

    exit_code = main(
        [
            "kis-daily-bars",
            "--symbol",
            "005930",
            "--start-date",
            "2026-02-13",
            "--end-date",
            "2026-05-13",
            "--allow-network",
            "--run-network",
            "--endpoint-profile",
            "paper",
            "--output-root",
            str(output_root),
            "--report-output",
            str(report),
        ]
    )

    assert exit_code == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["csv_file_count"] == 0
    assert not output_root.exists()


def test_kis_stock_master_plan_defaults_to_kospi_and_kosdaq():
    plan = build_kis_stock_master_plan()

    assert plan["status"] == "ready"
    assert plan["mode"] == "network-disabled"
    assert list(plan["source_files"]) == ["KOSPI", "KOSDAQ"]
    assert plan["ready_for_broker_or_order_transmission"] is False


def test_kis_stock_master_parses_candidates_from_kis_master_zips():
    payloads = {
        "kospi_code.mst.zip": _stock_master_zip(
            "kospi_code.mst",
            _stock_master_row("005930", "KR7005930003", "Samsung", market="KOSPI"),
        ),
        "kosdaq_code.mst.zip": _stock_master_zip(
            "kosdaq_code.mst",
            _stock_master_row("035720", "KR7035720002", "Kakao", market="KOSDAQ"),
        ),
    }

    result = build_kis_stock_master(
        fetcher=lambda url: payloads[url.rsplit("/", 1)[-1]],
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    payload = result.as_dict()

    assert payload["status"] == "passed"
    assert payload["included_symbols"] == ["005930", "035720"]
    assert payload["market_counts"] == {"KOSPI": 1, "KOSDAQ": 1}
    assert payload["api_flags"] == ()
    assert payload["duplicate_symbol_count"] == 0


def test_kis_stock_master_fails_when_expected_master_file_missing():
    result = build_kis_stock_master(
        markets=("KOSPI",),
        fetcher=lambda url: _stock_master_zip(
            "unexpected.txt",
            _stock_master_row("005930", "KR7005930003", "Samsung", market="KOSPI"),
        ),
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    payload = result.as_dict()

    assert payload["status"] == "failed"
    assert payload["market_counts"] == {"KOSPI": 0}
    assert "kospi_stock_master_malformed" in payload["api_flags"]
    assert "kospi_stock_master_empty" in payload["api_flags"]


def test_kis_stock_master_excludes_duplicate_candidates_with_evidence():
    result = build_kis_stock_master(
        markets=("KOSPI",),
        fetcher=lambda url: _stock_master_zip(
            "kospi_code.mst",
            _stock_master_row("005930", "KR7005930003", "Samsung", market="KOSPI")
            + _stock_master_row("005930", "KR7005930004", "Samsung Dup", market="KOSPI")
            + _stock_master_row("000660", "KR7000660001", "SK Hynix", market="KOSPI"),
        ),
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    payload = result.as_dict()

    assert payload["status"] == "passed"
    assert payload["included_symbols"] == ["000660"]
    assert payload["duplicate_symbol_count"] == 2
    assert ["005930", "duplicate-symbol"] in payload["excluded_symbols"]


def test_kis_stock_master_cli_offline_writes_plan(tmp_path):
    output = tmp_path / "kis-stock-master.json"

    exit_code = main(["kis-stock-master-refresh", "--report-output", str(output)])

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["mode"] == "network-disabled"


def test_kis_stock_master_cli_network_updates_db_and_writes_symbol_list(tmp_path, monkeypatch):
    output = tmp_path / "kis-stock-master.json"
    symbols = tmp_path / "symbols.txt"
    db_calls = []

    class FakeResult:
        def as_dict(self):
            return {
                "status": "passed",
                "mode": "network-read-only-stock-master",
                "symbol_count": 1,
                "included_symbols": ["005930"],
                "excluded_symbols": [],
                "members": [
                    {
                        "symbol": "005930",
                        "name": "Samsung",
                        "market": "KOSPI",
                        "section_kind": "ST",
                        "status_kind": "normal",
                        "control_kind": "",
                        "supervision_kind": "",
                        "included": True,
                        "reason": "candidate",
                    }
                ],
                "api_flags": [],
            }

    class FakeLock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(cli, "build_kis_stock_master", lambda markets: FakeResult())
    monkeypatch.setattr(cli.db, "apply_schema", lambda: db_calls.append(("schema", None)))
    monkeypatch.setattr(cli.db, "workflow_lock", lambda: FakeLock())
    monkeypatch.setattr(
        cli.db,
        "replace_symbol_metadata_source",
        lambda metadata, *, source: db_calls.append(("replace", len(metadata), source)) or len(metadata),
    )

    exit_code = main(
        [
            "kis-stock-master-refresh",
            "--allow-network",
            "--run-network",
            "--report-output",
            str(output),
            "--symbol-list-output",
            str(symbols),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["local_db_update"]["row_count"] == 1
    assert symbols.read_text(encoding="utf-8") == "005930\n"
    assert db_calls == [("schema", None), ("replace", 1, "kis-stock-master")]


def test_kis_stock_master_cli_db_update_uses_included_members_only(tmp_path, monkeypatch):
    output = tmp_path / "kis-stock-master.json"
    symbols = tmp_path / "symbols.txt"
    captured_symbols = []

    class FakeResult:
        def as_dict(self):
            return {
                "status": "passed",
                "mode": "network-read-only-stock-master",
                "symbol_count": 3,
                "included_symbols": ["000660"],
                "excluded_symbols": [["005930", "duplicate-symbol"]],
                "members": [
                    {
                        "symbol": "005930",
                        "name": "Samsung",
                        "market": "KOSPI",
                        "section_kind": "ST",
                        "status_kind": "normal",
                        "control_kind": "",
                        "supervision_kind": "",
                        "included": False,
                        "reason": "duplicate-symbol",
                    },
                    {
                        "symbol": "005930",
                        "name": "Samsung Dup",
                        "market": "KOSPI",
                        "section_kind": "ST",
                        "status_kind": "normal",
                        "control_kind": "",
                        "supervision_kind": "",
                        "included": False,
                        "reason": "duplicate-symbol",
                    },
                    {
                        "symbol": "000660",
                        "name": "SK Hynix",
                        "market": "KOSPI",
                        "section_kind": "ST",
                        "status_kind": "normal",
                        "control_kind": "",
                        "supervision_kind": "",
                        "included": True,
                        "reason": "candidate",
                    },
                ],
                "api_flags": [],
            }

    class FakeLock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(cli, "build_kis_stock_master", lambda markets: FakeResult())
    monkeypatch.setattr(cli.db, "apply_schema", lambda: None)
    monkeypatch.setattr(cli.db, "workflow_lock", lambda: FakeLock())

    def replace(metadata, *, source):
        captured_symbols.extend(item.symbol for item in metadata)
        return len(metadata)

    monkeypatch.setattr(cli.db, "replace_symbol_metadata_source", replace)

    exit_code = main(
        [
            "kis-stock-master-refresh",
            "--allow-network",
            "--run-network",
            "--report-output",
            str(output),
            "--symbol-list-output",
            str(symbols),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["local_db_update"]["row_count"] == 1
    assert captured_symbols == ["000660"]
    assert symbols.read_text(encoding="utf-8") == "000660\n"


def test_kis_stock_master_cli_network_rejects_single_market_refresh(tmp_path):
    with pytest.raises(ValueError, match="requires both KOSPI and KOSDAQ"):
        main(
            [
                "kis-stock-master-refresh",
                "--allow-network",
                "--run-network",
                "--market",
                "KOSPI",
                "--report-output",
                str(tmp_path / "kis-stock-master.json"),
            ]
        )


def test_kis_stock_master_cli_blocks_symbol_list_when_db_update_fails(tmp_path, monkeypatch):
    output = tmp_path / "kis-stock-master.json"
    symbols = tmp_path / "symbols.txt"

    class FakeResult:
        def as_dict(self):
            return {
                "status": "passed",
                "mode": "network-read-only-stock-master",
                "symbol_count": 1,
                "included_symbols": ["005930"],
                "excluded_symbols": [],
                "members": [
                    {
                        "symbol": "005930",
                        "name": "Samsung",
                        "market": "KOSPI",
                        "section_kind": "ST",
                        "status_kind": "normal",
                        "control_kind": "",
                        "supervision_kind": "",
                    }
                ],
                "api_flags": [],
            }

    class FakeLock:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(cli, "build_kis_stock_master", lambda markets: FakeResult())
    monkeypatch.setattr(cli.db, "apply_schema", lambda: None)
    monkeypatch.setattr(cli.db, "workflow_lock", lambda: FakeLock())
    monkeypatch.setattr(
        cli.db,
        "replace_symbol_metadata_source",
        lambda metadata, *, source: (_ for _ in ()).throw(RuntimeError("db down")),
    )

    exit_code = main(
        [
            "kis-stock-master-refresh",
            "--allow-network",
            "--run-network",
            "--report-output",
            str(output),
            "--symbol-list-output",
            str(symbols),
        ]
    )

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["api_flags"] == ["local_db_update_failed"]
    assert payload["local_db_update"]["error_type"] == "RuntimeError"
    assert not symbols.exists()


def test_kis_readonly_universe_degrades_included_price_only_quote():
    client = FakeKisUniverseClient([JsonHttpResponse(200, {"rt_cd": "0", "output": {"stck_prpr": "70000"}})])
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "degraded"
    assert payload["api_flags"] == (
        "field_data_incomplete:stck_oprc,stck_hgpr,stck_lwpr,acml_vol,acml_tr_pbmn",
        "bid_ask_placeholder",
    )
    assert payload["members"][0]["field_data_flags"] == payload["api_flags"]


def test_kis_readonly_universe_paper_profile_uses_paper_endpoint_and_env():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "70000",
                        "stck_oprc": "69000",
                        "stck_hgpr": "70500",
                        "stck_lwpr": "68500",
                        "acml_vol": "123456",
                        "acml_tr_pbmn": "8641920000",
                        "total_askp_rsqn": "1000",
                        "total_bidp_rsqn": "2500",
                    },
                },
            )
        ]
    )
    env = {
        "KIS_PAPER_APP_KEY": "kis-paper-key-secret",
        "KIS_PAPER_APP_SECRET": "kis-paper-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="paper",
    )
    payload = result.as_dict()

    assert payload["status"] == "passed"
    assert payload["mode"] == "network-read-only-paper"
    assert "openapivts.koreainvestment.com" in client.post_calls[0]["url"]
    assert "openapivts.koreainvestment.com" in client.get_calls[0]["url"]
    assert client.get_calls[0]["headers"]["appkey"] == "kis-paper-key-secret"


def test_kis_readonly_universe_prod_profile_uses_live_endpoint_and_env():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "70000",
                        "stck_oprc": "69000",
                        "stck_hgpr": "70500",
                        "stck_lwpr": "68500",
                        "acml_vol": "123456",
                        "acml_tr_pbmn": "8641920000",
                        "total_askp_rsqn": "1000",
                        "total_bidp_rsqn": "2500",
                    },
                },
            )
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "passed"
    assert payload["mode"] == "network-read-only-prod"
    assert "openapi.koreainvestment.com" in client.post_calls[0]["url"]
    assert "openapi.koreainvestment.com" in client.get_calls[0]["url"]
    assert client.get_calls[0]["headers"]["appkey"] == "kis-live-key-secret"


def test_kis_readonly_universe_can_merge_quote_depth_without_second_token_issue():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "70000",
                        "stck_oprc": "69000",
                        "stck_hgpr": "70500",
                        "stck_lwpr": "68500",
                        "acml_vol": "123456",
                        "acml_tr_pbmn": "8641920000",
                    },
                },
            ),
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output1": {
                        "total_askp_rsqn": "1000",
                        "total_bidp_rsqn": "2500",
                    },
                },
            ),
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        include_quote_depth=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "passed"
    assert payload["members"][0]["bid_ask_ratio"] == "2.500000"
    assert payload["members"][0]["price_observed_at"]
    assert payload["members"][0]["depth_observed_at"]
    assert payload["members"][0]["observed_at"] == payload["members"][0]["depth_observed_at"]
    assert Decimal(payload["members"][0]["paired_snapshot_gap_seconds"]) >= Decimal("0")
    assert Decimal(payload["members"][0]["paired_snapshot_gap_seconds"]) <= Decimal("5.0")
    assert payload["read_call_count"] == 3
    assert len(client.post_calls) == 1
    assert "inquire-price" in client.get_calls[0]["url"]
    assert "inquire-asking-price-exp-ccn" in client.get_calls[1]["url"]


def test_kis_readonly_universe_flags_parallel_quote_depth_budget_breach(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 5, 11, 15, 15, tzinfo=ZoneInfo("Asia/Seoul"))
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(api_smoke, "datetime", FixedDatetime)
    responses = []
    for price in ("70000", "70100", "70200"):
        responses.extend(
            [
                JsonHttpResponse(
                    200,
                    {
                        "rt_cd": "0",
                        "output": {
                            "stck_prpr": price,
                            "stck_oprc": price,
                            "stck_hgpr": price,
                            "stck_lwpr": price,
                            "acml_vol": "123456",
                            "acml_tr_pbmn": "8641920000",
                        },
                    },
                ),
                JsonHttpResponse(
                    200,
                    {
                        "rt_cd": "0",
                        "output1": {
                            "total_askp_rsqn": "1000",
                            "total_bidp_rsqn": "2500",
                        },
                    },
                ),
            ]
        )
    client = FakeKisUniverseClient(responses)
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930", "000660", "035420"),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        include_quote_depth=True,
        quote_interval_seconds=0,
    )
    payload = result.as_dict()

    assert payload["status"] == "degraded"
    assert "api_rate_limit_risk" in payload["api_flags"]
    assert payload["budget_evidence"]["within_budget"] is False
    assert payload["budget_evidence"]["measured_peak_per_second"] == 7


def test_kis_readonly_universe_include_quote_depth_always_calls_depth_endpoint():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "70000",
                        "stck_oprc": "69000",
                        "stck_hgpr": "70500",
                        "stck_lwpr": "68500",
                        "acml_vol": "123456",
                        "acml_tr_pbmn": "8641920000",
                        "total_askp_rsqn": "1000",
                        "total_bidp_rsqn": "2000",
                    },
                },
            ),
            JsonHttpResponse(200, {"rt_cd": "0", "output1": {"total_askp_rsqn": "1000", "total_bidp_rsqn": "2500"}}),
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        include_quote_depth=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "passed"
    assert payload["members"][0]["bid_ask_ratio"] == "2.500000"
    assert payload["members"][0]["depth_observed_at"]
    assert payload["members"][0]["paired_snapshot_gap_seconds"]
    assert len(client.get_calls) == 2
    assert "inquire-price" in client.get_calls[0]["url"]
    assert "inquire-asking-price-exp-ccn" in client.get_calls[1]["url"]


def test_kis_readonly_universe_treats_zero_ask_depth_as_placeholder():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "152100",
                        "stck_oprc": "151400",
                        "stck_hgpr": "152100",
                        "stck_lwpr": "150000",
                        "acml_vol": "208293",
                        "acml_tr_pbmn": "31624428300",
                    },
                },
            ),
            JsonHttpResponse(200, {"rt_cd": "0", "output1": {"total_askp_rsqn": "0", "total_bidp_rsqn": "60365"}}),
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("003550",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        include_quote_depth=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "degraded"
    assert payload["members"][0]["ask_volume"] == "0"
    assert payload["members"][0]["bid_volume"] == "60365"
    assert "bid_ask_ratio" not in payload["members"][0]
    assert payload["members"][0]["field_data_flags"] == ("bid_ask_placeholder",)
    assert "bid_ask_placeholder" in payload["api_flags"]


def test_kis_readonly_universe_treats_zero_bid_and_zero_ask_depth_as_placeholder():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "70000",
                        "stck_oprc": "69000",
                        "stck_hgpr": "70500",
                        "stck_lwpr": "68500",
                        "acml_vol": "123456",
                        "acml_tr_pbmn": "8641920000",
                    },
                },
            ),
            JsonHttpResponse(200, {"rt_cd": "0", "output1": {"total_askp_rsqn": "0", "total_bidp_rsqn": "0"}}),
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        include_quote_depth=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "degraded"
    assert payload["members"][0]["field_data_flags"] == ("bid_ask_placeholder",)
    assert "bid_ask_placeholder" in payload["api_flags"]


def test_kis_readonly_universe_include_quote_depth_preserves_per_symbol_pairing_order():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "70000",
                        "stck_oprc": "69000",
                        "stck_hgpr": "70500",
                        "stck_lwpr": "68500",
                        "acml_vol": "123456",
                        "acml_tr_pbmn": "8641920000",
                    },
                },
            ),
            JsonHttpResponse(200, {"rt_cd": "0", "output1": {"total_askp_rsqn": "1000", "total_bidp_rsqn": "2500"}}),
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "80000",
                        "stck_oprc": "79000",
                        "stck_hgpr": "80500",
                        "stck_lwpr": "78500",
                        "acml_vol": "654321",
                        "acml_tr_pbmn": "52345680000",
                    },
                },
            ),
            JsonHttpResponse(200, {"rt_cd": "0", "output1": {"total_askp_rsqn": "2000", "total_bidp_rsqn": "3000"}}),
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930", "000660"),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        include_quote_depth=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "passed"
    assert payload["api_flags"] == ()
    assert payload["read_call_count"] == 5
    assert len(client.get_calls) == 4
    assert "FID_INPUT_ISCD=005930" in client.get_calls[0]["url"]
    assert "inquire-price" in client.get_calls[0]["url"]
    assert "FID_INPUT_ISCD=005930" in client.get_calls[1]["url"]
    assert "inquire-asking-price-exp-ccn" in client.get_calls[1]["url"]
    assert "FID_INPUT_ISCD=000660" in client.get_calls[2]["url"]
    assert "inquire-price" in client.get_calls[2]["url"]
    assert "FID_INPUT_ISCD=000660" in client.get_calls[3]["url"]
    assert "inquire-asking-price-exp-ccn" in client.get_calls[3]["url"]
    for member in payload["members"]:
        assert member["price_observed_at"] <= member["depth_observed_at"]
        assert member["observed_at"] == member["depth_observed_at"]
        assert Decimal(member["paired_snapshot_gap_seconds"]) <= Decimal("5.0")


def test_kis_readonly_universe_include_quote_depth_flags_wide_per_symbol_gap(monkeypatch):
    class FixedDateTime(datetime):
        calls = [
            datetime(2026, 5, 12, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 12, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 12, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 12, 0, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 12, 0, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 12, 0, 0, 10, tzinfo=timezone.utc),
        ]

        @classmethod
        def now(cls, tz=None):
            value = cls.calls.pop(0)
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(api_smoke, "datetime", FixedDateTime)
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "0",
                    "output": {
                        "stck_prpr": "70000",
                        "stck_oprc": "69000",
                        "stck_hgpr": "70500",
                        "stck_lwpr": "68500",
                        "acml_vol": "123456",
                        "acml_tr_pbmn": "8641920000",
                    },
                },
            ),
            JsonHttpResponse(200, {"rt_cd": "0", "output1": {"total_askp_rsqn": "1000", "total_bidp_rsqn": "2500"}}),
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-live-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-live-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        include_quote_depth=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "degraded"
    assert "paired_snapshot_gap_exceeded" in payload["api_flags"]
    assert payload["members"][0]["field_data_flags"] == ("paired_snapshot_gap_exceeded",)
    assert payload["members"][0]["paired_snapshot_gap_seconds"] == "9.000000"


def test_kis_readonly_universe_classifies_rate_limit_message():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                200,
                {
                    "rt_cd": "1",
                    "msg1": "초당 거래건수를 초과하였습니다.",
                    "output": {},
                },
            ),
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "failed"
    assert payload["api_flags"] == ("api_rate_limit_risk",)
    assert payload["budget_evidence"]["throttle_flag"] is True
    assert payload["budget_evidence"]["within_budget"] is False
    assert payload["excluded_symbols"] == (("005930", "api rate limit"),)


def test_kis_readonly_universe_classifies_http_error_rate_limit_message():
    client = FakeKisUniverseClient(
        [
            JsonHttpResponse(
                500,
                {
                    "rt_cd": "1",
                    "msg1": "초당 거래건수를 초과하였습니다.",
                },
            ),
        ]
    )
    env = {
        "KIS_LIVE_APP_KEY": "kis-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )
    payload = result.as_dict()

    assert payload["api_flags"] == ("api_rate_limit_risk",)


def test_kis_readonly_universe_classifies_auth_timeout_without_crash():
    client = FakeKisAuthFailureClient(exc=URLError("timed out"))
    env = {
        "KIS_LIVE_APP_KEY": "kis-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "failed"
    assert payload["api_flags"] == ("api_timeout",)
    assert payload["excluded_symbols"] == (("005930", "KIS auth timeout or network error"),)
    assert client.get_calls == []


def test_kis_readonly_universe_persists_auth_cooldown_without_secret_values(tmp_path):
    cooldown_path = tmp_path / "kis-auth-cooldown.json"
    failing_client = FakeKisAuthFailureClient(JsonHttpResponse(200, {"msg1": "missing token"}))
    env = {
        "KIS_LIVE_APP_KEY": "kis-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-secret",
    }

    first = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=failing_client,
        auth_cooldown_path=cooldown_path,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    ).as_dict()
    second_client = FakeKisUniverseClient([JsonHttpResponse(200, {"rt_cd": "0", "output": {"stck_prpr": "70000"}})])
    second = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=second_client,
        auth_cooldown_path=cooldown_path,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    ).as_dict()

    assert first["api_flags"] == ("api_auth_error",)
    assert second["api_flags"] == ("api_auth_error",)
    assert second["read_call_count"] == 0
    assert second_client.post_calls == []
    serialized = cooldown_path.read_text(encoding="utf-8")
    assert "kis-key-secret" not in serialized
    assert "kis-secret" not in serialized
    assert "missing token" not in serialized
    assert '"reason": "auth schema mismatch"' in serialized


def test_kis_auth_cooldown_sanitizes_remote_reason_text(tmp_path):
    cooldown_path = tmp_path / "kis-auth-cooldown.json"
    api_smoke._write_auth_cooldown(
        cooldown_path,
        profile="prod",
        flag="api_auth_error",
        reason="remote echoed app_key=kis-key-secret account=12345678",
    )

    serialized = cooldown_path.read_text(encoding="utf-8")
    assert "kis-key-secret" not in serialized
    assert "12345678" not in serialized
    assert api_smoke._read_auth_cooldown(cooldown_path, profile="prod")["reason"] == "auth error"


def test_api_smoke_network_persists_kis_paper_auth_cooldown(tmp_path):
    cooldown_path = tmp_path / "kis-auth-cooldown.json"
    env = {
        "KIS_PAPER_APP_KEY": "kis-paper-key-secret",
        "KIS_PAPER_APP_SECRET": "kis-paper-secret",
    }
    failing_client = FakeKisAuthFailureClient(JsonHttpResponse(200, {"msg1": "missing token"}))

    first = run_api_smoke_network(environ=env, client=failing_client, auth_cooldown_path=cooldown_path)
    second_client = FakeKisUniverseClient([JsonHttpResponse(200, {"rt_cd": "0", "output": {"stck_prpr": "70000"}})])
    second = run_api_smoke_network(environ=env, client=second_client, auth_cooldown_path=cooldown_path)

    first_auth = {probe["name"]: probe for probe in first["probes"]}["kis-paper-auth"]
    second_auth = {probe["name"]: probe for probe in second["probes"]}["kis-paper-auth"]
    assert first_auth["diagnostics"]["flags"] == ["api_auth_error"]
    assert second_auth["diagnostics"]["flags"] == ["api_auth_error"]
    assert second_client.post_calls == []
    serialized = cooldown_path.read_text(encoding="utf-8")
    assert "kis-paper-key-secret" not in serialized
    assert "kis-paper-secret" not in serialized
    assert "missing token" not in serialized


def test_kis_auth_cooldown_ignores_malformed_json(tmp_path):
    cooldown_path = tmp_path / "kis-auth-cooldown.json"
    cooldown_path.write_text("{not-json", encoding="utf-8")

    assert api_smoke._read_auth_cooldown(cooldown_path, profile="prod") is None

    api_smoke._write_auth_cooldown(cooldown_path, profile="prod", flag="api_auth_error", reason="missing token")
    assert api_smoke._read_auth_cooldown(cooldown_path, profile="prod")["flag"] == "api_auth_error"


def test_kis_auth_cooldown_ignores_expired_records(tmp_path):
    cooldown_path = tmp_path / "kis-auth-cooldown.json"
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    cooldown_path.write_text(
        json.dumps({"prod": {"flag": "api_auth_error", "reason": "old", "recorded_at": expired_at.isoformat()}}),
        encoding="utf-8",
    )

    assert api_smoke._read_auth_cooldown(cooldown_path, profile="prod") is None


def test_kis_auth_cooldown_clear_preserves_other_profiles(tmp_path):
    cooldown_path = tmp_path / "kis-auth-cooldown.json"
    api_smoke._write_auth_cooldown(cooldown_path, profile="prod", flag="api_auth_error", reason="prod failure")
    api_smoke._write_auth_cooldown(cooldown_path, profile="paper", flag="api_timeout", reason="paper failure")

    api_smoke._clear_auth_cooldown(cooldown_path, profile="prod")

    assert api_smoke._read_auth_cooldown(cooldown_path, profile="prod") is None
    assert api_smoke._read_auth_cooldown(cooldown_path, profile="paper")["flag"] == "api_timeout"


def test_kis_readonly_universe_counts_timed_out_quote_attempts_in_budget():
    client = FakeKisUniverseClient([URLError("timed out")])
    env = {
        "KIS_LIVE_APP_KEY": "kis-key-secret",
        "KIS_LIVE_APP_SECRET": "kis-secret",
    }

    result = build_kis_read_only_universe(
        symbols=("005930",),
        environ=env,
        client=client,
        endpoint_profile="prod",
        confirm_prod_readonly=True,
    )
    payload = result.as_dict()

    assert payload["status"] == "failed"
    assert payload["api_flags"] == ("api_timeout",)
    assert payload["read_call_count"] == 2
    assert payload["budget_evidence"]["measured_read_calls"] == 2


def test_kis_readonly_universe_throttles_every_price_and_depth_call(monkeypatch):
    responses = []
    for price in ("70000", "120000"):
        responses.extend(
            [
                JsonHttpResponse(
                    200,
                    {
                        "rt_cd": "0",
                        "output": {
                            "stck_prpr": price,
                            "stck_oprc": price,
                            "stck_hgpr": price,
                            "stck_lwpr": price,
                            "acml_vol": "123456",
                            "acml_tr_pbmn": "8641920000",
                        },
                    },
                ),
                JsonHttpResponse(
                    200,
                    {
                        "rt_cd": "0",
                        "output1": {
                            "total_askp_rsqn": "1000",
                            "total_bidp_rsqn": "2500",
                        },
                    },
                ),
            ]
        )
    sleeps: list[float] = []
    monkeypatch.setattr(api_smoke.time, "sleep", sleeps.append)

    result = build_kis_read_only_universe(
        symbols=("005930", "000660"),
        environ={"KIS_LIVE_APP_KEY": "kis-key-secret", "KIS_LIVE_APP_SECRET": "kis-secret"},
        client=FakeKisUniverseClient(responses),
        endpoint_profile="prod",
        confirm_prod_readonly=True,
        include_quote_depth=True,
        quote_interval_seconds=0.25,
    )

    assert result.read_call_count == 5
    assert len(sleeps) == 4
    assert all(duration > 0 for duration in sleeps)


def test_kis_readonly_universe_rejects_negative_quote_interval():
    with pytest.raises(ValueError, match="quote_interval_seconds"):
        build_kis_read_only_universe(symbols=("005930",), environ={}, quote_interval_seconds=-1)


def test_kis_readonly_universe_requires_prod_readonly_confirmation_at_library_boundary():
    with pytest.raises(ValueError, match="confirm_prod_readonly=True"):
        build_kis_read_only_universe(
            symbols=("005930",),
            environ={"KIS_LIVE_APP_KEY": "key", "KIS_LIVE_APP_SECRET": "secret"},
            client=FakeKisUniverseClient([]),
            endpoint_profile="prod",
        )


def test_kis_readonly_universe_cli_writes_offline_plan(tmp_path):
    output = tmp_path / "kis-universe.json"

    exit_code = main(
        [
            "kis-readonly-universe",
            "--symbol",
            "A005930",
            "--symbol",
            "000660",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["symbols"] == ["005930", "000660"]


def test_kis_readonly_universe_cli_allow_network_plan_still_exits_zero(tmp_path):
    output = tmp_path / "kis-universe.json"

    exit_code = main(
        [
            "kis-readonly-universe",
            "--symbol",
            "005930",
            "--allow-network",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "network-disabled"


def test_kis_readonly_universe_cli_stop_guard_skips_network_after_session_close(monkeypatch, tmp_path):
    output = tmp_path / "kis-universe.json"

    def fail_if_called(**_kwargs):
        raise AssertionError("network builder must not run after the session stop guard")

    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fail_if_called)

    exit_code = main(
        [
            "kis-readonly-universe",
            "--symbol",
            "005930",
            "--allow-network",
            "--run-network",
            "--enforce-market-session-stop",
            "--market-session-date",
            "2026-05-12",
            "--market-session-stop-time",
            "15:35",
            "--now",
            "2026-05-12T16:20:00+09:00",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "stopped"
    assert payload["mode"] == "market-session-closed"
    assert payload["api_flags"] == ["market_session_closed"]
    assert payload["read_call_count"] == 0


def test_kis_readonly_universe_cli_stop_guard_requires_session_date(tmp_path):
    with pytest.raises(ValueError, match="market-session-date"):
        main(
            [
                "kis-readonly-universe",
                "--symbol",
                "005930",
                "--allow-network",
                "--run-network",
                "--enforce-market-session-stop",
                "--now",
                "2026-05-13T00:10:00+09:00",
                "--output",
                str(tmp_path / "kis-universe.json"),
            ]
        )


def test_kis_readonly_universe_cli_prod_network_requires_explicit_confirmation(tmp_path):
    with pytest.raises(ValueError, match="confirm-prod-readonly"):
        main(
            [
                "kis-readonly-universe",
                "--symbol",
                "005930",
                "--allow-network",
                "--run-network",
                "--endpoint-profile",
                "prod",
                "--output",
                str(tmp_path / "kis-universe.json"),
            ]
        )


def test_kis_readonly_universe_cli_defaults_to_paper_endpoint_for_network(monkeypatch, tmp_path):
    captured = {}

    def fake_build_kis_read_only_universe(**kwargs):
        captured.update(kwargs)
        return api_smoke.KisReadOnlyUniverseResult(
            status="passed",
            mode="network-read-only-paper",
            universe_id="kis-readonly-u1",
            symbol_count=1,
            included_symbols=("005930",),
            excluded_symbols=(),
            members=(),
            api_flags=(),
            read_call_count=0,
            budget_evidence={},
            safety_boundary="read-only test",
        )

    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)
    exit_code = main(
        [
            "kis-readonly-universe",
            "--symbol",
            "005930",
            "--allow-network",
            "--run-network",
            "--output",
            str(tmp_path / "kis-universe.json"),
        ]
    )

    assert exit_code == 0
    assert captured["endpoint_profile"] == "paper"


def test_kis_readonly_universe_cli_prod_report_excludes_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KIS_LIVE_APP_KEY", "prod-key-secret")
    monkeypatch.setenv("KIS_LIVE_APP_SECRET", "prod-secret-value")
    captured = {}

    def fake_build_kis_read_only_universe(**kwargs):
        captured.update(kwargs)
        return api_smoke.KisReadOnlyUniverseResult(
            status="passed",
            mode="network-read-only-prod",
            universe_id="kis-readonly-u1",
            symbol_count=1,
            included_symbols=("005930",),
            excluded_symbols=(),
            members=(),
            api_flags=(),
            read_call_count=2,
            budget_evidence={"source": "kis-readonly-universe-prod"},
            safety_boundary="read-only test",
        )

    output = tmp_path / "kis-prod-universe.json"
    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)

    exit_code = main(
        [
            "kis-readonly-universe",
            "--symbol",
            "005930",
            "--allow-network",
            "--run-network",
            "--endpoint-profile",
            "prod",
            "--confirm-prod-readonly",
            "--output",
            str(output),
        ]
    )

    stdout = capsys.readouterr().out
    serialized = output.read_text(encoding="utf-8")
    combined = stdout + serialized
    assert exit_code == 0
    assert captured["endpoint_profile"] == "prod"
    assert captured["confirm_prod_readonly"] is True
    assert "prod-key-secret" not in combined
    assert "prod-secret-value" not in combined
    assert "access_token" not in combined


def test_kis_readonly_universe_cli_include_quote_depth_returns_nonzero_when_degraded(monkeypatch, tmp_path):
    def fake_build_kis_read_only_universe(**kwargs):
        return api_smoke.KisReadOnlyUniverseResult(
            status="degraded",
            mode="network-read-only-prod",
            universe_id="kis-readonly-u1",
            symbol_count=1,
            included_symbols=("005930",),
            excluded_symbols=(),
            members=(),
            api_flags=("bid_ask_placeholder",),
            read_call_count=3,
            budget_evidence={"source": "kis-readonly-universe-prod"},
            safety_boundary="read-only test",
        )

    monkeypatch.setattr("zurini.cli.build_kis_read_only_universe", fake_build_kis_read_only_universe)

    exit_code = main(
        [
            "kis-readonly-universe",
            "--symbol",
            "005930",
            "--allow-network",
            "--run-network",
            "--endpoint-profile",
            "prod",
            "--confirm-prod-readonly",
            "--include-quote-depth",
            "--output",
            str(tmp_path / "kis-universe.json"),
        ]
    )

    assert exit_code == 1


def test_kis_readonly_universe_cli_rejects_negative_quote_interval(tmp_path):
    with pytest.raises(ValueError, match="quote-interval-seconds"):
        main(
            [
                "kis-readonly-universe",
                "--symbol",
                "005930",
                "--allow-network",
                "--run-network",
                "--endpoint-profile",
                "paper",
                "--quote-interval-seconds",
                "-1",
                "--output",
                str(tmp_path / "kis-universe.json"),
            ]
        )


def test_kis_readonly_universe_cli_prod_rate_profile_uses_field_budget():
    interval = _kis_quote_interval(Namespace(quote_interval_seconds=None, rate_profile="prod", skip_quote_depth=False))

    assert interval >= 2 / 12


def test_kis_readonly_universe_cli_prod_rate_profile_uses_critical_window_budget(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 5, 11, 15, 15, tzinfo=ZoneInfo("Asia/Seoul"))
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr("zurini.cli.datetime", FixedDatetime)

    interval = _kis_quote_interval(Namespace(quote_interval_seconds=None, rate_profile="prod", skip_quote_depth=False))

    assert interval == pytest.approx(0.3)


def test_api_smoke_network_skips_missing_env_without_calling_network():
    client = FakeHttpClient()

    payload = run_api_smoke_network(environ={}, client=client)

    probes = {probe["name"]: probe for probe in payload["probes"]}
    assert payload["status"] == "failed"
    assert probes["telegram"]["status"] == "skipped"
    assert probes["gemini"]["status"] == "skipped"
    assert probes["kis-paper-auth"]["status"] == "skipped"
    assert probes["kis-paper-market-data"]["status"] == "skipped"
    assert client.post_calls == []
    assert client.get_calls == []


def test_json_http_client_sanitizes_non_json_success_response(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeUrlopenResponse()

    monkeypatch.setattr(api_smoke, "urlopen", fake_urlopen)

    response = JsonHttpClient().get_json("https://example.invalid/smoke")

    assert response.status_code == 200
    assert response.payload["error"]["message"] == "<html>not json</html>"


def test_json_http_client_normalizes_incomplete_read_as_url_error(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeIncompleteReadResponse()

    monkeypatch.setattr(api_smoke, "urlopen", fake_urlopen)

    with pytest.raises(URLError):
        JsonHttpClient().get_json("https://example.invalid/smoke")


def test_api_smoke_cli_rejects_network_run_without_network_gate(tmp_path):
    with pytest.raises(ValueError, match="--run-network requires --allow-network"):
        main(["api-smoke", "--run-network", "--output", str(tmp_path / "api-smoke.json")])
