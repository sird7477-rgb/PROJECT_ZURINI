import json

import pytest

import zurini.api_smoke as api_smoke
from zurini.api_smoke import JsonHttpClient, JsonHttpResponse, build_api_smoke_plan, run_api_smoke_network
from zurini.cli import main


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


class FakeUrlopenResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"<html>not json</html>"


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


def test_api_smoke_cli_rejects_network_run_without_network_gate(tmp_path):
    with pytest.raises(ValueError, match="--run-network requires --allow-network"):
        main(["api-smoke", "--run-network", "--output", str(tmp_path / "api-smoke.json")])
