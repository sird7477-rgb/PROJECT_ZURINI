from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ApiProbe:
    name: str
    required_env: tuple[str, ...]
    enabled: bool
    missing_env: tuple[str, ...]
    mode: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


PROBES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("telegram", ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")),
    ("gemini", ("GEMINI_API_KEY",)),
    ("kis-paper-auth", ("KIS_PAPER_APP_KEY", "KIS_PAPER_APP_SECRET")),
    ("kis-paper-market-data", ("KIS_PAPER_APP_KEY", "KIS_PAPER_APP_SECRET")),
)


def build_api_smoke_plan(*, allow_network: bool = False, environ: dict[str, str] | None = None) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    mode = "network-disabled" if not allow_network else "network-contract-only"
    probes = [
        ApiProbe(
            name=name,
            required_env=required,
            enabled=allow_network and all(env.get(item) for item in required),
            missing_env=tuple(item for item in required if not env.get(item)),
            mode=mode,
        )
        for name, required in PROBES
    ]
    return {
        "status": "ready" if all(not probe.missing_env for probe in probes) else "missing-env",
        "mode": mode,
        "safety_boundary": (
            "API smoke tests are read-only connectivity/contract checks. "
            "They must not place orders, inspect .env contents, or print secret values."
        ),
        "probes": [probe.as_dict() for probe in probes],
    }
