import json

from zurini.api_smoke import build_api_smoke_plan
from zurini.cli import main


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
