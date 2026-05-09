from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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

KIS_PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"


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


@dataclass(frozen=True)
class ApiSmokeResult:
    name: str
    status: str
    http_status: int | None = None
    message: str = ""
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value not in (None, "", {})}


@dataclass(frozen=True)
class JsonHttpResponse:
    status_code: int
    payload: dict[str, Any]


class JsonHttpClient:
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any],
        timeout_seconds: float = 10.0,
    ) -> JsonHttpResponse:
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        return self._open_json(request, timeout_seconds=timeout_seconds)

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> JsonHttpResponse:
        request = Request(url, headers=headers or {}, method="GET")
        return self._open_json(request, timeout_seconds=timeout_seconds)

    def _open_json(self, request: Request, *, timeout_seconds: float) -> JsonHttpResponse:
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return JsonHttpResponse(response.status, _safe_json(response.read().decode("utf-8")))
        except HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else "{}"
            return JsonHttpResponse(exc.code, _safe_json(body))


class KisPaperTokenCache:
    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        client: JsonHttpClient,
        base_url: str = KIS_PAPER_BASE_URL,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._access_token = ""
        self._expires_at = datetime.min.replace(tzinfo=timezone.utc)

    def get_token(self, *, now: datetime | None = None) -> tuple[str, bool, JsonHttpResponse | None]:
        current = now or datetime.now(timezone.utc)
        if self._access_token and current < self._expires_at:
            return self._access_token, True, None

        response = self._client.post_json(
            f"{self._base_url}/oauth2/tokenP",
            payload={
                "grant_type": "client_credentials",
                "appkey": self._app_key,
                "appsecret": self._app_secret,
            },
        )
        token = str(response.payload.get("access_token") or "")
        if token:
            self._access_token = token
            self._expires_at = _kis_token_expiry(response.payload, current)
        return token, False, response


def run_api_smoke_network(
    *,
    environ: dict[str, str] | None = None,
    client: JsonHttpClient | None = None,
    symbol: str = "005930",
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    http = client or JsonHttpClient()
    plan = build_api_smoke_plan(allow_network=True, environ=env)
    results = [
        _run_telegram_probe(env, http),
        _run_gemini_probe(env, http),
        *_run_kis_paper_probes(env, http, symbol=symbol),
    ]
    return {
        "status": "passed" if all(result.status == "passed" for result in results) else "failed",
        "mode": "network-read-only",
        "safety_boundary": plan["safety_boundary"],
        "probes": [result.as_dict() for result in results],
    }


def _run_telegram_probe(env: dict[str, str], client: JsonHttpClient) -> ApiSmokeResult:
    missing = _missing(env, ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"))
    if missing:
        return ApiSmokeResult("telegram", "skipped", message="missing environment", detail={"missing_env": missing})
    try:
        response = client.get_json(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/getMe")
    except (OSError, URLError) as exc:
        return ApiSmokeResult("telegram", "failed", message=_safe_message(exc))
    ok = bool(response.payload.get("ok"))
    return ApiSmokeResult(
        "telegram",
        "passed" if ok else "failed",
        http_status=response.status_code,
        message="" if ok else str(response.payload.get("description", ""))[:200],
        detail={"bot_username_present": bool((response.payload.get("result") or {}).get("username"))},
    )


def _run_gemini_probe(env: dict[str, str], client: JsonHttpClient) -> ApiSmokeResult:
    missing = _missing(env, ("GEMINI_API_KEY",))
    if missing:
        return ApiSmokeResult("gemini", "skipped", message="missing environment", detail={"missing_env": missing})
    try:
        response = client.post_json(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            headers={"x-goog-api-key": env["GEMINI_API_KEY"]},
            payload={
                "contents": [{"parts": [{"text": "Reply with ZURINI_API_OK only."}]}],
                "generationConfig": {"maxOutputTokens": 16},
            },
        )
    except (OSError, URLError) as exc:
        return ApiSmokeResult("gemini", "failed", message=_safe_message(exc))
    has_candidates = bool(response.payload.get("candidates"))
    error = response.payload.get("error") or {}
    return ApiSmokeResult(
        "gemini",
        "passed" if response.status_code == 200 and has_candidates else "failed",
        http_status=response.status_code,
        message=str(error.get("message", ""))[:200],
        detail={"has_candidates": has_candidates},
    )


def _run_kis_paper_probes(env: dict[str, str], client: JsonHttpClient, *, symbol: str) -> list[ApiSmokeResult]:
    missing = _missing(env, ("KIS_PAPER_APP_KEY", "KIS_PAPER_APP_SECRET"))
    if missing:
        skipped = ApiSmokeResult("kis-paper-auth", "skipped", message="missing environment", detail={"missing_env": missing})
        return [skipped, ApiSmokeResult("kis-paper-market-data", "skipped", message="missing KIS paper auth")]

    token_cache = KisPaperTokenCache(
        app_key=env["KIS_PAPER_APP_KEY"],
        app_secret=env["KIS_PAPER_APP_SECRET"],
        client=client,
    )
    token, from_cache, token_response = token_cache.get_token()
    auth_result = ApiSmokeResult(
        "kis-paper-auth",
        "passed" if token else "failed",
        http_status=token_response.status_code if token_response else None,
        message="" if token else _kis_message(token_response.payload if token_response else {}),
        detail={"token_present": bool(token), "from_cache": from_cache},
    )
    if not token:
        return [auth_result, ApiSmokeResult("kis-paper-market-data", "skipped", message="missing KIS paper token")]

    query = urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol})
    try:
        price_response = client.get_json(
            f"{KIS_PAPER_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price?{query}",
            headers={
                "Authorization": f"Bearer {token}",
                "appkey": env["KIS_PAPER_APP_KEY"],
                "appsecret": env["KIS_PAPER_APP_SECRET"],
                "tr_id": "FHKST01010100",
                "custtype": "P",
            },
        )
    except (OSError, URLError) as exc:
        return [auth_result, ApiSmokeResult("kis-paper-market-data", "failed", message=_safe_message(exc))]
    output = price_response.payload.get("output") or {}
    rt_cd = str(price_response.payload.get("rt_cd", ""))
    return [
        auth_result,
        ApiSmokeResult(
            "kis-paper-market-data",
            "passed" if price_response.status_code == 200 and rt_cd == "0" and bool(output.get("stck_prpr")) else "failed",
            http_status=price_response.status_code,
            message=_kis_message(price_response.payload),
            detail={"rt_cd": rt_cd, "price_present": bool(output.get("stck_prpr")), "symbol": symbol},
        ),
    ]


def _missing(env: dict[str, str], names: tuple[str, ...]) -> list[str]:
    return [name for name in names if not env.get(name)]


def _safe_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": {"message": raw[:200]}}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _safe_message(exc: BaseException) -> str:
    return str(exc)[:200]


def _kis_message(payload: dict[str, Any]) -> str:
    return str(payload.get("msg1") or payload.get("error_description") or payload.get("message") or "")[:200]


def _kis_token_expiry(payload: dict[str, Any], now: datetime) -> datetime:
    expires_in = int(payload.get("expires_in") or 3600)
    return now + timedelta(seconds=max(0, expires_in - 60))
