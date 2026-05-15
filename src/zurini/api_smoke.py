from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from math import ceil
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from zurini.api_budget import build_read_call_budget_evidence, normalize_to_kst


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

KIS_LIVE_BASE_URL = "https://openapi.koreainvestment.com:9443"
KIS_PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
KIS_PAIRED_SNAPSHOT_MAX_GAP_SECONDS = 5.0


@dataclass(frozen=True)
class KisEndpointProfile:
    name: str
    base_url: str
    app_key_env: str
    app_secret_env: str
    auth_probe_name: str
    market_data_probe_name: str


KIS_ENDPOINT_PROFILES: dict[str, KisEndpointProfile] = {
    "prod": KisEndpointProfile(
        name="prod",
        base_url=KIS_LIVE_BASE_URL,
        app_key_env="KIS_LIVE_APP_KEY",
        app_secret_env="KIS_LIVE_APP_SECRET",
        auth_probe_name="kis-prod-auth",
        market_data_probe_name="kis-prod-market-data",
    ),
    "paper": KisEndpointProfile(
        name="paper",
        base_url=KIS_PAPER_BASE_URL,
        app_key_env="KIS_PAPER_APP_KEY",
        app_secret_env="KIS_PAPER_APP_SECRET",
        auth_probe_name="kis-paper-auth",
        market_data_probe_name="kis-paper-market-data",
    ),
}


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
    diagnostics: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value not in (None, "", {})}


@dataclass(frozen=True)
class KisUniverseMember:
    symbol: str
    price: str
    included: bool
    reason: str
    open: str = ""
    high: str = ""
    low: str = ""
    volume: str = ""
    traded_value: str = ""
    previous_day_change_rate: str = ""
    observed_at: str = ""
    price_observed_at: str = ""
    depth_observed_at: str = ""
    paired_snapshot_gap_seconds: str = ""
    ask_volume: str = ""
    bid_volume: str = ""
    bid_ask_ratio: str = ""
    field_data_flags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in ("", None, ())}


@dataclass(frozen=True)
class KisReadOnlyUniverseResult:
    status: str
    mode: str
    universe_id: str
    symbol_count: int
    included_symbols: tuple[str, ...]
    excluded_symbols: tuple[tuple[str, str], ...]
    members: tuple[KisUniverseMember, ...]
    api_flags: tuple[str, ...]
    read_call_count: int
    budget_evidence: dict[str, Any]
    safety_boundary: str
    ready_for_broker_or_order_transmission: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "members": [member.as_dict() for member in self.members],
        }


@dataclass(frozen=True)
class KisQuoteDepthMember:
    symbol: str
    included: bool
    reason: str
    observed_at: str = ""
    ask_volume: str = ""
    bid_volume: str = ""
    bid_ask_ratio: str = ""
    field_data_flags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in ("", None, ())}


@dataclass(frozen=True)
class KisReadOnlyDepthResult:
    status: str
    mode: str
    universe_id: str
    symbol_count: int
    included_symbols: tuple[str, ...]
    excluded_symbols: tuple[tuple[str, str], ...]
    members: tuple[KisQuoteDepthMember, ...]
    api_flags: tuple[str, ...]
    read_call_count: int
    budget_evidence: dict[str, Any]
    safety_boundary: str
    ready_for_broker_or_order_transmission: bool = False
    parallel_collection_note: str = (
        "Quote-depth snapshots are collected in a separate read-only loop. "
        "Do not treat them as same-tick joins with price snapshots unless paired_snapshot_evidence is fresh."
    )
    paired_snapshot_evidence: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            **asdict(self),
            "members": [member.as_dict() for member in self.members],
        }
        if self.paired_snapshot_evidence is None:
            payload.pop("paired_snapshot_evidence", None)
        return payload


@dataclass(frozen=True)
class KisAuthPreflightResult:
    status: str
    mode: str
    api_flags: tuple[str, ...]
    read_call_count: int
    token_present: bool
    from_cache: bool
    safety_boundary: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KisHolidayRow:
    bass_dt: date
    wday_dvsn_cd: str
    bzdy_yn: str
    tr_day_yn: str
    opnd_yn: str
    sttl_day_yn: str

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "bass_dt": self.bass_dt.isoformat(),
        }


@dataclass(frozen=True)
class KisHolidayCalendarResult:
    status: str
    mode: str
    target_date: date
    query_start_date: date
    expected_prior_date: date | None
    rows: tuple[KisHolidayRow, ...]
    api_flags: tuple[str, ...]
    read_call_count: int
    safety_boundary: str
    ready_for_broker_or_order_transmission: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "target_date": self.target_date.isoformat(),
            "query_start_date": self.query_start_date.isoformat(),
            "expected_prior_date": self.expected_prior_date.isoformat() if self.expected_prior_date else None,
            "rows": [row.as_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class KisDailyBar:
    symbol: str
    trading_date: date
    open: str
    high: str
    low: str
    close: str
    volume: str
    traded_value: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "trading_date": self.trading_date.isoformat(),
        }


@dataclass(frozen=True)
class KisDailyBarsMember:
    symbol: str
    included: bool
    reason: str
    rows: tuple[KisDailyBar, ...] = ()
    field_data_flags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "included": self.included,
            "reason": self.reason,
            "rows": [row.as_dict() for row in self.rows],
        }
        if self.field_data_flags:
            payload["field_data_flags"] = self.field_data_flags
        return payload


@dataclass(frozen=True)
class KisDailyBarsResult:
    status: str
    mode: str
    symbol_count: int
    start_date: date
    end_date: date
    included_symbols: tuple[str, ...]
    excluded_symbols: tuple[tuple[str, str], ...]
    members: tuple[KisDailyBarsMember, ...]
    api_flags: tuple[str, ...]
    read_call_count: int
    budget_evidence: dict[str, Any]
    safety_boundary: str
    latest_prior_date: date | None = None
    source_fresh: bool = False
    ready_for_broker_or_order_transmission: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "latest_prior_date": self.latest_prior_date.isoformat() if self.latest_prior_date else None,
            "members": [member.as_dict() for member in self.members],
        }


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


class KisTokenCache:
    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        client: JsonHttpClient,
        base_url: str,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._access_token = ""
        self._expires_at = datetime.min.replace(tzinfo=timezone.utc)
        self._last_issue_attempt_at: datetime | None = None

    def get_token(self, *, now: datetime | None = None) -> tuple[str, bool, JsonHttpResponse | None]:
        current = now or datetime.now(timezone.utc)
        if self._access_token and current < self._expires_at:
            return self._access_token, True, None
        if (
            self._last_issue_attempt_at is not None
            and current - self._last_issue_attempt_at < timedelta(minutes=1)
        ):
            return "", False, JsonHttpResponse(0, {"auth_cooldown": True})
        try:
            response = self._client.post_json(
                f"{self._base_url}/oauth2/tokenP",
                payload={
                    "grant_type": "client_credentials",
                    "appkey": self._app_key,
                    "appsecret": self._app_secret,
                },
            )
        except (OSError, URLError):
            self._last_issue_attempt_at = current
            raise
        token = str(response.payload.get("access_token") or "")
        if token:
            self._access_token = token
            self._expires_at = _kis_token_expiry(response.payload, current)
            if current < self._expires_at:
                self._last_issue_attempt_at = None
            else:
                response = JsonHttpResponse(
                    response.status_code,
                    {key: value for key, value in response.payload.items() if key != "access_token"}
                    | {"token_expired_immediately": True},
                )
                token = ""
                self._last_issue_attempt_at = current
        else:
            self._last_issue_attempt_at = current
        return token, False, response


def prewarm_kis_token_cache(
    *,
    environ: dict[str, str] | None = None,
    client: JsonHttpClient | None = None,
    endpoint_profile: str = "paper",
    auth_cooldown_path: Path | None = None,
    confirm_prod_readonly: bool = False,
) -> tuple[KisTokenCache | None, KisAuthPreflightResult]:
    kis_profile = _kis_endpoint_profile(endpoint_profile)
    if kis_profile.name == "prod" and not confirm_prod_readonly:
        raise ValueError("prod read-only KIS access requires confirm_prod_readonly=True")
    env = environ if environ is not None else os.environ
    http = client or JsonHttpClient()
    mode = f"network-read-only-auth-{kis_profile.name}"
    safety_boundary = "read-only KIS auth preflight; no broker order, account, balance, or real-fill calls"
    missing = _missing(env, (kis_profile.app_key_env, kis_profile.app_secret_env))
    if missing:
        return None, KisAuthPreflightResult(
            status="failed",
            mode=mode,
            api_flags=("api_auth_error",),
            read_call_count=0,
            token_present=False,
            from_cache=False,
            safety_boundary=safety_boundary,
        )
    cooldown = _read_auth_cooldown(auth_cooldown_path, profile=kis_profile.name)
    if cooldown is not None:
        return None, KisAuthPreflightResult(
            status="failed",
            mode=mode,
            api_flags=(str(cooldown.get("flag") or "api_auth_cooldown"),),
            read_call_count=0,
            token_present=False,
            from_cache=False,
            safety_boundary=safety_boundary,
        )

    token_cache = KisTokenCache(
        app_key=env[kis_profile.app_key_env],
        app_secret=env[kis_profile.app_secret_env],
        client=http,
        base_url=kis_profile.base_url,
    )
    try:
        token, from_cache, token_response = token_cache.get_token()
    except (OSError, URLError):
        _write_auth_cooldown(auth_cooldown_path, profile=kis_profile.name, flag="api_timeout", reason="auth timeout or network error")
        return None, KisAuthPreflightResult(
            status="failed",
            mode=mode,
            api_flags=("api_timeout",),
            read_call_count=1,
            token_present=False,
            from_cache=False,
            safety_boundary=safety_boundary,
        )
    if not token:
        diagnostic = _kis_diagnostic(
            probe_name=kis_profile.auth_probe_name,
            http_status=token_response.status_code if token_response else None,
            payload=token_response.payload if token_response else {},
            expected_fields=("access_token",),
        )
        _write_auth_cooldown(
            auth_cooldown_path,
            profile=kis_profile.name,
            flag=str((diagnostic["flags"] or ["api_auth_error"])[0]),
            reason=str(diagnostic["reason"]),
        )
        return None, KisAuthPreflightResult(
            status="failed",
            mode=mode,
            api_flags=tuple(diagnostic["flags"]),
            read_call_count=1,
            token_present=False,
            from_cache=from_cache,
            safety_boundary=safety_boundary,
        )
    _clear_auth_cooldown(auth_cooldown_path, profile=kis_profile.name)
    return token_cache, KisAuthPreflightResult(
        status="passed",
        mode=mode,
        api_flags=(),
        read_call_count=1,
        token_present=True,
        from_cache=from_cache,
        safety_boundary=safety_boundary,
    )


def run_api_smoke_network(
    *,
    environ: dict[str, str] | None = None,
    client: JsonHttpClient | None = None,
    symbol: str = "005930",
    auth_cooldown_path: Path | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    http = client or JsonHttpClient()
    plan = build_api_smoke_plan(allow_network=True, environ=env)
    results = [
        _run_telegram_probe(env, http),
        _run_gemini_probe(env, http),
        *_run_kis_paper_probes(env, http, symbol=symbol, auth_cooldown_path=auth_cooldown_path),
    ]
    return {
        "status": "passed" if all(result.status == "passed" for result in results) else "failed",
        "mode": "network-read-only",
        "safety_boundary": plan["safety_boundary"],
        "probes": [result.as_dict() for result in results],
        "api_flags": _api_flags(results),
    }


def build_kis_read_only_universe_plan(*, symbols: tuple[str, ...]) -> dict[str, Any]:
    normalized = _normalize_symbols(symbols)
    return {
        "status": "ready" if normalized else "missing-symbols",
        "mode": "network-disabled",
        "universe_id": "kis-readonly-u1-plan",
        "symbol_count": len(normalized),
        "symbols": list(normalized),
        "ready_for_broker_or_order_transmission": False,
        "safety_boundary": (
            "KIS universe construction uses read-only market-data probes only. "
            "It must not call order, balance, account, or credential-persistence endpoints."
        ),
    }


def build_kis_read_only_depth_plan(*, symbols: tuple[str, ...]) -> dict[str, Any]:
    normalized = _normalize_symbols(symbols)
    return {
        "status": "ready" if normalized else "missing-symbols",
        "mode": "network-disabled",
        "universe_id": "kis-readonly-depth-plan",
        "symbol_count": len(normalized),
        "symbols": list(normalized),
        "ready_for_broker_or_order_transmission": False,
        "parallel_collection_note": (
            "Quote-depth collection is a separate read-only stream; compare observed_at "
            "with the price snapshot before using the ratio as strategy evidence."
        ),
        "safety_boundary": (
            "KIS quote-depth construction uses read-only market-data probes only. "
            "It must not call order, balance, account, or credential-persistence endpoints."
        ),
    }


def build_kis_daily_bars_plan(*, symbols: tuple[str, ...], start_date: date, end_date: date) -> dict[str, Any]:
    _validate_date_range(start_date, end_date)
    normalized = _normalize_symbols(symbols)
    return {
        "status": "ready" if normalized else "missing-symbols",
        "mode": "network-disabled",
        "symbol_count": len(normalized),
        "symbols": list(normalized),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "ready_for_broker_or_order_transmission": False,
        "safety_boundary": (
            "KIS daily-bar collection uses read-only domestic stock period-price probes only. "
            "It must not call order, balance, account, or credential-persistence endpoints."
        ),
    }


def build_kis_holiday_calendar(
    *,
    target_date: date,
    environ: dict[str, str] | None = None,
    client: JsonHttpClient | None = None,
    endpoint_profile: str = "paper",
    auth_cooldown_path: Path | None = None,
    confirm_prod_readonly: bool = False,
    token_cache: KisTokenCache | None = None,
) -> KisHolidayCalendarResult:
    kis_profile = _kis_endpoint_profile(endpoint_profile)
    if kis_profile.name == "prod" and not confirm_prod_readonly:
        raise ValueError("prod read-only KIS access requires confirm_prod_readonly=True")
    env = environ if environ is not None else os.environ
    http = client or JsonHttpClient()
    safety_boundary = (
        "read-only KIS domestic holiday calendar; no broker order, account, balance, or real-fill calls"
    )
    query_start_date = target_date - timedelta(days=120)
    missing = _missing(env, (kis_profile.app_key_env, kis_profile.app_secret_env))
    if missing:
        return KisHolidayCalendarResult(
            status="failed",
            mode=f"network-read-only-holiday-calendar-{kis_profile.name}",
            target_date=target_date,
            query_start_date=query_start_date,
            expected_prior_date=None,
            rows=(),
            api_flags=("api_auth_error",),
            read_call_count=0,
            safety_boundary=safety_boundary,
        )
    token_cache = token_cache or KisTokenCache(
        app_key=env[kis_profile.app_key_env],
        app_secret=env[kis_profile.app_secret_env],
        client=http,
        base_url=kis_profile.base_url,
    )
    cooldown = _read_auth_cooldown(auth_cooldown_path, profile=kis_profile.name)
    if cooldown is not None:
        return KisHolidayCalendarResult(
            status="failed",
            mode=f"network-read-only-holiday-calendar-{kis_profile.name}",
            target_date=target_date,
            query_start_date=query_start_date,
            expected_prior_date=None,
            rows=(),
            api_flags=(str(cooldown.get("flag") or "api_auth_cooldown"),),
            read_call_count=0,
            safety_boundary=safety_boundary,
        )
    try:
        token, _, token_response = token_cache.get_token()
    except (OSError, URLError):
        _write_auth_cooldown(auth_cooldown_path, profile=kis_profile.name, flag="api_timeout", reason="auth timeout or network error")
        return KisHolidayCalendarResult(
            status="failed",
            mode=f"network-read-only-holiday-calendar-{kis_profile.name}",
            target_date=target_date,
            query_start_date=query_start_date,
            expected_prior_date=None,
            rows=(),
            api_flags=("api_timeout",),
            read_call_count=1,
            safety_boundary=safety_boundary,
        )
    if not token:
        diagnostic = _kis_diagnostic(
            probe_name=kis_profile.auth_probe_name,
            http_status=token_response.status_code if token_response else None,
            payload=token_response.payload if token_response else {},
            expected_fields=("access_token",),
        )
        _write_auth_cooldown(
            auth_cooldown_path,
            profile=kis_profile.name,
            flag=str((diagnostic["flags"] or ["api_auth_error"])[0]),
            reason=str(diagnostic["reason"]),
        )
        return KisHolidayCalendarResult(
            status="failed",
            mode=f"network-read-only-holiday-calendar-{kis_profile.name}",
            target_date=target_date,
            query_start_date=query_start_date,
            expected_prior_date=None,
            rows=(),
            api_flags=tuple(diagnostic["flags"]),
            read_call_count=1,
            safety_boundary=safety_boundary,
        )
    rows_by_date: dict[date, KisHolidayRow] = {}
    all_flags: list[str] = []
    status_codes: list[int] = []
    read_call_count = 1
    try:
        base_date = query_start_date
        while base_date <= target_date:
            response = _kis_chk_holiday(
                env,
                http,
                token=token,
                base_date=base_date,
                profile=kis_profile,
            )
            read_call_count += 1
            status_codes.append(response.status_code)
            diagnostic = _kis_diagnostic(
                probe_name=f"{kis_profile.market_data_probe_name}-holiday-calendar",
                http_status=response.status_code,
                payload=response.payload,
                expected_fields=("output",),
            )
            rows, row_flags = _parse_kis_holiday_rows(response.payload.get("output"))
            all_flags.extend(str(flag) for flag in (*diagnostic["flags"], *row_flags) if flag)
            for row in rows:
                rows_by_date[row.bass_dt] = row
            base_date += timedelta(days=20)
    except (OSError, URLError):
        return KisHolidayCalendarResult(
            status="failed",
            mode=f"network-read-only-holiday-calendar-{kis_profile.name}",
            target_date=target_date,
            query_start_date=query_start_date,
            expected_prior_date=None,
            rows=(),
            api_flags=("api_timeout",),
            read_call_count=read_call_count,
            safety_boundary=safety_boundary,
        )
    rows = tuple(sorted(rows_by_date.values(), key=lambda item: item.bass_dt))
    flags = tuple(dict.fromkeys(all_flags))
    mismatch = [row.bass_dt for row in rows if row.bass_dt < target_date and row.bzdy_yn == "Y" and row.opnd_yn != "Y"]
    if mismatch:
        flags = tuple(dict.fromkeys((*flags, "holiday_calendar_business_open_mismatch")))
    prior_candidates = [
        row.bass_dt
        for row in rows
        if row.bass_dt < target_date and row.bzdy_yn == "Y" and row.opnd_yn == "Y"
    ]
    expected_prior_date = max(prior_candidates, default=None)
    status = "passed" if status_codes and all(code == 200 for code in status_codes) and expected_prior_date is not None and not flags else "failed"
    return KisHolidayCalendarResult(
        status=status,
        mode=f"network-read-only-holiday-calendar-{kis_profile.name}",
        target_date=target_date,
        query_start_date=query_start_date,
        expected_prior_date=expected_prior_date,
        rows=rows,
        api_flags=flags,
        read_call_count=read_call_count,
        safety_boundary=safety_boundary,
    )


def build_kis_read_only_universe(
    *,
    symbols: tuple[str, ...],
    environ: dict[str, str] | None = None,
    client: JsonHttpClient | None = None,
    quote_interval_seconds: float = 0.0,
    endpoint_profile: str = "paper",
    auth_cooldown_path: Path | None = None,
    confirm_prod_readonly: bool = False,
    include_quote_depth: bool = False,
    token_cache: KisTokenCache | None = None,
) -> KisReadOnlyUniverseResult:
    if quote_interval_seconds < 0:
        raise ValueError("quote_interval_seconds must be non-negative")
    kis_profile = _kis_endpoint_profile(endpoint_profile)
    if kis_profile.name == "prod" and not confirm_prod_readonly:
        raise ValueError("prod read-only KIS access requires confirm_prod_readonly=True")
    normalized = _normalize_symbols(symbols)
    env = environ if environ is not None else os.environ
    http = client or JsonHttpClient()
    safety_boundary = (
        "read-only KIS market-data universe; no broker order, account, balance, or real-fill calls"
    )
    if not normalized:
        return KisReadOnlyUniverseResult(
            status="failed",
            mode=f"network-read-only-{kis_profile.name}",
            universe_id="kis-readonly-u1",
            symbol_count=0,
            included_symbols=(),
            excluded_symbols=(),
            members=(),
            api_flags=("api_command_error",),
            read_call_count=0,
            budget_evidence=_kis_budget_evidence(
                read_call_count=0,
                quote_call_count=0,
                api_flags=("api_command_error",),
                source=f"kis-readonly-universe-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )
    missing = _missing(env, (kis_profile.app_key_env, kis_profile.app_secret_env))
    if missing:
        return KisReadOnlyUniverseResult(
            status="failed",
            mode=f"network-read-only-{kis_profile.name}",
            universe_id="kis-readonly-u1",
            symbol_count=len(normalized),
            included_symbols=(),
            excluded_symbols=tuple((symbol, f"missing KIS {kis_profile.name} auth") for symbol in normalized),
            members=tuple(KisUniverseMember(symbol, "", False, f"missing KIS {kis_profile.name} auth") for symbol in normalized),
            api_flags=("api_auth_error",),
            read_call_count=0,
            budget_evidence=_kis_budget_evidence(
                read_call_count=0,
                quote_call_count=0,
                api_flags=("api_auth_error",),
                source=f"kis-readonly-universe-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )

    token_cache = token_cache or KisTokenCache(
        app_key=env[kis_profile.app_key_env],
        app_secret=env[kis_profile.app_secret_env],
        client=http,
        base_url=kis_profile.base_url,
    )
    call_timestamps: list[datetime] = []
    cooldown = _read_auth_cooldown(auth_cooldown_path, profile=kis_profile.name)
    if cooldown is not None:
        flag = str(cooldown.get("flag") or "api_auth_cooldown")
        reason = str(cooldown.get("reason") or "prior KIS auth failure")
        return KisReadOnlyUniverseResult(
            status="failed",
            mode=f"network-read-only-{kis_profile.name}",
            universe_id="kis-readonly-u1",
            symbol_count=len(normalized),
            included_symbols=(),
            excluded_symbols=tuple((symbol, f"KIS auth cooldown after {reason}") for symbol in normalized),
            members=tuple(KisUniverseMember(symbol, "", False, f"KIS auth cooldown after {reason}") for symbol in normalized),
            api_flags=(flag,),
            read_call_count=0,
            budget_evidence=_kis_budget_evidence(
                read_call_count=0,
                quote_call_count=0,
                api_flags=(flag,),
                source=f"kis-readonly-universe-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )
    try:
        call_timestamps.append(datetime.now(timezone.utc))
        token, _, token_response = token_cache.get_token()
    except (OSError, URLError) as exc:
        _write_auth_cooldown(auth_cooldown_path, profile=kis_profile.name, flag="api_timeout", reason="auth timeout or network error")
        return KisReadOnlyUniverseResult(
            status="failed",
            mode=f"network-read-only-{kis_profile.name}",
            universe_id="kis-readonly-u1",
            symbol_count=len(normalized),
            included_symbols=(),
            excluded_symbols=tuple((symbol, "KIS auth timeout or network error") for symbol in normalized),
            members=tuple(KisUniverseMember(symbol, "", False, "KIS auth timeout or network error") for symbol in normalized),
            api_flags=("api_timeout",),
            read_call_count=1,
            budget_evidence=_kis_budget_evidence(
                read_call_count=1,
                quote_call_count=0,
                call_timestamps=tuple(call_timestamps),
                api_flags=("api_timeout",),
                source=f"kis-readonly-universe-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )
    if not token:
        diagnostic = _kis_diagnostic(
            probe_name=kis_profile.auth_probe_name,
            http_status=token_response.status_code if token_response else None,
            payload=token_response.payload if token_response else {},
            expected_fields=("access_token",),
        )
        _write_auth_cooldown(
            auth_cooldown_path,
            profile=kis_profile.name,
            flag=str((diagnostic["flags"] or ["api_auth_error"])[0]),
            reason=str(diagnostic["reason"]),
        )
        return KisReadOnlyUniverseResult(
            status="failed",
            mode=f"network-read-only-{kis_profile.name}",
            universe_id="kis-readonly-u1",
            symbol_count=len(normalized),
            included_symbols=(),
            excluded_symbols=tuple((symbol, f"missing KIS {kis_profile.name} token") for symbol in normalized),
            members=tuple(KisUniverseMember(symbol, "", False, f"missing KIS {kis_profile.name} token") for symbol in normalized),
            api_flags=tuple(diagnostic["flags"]),
            read_call_count=1,
            budget_evidence=_kis_budget_evidence(
                read_call_count=1,
                quote_call_count=0,
                call_timestamps=tuple(call_timestamps),
                api_flags=tuple(diagnostic["flags"]),
                source=f"kis-readonly-universe-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )

    members: list[KisUniverseMember] = []
    _clear_auth_cooldown(auth_cooldown_path, profile=kis_profile.name)
    flags: list[str] = []
    read_call_count = 1
    for index, symbol in enumerate(normalized):
        if quote_interval_seconds and index > 0:
            time.sleep(quote_interval_seconds)
        depth_response: JsonHttpResponse | None = None
        if include_quote_depth:
            try:
                read_call_count += 1
                call_timestamps.append(datetime.now(timezone.utc))
                response = _kis_inquire_price(env, http, token=token, symbol=symbol, profile=kis_profile)
                price_observed_at = datetime.now(timezone.utc)
            except (OSError, URLError):
                flags.append("api_timeout")
                members.append(KisUniverseMember(symbol, "", False, "api timeout or network error"))
                continue
            try:
                read_call_count += 1
                call_timestamps.append(datetime.now(timezone.utc))
                depth_response = _kis_inquire_asking_price_exp_ccn(
                    env,
                    http,
                    token=token,
                    symbol=symbol,
                    profile=kis_profile,
                )
                depth_observed_at = datetime.now(timezone.utc)
            except (OSError, URLError):
                flags.append("api_timeout")
                depth_observed_at = None
        else:
            try:
                read_call_count += 1
                call_timestamps.append(datetime.now(timezone.utc))
                response = _kis_inquire_price(env, http, token=token, symbol=symbol, profile=kis_profile)
                price_observed_at = datetime.now(timezone.utc)
            except (OSError, URLError) as exc:
                members.append(KisUniverseMember(symbol, "", False, "api timeout or network error"))
                flags.append("api_timeout")
                continue
        output = response.payload.get("output") or {}
        observed_at = price_observed_at
        if not include_quote_depth:
            depth_observed_at = None
        paired_snapshot_gap_seconds: float | None = None
        price = str(output.get("stck_prpr") or "")
        ask_volume = _first_output_value(output, "total_askp_rsqn", "askp_rsqn", "askp_rsqn1")
        bid_volume = _first_output_value(output, "total_bidp_rsqn", "bidp_rsqn", "bidp_rsqn1")
        bid_ask_ratio = _bid_ask_ratio(bid_volume, ask_volume)
        if include_quote_depth:
            if depth_response is not None and depth_observed_at is not None:
                paired_snapshot_gap_seconds = abs((depth_observed_at - price_observed_at).total_seconds())
                depth_output = depth_response.payload.get("output1") or depth_response.payload.get("output") or {}
                depth_diagnostic = _kis_diagnostic(
                    probe_name=f"{kis_profile.market_data_probe_name}-depth",
                    http_status=depth_response.status_code,
                    payload=depth_response.payload,
                    expected_fields=("output1",),
                )
                flags.extend(depth_diagnostic["flags"])
                depth_ask_volume = _first_output_value(depth_output, "total_askp_rsqn", "askp_rsqn", "askp_rsqn1")
                depth_bid_volume = _first_output_value(depth_output, "total_bidp_rsqn", "bidp_rsqn", "bidp_rsqn1")
                depth_bid_ask_ratio = _bid_ask_ratio(depth_bid_volume, depth_ask_volume)
                ask_volume = depth_ask_volume
                bid_volume = depth_bid_volume
                if depth_bid_ask_ratio:
                    bid_ask_ratio = depth_bid_ask_ratio
                    observed_at = depth_observed_at
                else:
                    flags.append("bid_ask_placeholder")
                if paired_snapshot_gap_seconds > KIS_PAIRED_SNAPSHOT_MAX_GAP_SECONDS:
                    flags.append("paired_snapshot_gap_exceeded")
        if include_quote_depth and depth_observed_at is None:
            flags.append("paired_snapshot_missing")
        field_data_flags = _kis_field_data_flags(
            output,
            price=price,
            bid_ask_ratio=bid_ask_ratio,
        )
        if include_quote_depth and depth_observed_at is None:
            field_data_flags = tuple(dict.fromkeys((*field_data_flags, "paired_snapshot_missing")))
        if paired_snapshot_gap_seconds is not None and paired_snapshot_gap_seconds > KIS_PAIRED_SNAPSHOT_MAX_GAP_SECONDS:
            field_data_flags = tuple(dict.fromkeys((*field_data_flags, "paired_snapshot_gap_exceeded")))
        diagnostic = _kis_diagnostic(
            probe_name=kis_profile.market_data_probe_name,
            http_status=response.status_code,
            payload=response.payload,
            expected_fields=("output.stck_prpr",),
        )
        flags.extend(diagnostic["flags"])
        included = response.status_code == 200 and str(response.payload.get("rt_cd", "")) == "0" and bool(price)
        if included:
            flags.extend(field_data_flags)
        members.append(
            KisUniverseMember(
                symbol=symbol,
                price=price,
                included=included,
                reason="read-only quote ok" if included else diagnostic["reason"],
                open=str(output.get("stck_oprc") or ""),
                high=str(output.get("stck_hgpr") or ""),
                low=str(output.get("stck_lwpr") or ""),
                volume=str(output.get("acml_vol") or ""),
                traded_value=str(output.get("acml_tr_pbmn") or ""),
                previous_day_change_rate=str(output.get("prdy_ctrt") or ""),
                observed_at=observed_at.isoformat(),
                price_observed_at=price_observed_at.isoformat(),
                depth_observed_at=depth_observed_at.isoformat() if depth_observed_at else "",
                paired_snapshot_gap_seconds=(
                    f"{paired_snapshot_gap_seconds:.6f}" if paired_snapshot_gap_seconds is not None else ""
                ),
                ask_volume=ask_volume,
                bid_volume=bid_volume,
                bid_ask_ratio=bid_ask_ratio,
                field_data_flags=field_data_flags,
            )
        )

    included_symbols = tuple(member.symbol for member in members if member.included)
    excluded_symbols = tuple((member.symbol, member.reason) for member in members if not member.included)
    unique_flags = tuple(dict.fromkeys(flags))
    budget_evidence = _kis_budget_evidence(
        read_call_count=read_call_count,
        quote_call_count=len(normalized),
        quote_interval_seconds=quote_interval_seconds,
        call_timestamps=tuple(call_timestamps),
        api_flags=unique_flags,
        source=f"kis-readonly-universe-{kis_profile.name}",
    )
    if not budget_evidence.get("within_budget") and "api_rate_limit_risk" not in unique_flags:
        unique_flags = tuple(dict.fromkeys((*unique_flags, "api_rate_limit_risk")))
        budget_evidence = _kis_budget_evidence(
            read_call_count=read_call_count,
            quote_call_count=len(normalized),
            quote_interval_seconds=quote_interval_seconds,
            call_timestamps=tuple(call_timestamps),
            api_flags=unique_flags,
            source=f"kis-readonly-universe-{kis_profile.name}",
        )
    return KisReadOnlyUniverseResult(
        status="passed" if included_symbols and not unique_flags else "degraded" if included_symbols else "failed",
        mode=f"network-read-only-{kis_profile.name}",
        universe_id="kis-readonly-u1",
        symbol_count=len(normalized),
        included_symbols=included_symbols,
        excluded_symbols=excluded_symbols,
        members=tuple(members),
        api_flags=unique_flags,
        read_call_count=read_call_count,
        budget_evidence=budget_evidence,
        safety_boundary=safety_boundary,
    )


def build_kis_daily_bars(
    *,
    symbols: tuple[str, ...],
    start_date: date,
    end_date: date,
    environ: dict[str, str] | None = None,
    client: JsonHttpClient | None = None,
    quote_interval_seconds: float = 0.0,
    endpoint_profile: str = "paper",
    auth_cooldown_path: Path | None = None,
    confirm_prod_readonly: bool = False,
    min_trading_days: int = 60,
    token_cache: KisTokenCache | None = None,
) -> KisDailyBarsResult:
    _validate_date_range(start_date, end_date)
    if quote_interval_seconds < 0:
        raise ValueError("quote_interval_seconds must be non-negative")
    if min_trading_days <= 0:
        raise ValueError("min_trading_days must be positive")
    kis_profile = _kis_endpoint_profile(endpoint_profile)
    if kis_profile.name == "prod" and not confirm_prod_readonly:
        raise ValueError("prod read-only KIS access requires confirm_prod_readonly=True")
    normalized = _normalize_symbols(symbols)
    env = environ if environ is not None else os.environ
    http = client or JsonHttpClient()
    safety_boundary = (
        "read-only KIS daily-bar collection; no broker order, account, balance, or real-fill calls"
    )
    empty_budget = _kis_budget_evidence(
        read_call_count=0,
        quote_call_count=0,
        api_flags=("api_command_error",),
        source=f"kis-daily-bars-{kis_profile.name}",
    )
    if not normalized:
        return KisDailyBarsResult(
            status="failed",
            mode=f"network-read-only-daily-bars-{kis_profile.name}",
            symbol_count=0,
            start_date=start_date,
            end_date=end_date,
            included_symbols=(),
            excluded_symbols=(),
            members=(),
            api_flags=("api_command_error",),
            read_call_count=0,
            budget_evidence=empty_budget,
            safety_boundary=safety_boundary,
        )
    missing = _missing(env, (kis_profile.app_key_env, kis_profile.app_secret_env))
    if missing:
        return KisDailyBarsResult(
            status="failed",
            mode=f"network-read-only-daily-bars-{kis_profile.name}",
            symbol_count=len(normalized),
            start_date=start_date,
            end_date=end_date,
            included_symbols=(),
            excluded_symbols=tuple((symbol, f"missing KIS {kis_profile.name} auth") for symbol in normalized),
            members=tuple(KisDailyBarsMember(symbol, False, f"missing KIS {kis_profile.name} auth") for symbol in normalized),
            api_flags=("api_auth_error",),
            read_call_count=0,
            budget_evidence=_kis_budget_evidence(
                read_call_count=0,
                quote_call_count=0,
                api_flags=("api_auth_error",),
                source=f"kis-daily-bars-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )

    token_cache = token_cache or KisTokenCache(
        app_key=env[kis_profile.app_key_env],
        app_secret=env[kis_profile.app_secret_env],
        client=http,
        base_url=kis_profile.base_url,
    )
    call_timestamps: list[datetime] = []
    cooldown = _read_auth_cooldown(auth_cooldown_path, profile=kis_profile.name)
    if cooldown is not None:
        flag = str(cooldown.get("flag") or "api_auth_cooldown")
        reason = str(cooldown.get("reason") or "prior KIS auth failure")
        return KisDailyBarsResult(
            status="failed",
            mode=f"network-read-only-daily-bars-{kis_profile.name}",
            symbol_count=len(normalized),
            start_date=start_date,
            end_date=end_date,
            included_symbols=(),
            excluded_symbols=tuple((symbol, f"KIS auth cooldown after {reason}") for symbol in normalized),
            members=tuple(KisDailyBarsMember(symbol, False, f"KIS auth cooldown after {reason}") for symbol in normalized),
            api_flags=(flag,),
            read_call_count=0,
            budget_evidence=_kis_budget_evidence(
                read_call_count=0,
                quote_call_count=0,
                api_flags=(flag,),
                source=f"kis-daily-bars-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )
    try:
        call_timestamps.append(datetime.now(timezone.utc))
        token, _, token_response = token_cache.get_token()
    except (OSError, URLError):
        _write_auth_cooldown(auth_cooldown_path, profile=kis_profile.name, flag="api_timeout", reason="auth timeout or network error")
        return KisDailyBarsResult(
            status="failed",
            mode=f"network-read-only-daily-bars-{kis_profile.name}",
            symbol_count=len(normalized),
            start_date=start_date,
            end_date=end_date,
            included_symbols=(),
            excluded_symbols=tuple((symbol, "KIS auth timeout or network error") for symbol in normalized),
            members=tuple(KisDailyBarsMember(symbol, False, "KIS auth timeout or network error") for symbol in normalized),
            api_flags=("api_timeout",),
            read_call_count=1,
            budget_evidence=_kis_budget_evidence(
                read_call_count=1,
                quote_call_count=0,
                call_timestamps=tuple(call_timestamps),
                api_flags=("api_timeout",),
                source=f"kis-daily-bars-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )
    if not token:
        diagnostic = _kis_diagnostic(
            probe_name=kis_profile.auth_probe_name,
            http_status=token_response.status_code if token_response else None,
            payload=token_response.payload if token_response else {},
            expected_fields=("access_token",),
        )
        _write_auth_cooldown(
            auth_cooldown_path,
            profile=kis_profile.name,
            flag=str((diagnostic["flags"] or ["api_auth_error"])[0]),
            reason=str(diagnostic["reason"]),
        )
        return KisDailyBarsResult(
            status="failed",
            mode=f"network-read-only-daily-bars-{kis_profile.name}",
            symbol_count=len(normalized),
            start_date=start_date,
            end_date=end_date,
            included_symbols=(),
            excluded_symbols=tuple((symbol, f"missing KIS {kis_profile.name} token") for symbol in normalized),
            members=tuple(KisDailyBarsMember(symbol, False, f"missing KIS {kis_profile.name} token") for symbol in normalized),
            api_flags=tuple(diagnostic["flags"]),
            read_call_count=1,
            budget_evidence=_kis_budget_evidence(
                read_call_count=1,
                quote_call_count=0,
                call_timestamps=tuple(call_timestamps),
                api_flags=tuple(diagnostic["flags"]),
                source=f"kis-daily-bars-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )

    members: list[KisDailyBarsMember] = []
    flags: list[str] = []
    read_call_count = 1
    _clear_auth_cooldown(auth_cooldown_path, profile=kis_profile.name)
    for symbol in normalized:
        if quote_interval_seconds:
            time.sleep(quote_interval_seconds)
        try:
            read_call_count += 1
            call_timestamps.append(datetime.now(timezone.utc))
            response = _kis_inquire_daily_itemchartprice(
                env,
                http,
                token=token,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                profile=kis_profile,
            )
        except (OSError, URLError):
            members.append(KisDailyBarsMember(symbol, False, "api timeout or network error"))
            flags.append("api_timeout")
            continue
        output_rows = response.payload.get("output2")
        diagnostic = _kis_diagnostic(
            probe_name=f"{kis_profile.market_data_probe_name}-daily-bars",
            http_status=response.status_code,
            payload=response.payload,
            expected_fields=("output2",),
        )
        flags.extend(diagnostic["flags"])
        rows, row_flags = _parse_kis_daily_bar_rows(symbol, output_rows, start_date=start_date, end_date=end_date)
        flags.extend(row_flags)
        trading_dates = [row.trading_date for row in rows]
        unique_trading_dates = set(trading_dates)
        duplicate_dates = len(unique_trading_dates) != len(trading_dates)
        latest_prior_date = max(unique_trading_dates, default=None)
        source_fresh = latest_prior_date == end_date
        enough_rows = len(unique_trading_dates) >= min_trading_days
        date_flags: list[str] = []
        if duplicate_dates:
            date_flags.append("daily_bar_duplicate_date")
        if rows and not source_fresh:
            date_flags.append("daily_bar_latest_prior_mismatch")
        row_flags = tuple(dict.fromkeys((*row_flags, *date_flags)))
        flags.extend(date_flags)
        included = (
            response.status_code == 200
            and str(response.payload.get("rt_cd", "")) == "0"
            and bool(rows)
            and enough_rows
            and source_fresh
            and not duplicate_dates
            and not row_flags
        )
        reason = (
            "read-only daily bars ok"
            if included
            else f"insufficient KIS daily rows: {len(rows)} < {min_trading_days}"
            if rows and not enough_rows
            else f"latest KIS daily date {latest_prior_date.isoformat()} != expected {end_date.isoformat()}"
            if rows and not source_fresh and latest_prior_date is not None
            else "duplicate KIS daily trading dates"
            if duplicate_dates
            else diagnostic["reason"]
            if not rows
            else "daily bar schema mismatch"
        )
        members.append(KisDailyBarsMember(symbol, included, reason, rows=tuple(rows), field_data_flags=tuple(row_flags)))

    included_symbols = tuple(member.symbol for member in members if member.included)
    excluded_symbols = tuple((member.symbol, member.reason) for member in members if not member.included)
    unique_flags = tuple(dict.fromkeys(flags))
    latest_dates = [
        max((row.trading_date for row in member.rows), default=None)
        for member in members
        if member.rows
    ]
    result_latest_prior_date = max((item for item in latest_dates if item is not None), default=None)
    return KisDailyBarsResult(
        status="passed" if included_symbols and not unique_flags else "degraded" if included_symbols else "failed",
        mode=f"network-read-only-daily-bars-{kis_profile.name}",
        symbol_count=len(normalized),
        start_date=start_date,
        end_date=end_date,
        included_symbols=included_symbols,
        excluded_symbols=excluded_symbols,
        members=tuple(members),
        api_flags=unique_flags,
        read_call_count=read_call_count,
        budget_evidence=_kis_budget_evidence(
            read_call_count=read_call_count,
            quote_call_count=len(normalized),
            quote_interval_seconds=quote_interval_seconds,
            call_timestamps=tuple(call_timestamps),
            api_flags=unique_flags,
            source=f"kis-daily-bars-{kis_profile.name}",
        ),
        safety_boundary=safety_boundary,
        latest_prior_date=result_latest_prior_date,
        source_fresh=bool(result_latest_prior_date == end_date and included_symbols and not unique_flags),
    )


def build_kis_read_only_depth(
    *,
    symbols: tuple[str, ...],
    environ: dict[str, str] | None = None,
    client: JsonHttpClient | None = None,
    quote_interval_seconds: float = 0.0,
    endpoint_profile: str = "paper",
    auth_cooldown_path: Path | None = None,
    confirm_prod_readonly: bool = False,
    paired_price_report: dict[str, Any] | None = None,
) -> KisReadOnlyDepthResult:
    if quote_interval_seconds < 0:
        raise ValueError("quote_interval_seconds must be non-negative")
    kis_profile = _kis_endpoint_profile(endpoint_profile)
    if kis_profile.name == "prod" and not confirm_prod_readonly:
        raise ValueError("prod read-only KIS access requires confirm_prod_readonly=True")
    normalized = _normalize_symbols(symbols)
    env = environ if environ is not None else os.environ
    http = client or JsonHttpClient()
    safety_boundary = (
        "read-only KIS quote-depth universe; no broker order, account, balance, or real-fill calls"
    )
    if not normalized:
        return KisReadOnlyDepthResult(
            status="failed",
            mode=f"network-read-only-depth-{kis_profile.name}",
            universe_id="kis-readonly-depth",
            symbol_count=0,
            included_symbols=(),
            excluded_symbols=(),
            members=(),
            api_flags=("api_command_error",),
            read_call_count=0,
            budget_evidence=_kis_budget_evidence(
                read_call_count=0,
                quote_call_count=0,
                api_flags=("api_command_error",),
                source=f"kis-readonly-depth-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )
    missing = _missing(env, (kis_profile.app_key_env, kis_profile.app_secret_env))
    if missing:
        return KisReadOnlyDepthResult(
            status="failed",
            mode=f"network-read-only-depth-{kis_profile.name}",
            universe_id="kis-readonly-depth",
            symbol_count=len(normalized),
            included_symbols=(),
            excluded_symbols=tuple((symbol, f"missing KIS {kis_profile.name} auth") for symbol in normalized),
            members=tuple(KisQuoteDepthMember(symbol, False, f"missing KIS {kis_profile.name} auth") for symbol in normalized),
            api_flags=("api_auth_error",),
            read_call_count=0,
            budget_evidence=_kis_budget_evidence(
                read_call_count=0,
                quote_call_count=0,
                api_flags=("api_auth_error",),
                source=f"kis-readonly-depth-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )

    token_cache = KisTokenCache(
        app_key=env[kis_profile.app_key_env],
        app_secret=env[kis_profile.app_secret_env],
        client=http,
        base_url=kis_profile.base_url,
    )
    cooldown = _read_auth_cooldown(auth_cooldown_path, profile=kis_profile.name)
    if cooldown is not None:
        flag = str(cooldown.get("flag") or "api_auth_cooldown")
        reason = str(cooldown.get("reason") or "prior KIS auth failure")
        return KisReadOnlyDepthResult(
            status="failed",
            mode=f"network-read-only-depth-{kis_profile.name}",
            universe_id="kis-readonly-depth",
            symbol_count=len(normalized),
            included_symbols=(),
            excluded_symbols=tuple((symbol, f"KIS auth cooldown after {reason}") for symbol in normalized),
            members=tuple(KisQuoteDepthMember(symbol, False, f"KIS auth cooldown after {reason}") for symbol in normalized),
            api_flags=(flag,),
            read_call_count=0,
            budget_evidence=_kis_budget_evidence(
                read_call_count=0,
                quote_call_count=0,
                api_flags=(flag,),
                source=f"kis-readonly-depth-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )
    try:
        call_timestamps: list[datetime] = [datetime.now(timezone.utc)]
        token, _, auth_response = token_cache.get_token()
    except (OSError, URLError):
        _write_auth_cooldown(auth_cooldown_path, profile=kis_profile.name, flag="api_timeout", reason="auth timeout or network error")
        return KisReadOnlyDepthResult(
            status="failed",
            mode=f"network-read-only-depth-{kis_profile.name}",
            universe_id="kis-readonly-depth",
            symbol_count=len(normalized),
            included_symbols=(),
            excluded_symbols=tuple((symbol, "KIS auth timeout or network error") for symbol in normalized),
            members=tuple(KisQuoteDepthMember(symbol, False, "KIS auth timeout or network error") for symbol in normalized),
            api_flags=("api_timeout",),
            read_call_count=1,
            budget_evidence=_kis_budget_evidence(
                read_call_count=1,
                quote_call_count=0,
                call_timestamps=tuple(call_timestamps),
                api_flags=("api_timeout",),
                source=f"kis-readonly-depth-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )
    if not token:
        reason = "KIS auth cooldown active" if auth_response and auth_response.payload.get("auth_cooldown") else "KIS auth failed"
        _write_auth_cooldown(auth_cooldown_path, profile=kis_profile.name, flag="api_auth_error", reason=reason)
        return KisReadOnlyDepthResult(
            status="failed",
            mode=f"network-read-only-depth-{kis_profile.name}",
            universe_id="kis-readonly-depth",
            symbol_count=len(normalized),
            included_symbols=(),
            excluded_symbols=tuple((symbol, reason) for symbol in normalized),
            members=tuple(KisQuoteDepthMember(symbol, False, reason) for symbol in normalized),
            api_flags=("api_auth_error",),
            read_call_count=1,
            budget_evidence=_kis_budget_evidence(
                read_call_count=1,
                quote_call_count=0,
                api_flags=("api_auth_error",),
                source=f"kis-readonly-depth-{kis_profile.name}",
            ),
            safety_boundary=safety_boundary,
        )

    members: list[KisQuoteDepthMember] = []
    _clear_auth_cooldown(auth_cooldown_path, profile=kis_profile.name)
    flags: list[str] = []
    read_call_count = 1
    for symbol in normalized:
        if quote_interval_seconds:
            time.sleep(quote_interval_seconds)
        try:
            read_call_count += 1
            call_timestamps.append(datetime.now(timezone.utc))
            response = _kis_inquire_asking_price_exp_ccn(env, http, token=token, symbol=symbol, profile=kis_profile)
        except (OSError, URLError):
            members.append(KisQuoteDepthMember(symbol, False, "api timeout or network error"))
            flags.append("api_timeout")
            continue
        output = response.payload.get("output1") or response.payload.get("output") or {}
        observed_at = datetime.now(timezone.utc).isoformat()
        ask_volume = _first_output_value(output, "total_askp_rsqn", "askp_rsqn", "askp_rsqn1")
        bid_volume = _first_output_value(output, "total_bidp_rsqn", "bidp_rsqn", "bidp_rsqn1")
        bid_ask_ratio = _bid_ask_ratio(bid_volume, ask_volume)
        diagnostic = _kis_diagnostic(
            probe_name=f"{kis_profile.market_data_probe_name}-depth",
            http_status=response.status_code,
            payload=response.payload,
            expected_fields=("output1",),
        )
        flags.extend(diagnostic["flags"])
        included = response.status_code == 200 and str(response.payload.get("rt_cd", "")) == "0" and bool(bid_ask_ratio)
        field_data_flags = () if bid_ask_ratio else ("bid_ask_placeholder",)
        if included:
            flags.extend(field_data_flags)
        members.append(
            KisQuoteDepthMember(
                symbol=symbol,
                included=included,
                reason="read-only quote-depth ok" if included else diagnostic["reason"],
                observed_at=observed_at,
                ask_volume=ask_volume,
                bid_volume=bid_volume,
                bid_ask_ratio=bid_ask_ratio,
                field_data_flags=field_data_flags,
            )
        )

    included_symbols = tuple(member.symbol for member in members if member.included)
    excluded_symbols = tuple((member.symbol, member.reason) for member in members if not member.included)
    unique_flags = tuple(dict.fromkeys(flags))
    return KisReadOnlyDepthResult(
        status="passed" if included_symbols and not unique_flags else "degraded" if included_symbols else "failed",
        mode=f"network-read-only-depth-{kis_profile.name}",
        universe_id="kis-readonly-depth",
        symbol_count=len(normalized),
        included_symbols=included_symbols,
        excluded_symbols=excluded_symbols,
        members=tuple(members),
        api_flags=unique_flags,
        read_call_count=read_call_count,
        budget_evidence=_kis_budget_evidence(
            read_call_count=read_call_count,
            quote_call_count=len(normalized),
            call_timestamps=tuple(call_timestamps),
            api_flags=unique_flags,
            source=f"kis-readonly-depth-{kis_profile.name}",
        ),
        safety_boundary=safety_boundary,
        paired_snapshot_evidence=_paired_snapshot_evidence(tuple(members), paired_price_report),
    )


def _first_output_value(output: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = output.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _bid_ask_ratio(bid_volume: str, ask_volume: str) -> str:
    try:
        bid = Decimal(str(bid_volume or "0"))
        ask = Decimal(str(ask_volume or "0"))
    except Exception:
        return ""
    if bid < 0 or ask < 0:
        return ""
    if ask == 0:
        return ""
    if bid == 0:
        return "0.000000"
    return str((bid / ask).quantize(Decimal("0.000001")))


def _kis_field_data_flags(
    output: dict[str, Any],
    *,
    price: str,
    bid_ask_ratio: str,
) -> tuple[str, ...]:
    flags: list[str] = []
    required = {
        "stck_prpr": price,
        "stck_oprc": output.get("stck_oprc"),
        "stck_hgpr": output.get("stck_hgpr"),
        "stck_lwpr": output.get("stck_lwpr"),
        "acml_vol": output.get("acml_vol"),
        "acml_tr_pbmn": output.get("acml_tr_pbmn"),
    }
    missing = [key for key, value in required.items() if value in (None, "")]
    if missing:
        flags.append("field_data_incomplete:" + ",".join(missing))
    if not bid_ask_ratio:
        flags.append("bid_ask_placeholder")
    return tuple(flags)


def _paired_snapshot_evidence(
    depth_members: tuple[KisQuoteDepthMember, ...],
    paired_price_report: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not paired_price_report:
        return None
    price_observed_at = {
        str(member.get("symbol")): str(member.get("observed_at") or "")
        for member in paired_price_report.get("members", [])
        if isinstance(member, dict)
    }
    gaps: list[float] = []
    missing = 0
    for member in depth_members:
        if not member.observed_at:
            missing += 1
            continue
        price_at = price_observed_at.get(member.symbol, "")
        if not price_at:
            missing += 1
            continue
        try:
            depth_at = datetime.fromisoformat(member.observed_at.replace("Z", "+00:00"))
            parsed_price_at = datetime.fromisoformat(price_at.replace("Z", "+00:00"))
        except ValueError:
            missing += 1
            continue
        gaps.append(abs((depth_at - parsed_price_at).total_seconds()))
    max_gap = max(gaps) if gaps else None
    return {
        "source": "paired-price-report",
        "paired_count": len(gaps),
        "missing_pair_count": missing,
        "max_gap_seconds": max_gap,
        "fresh_pairing": max_gap is not None and max_gap <= 30 and missing == 0,
        "note": "Parallel quote-depth and price snapshots are diagnostic unless timestamp gaps are accepted.",
    }


def _kis_budget_evidence(
    *,
    read_call_count: int,
    quote_call_count: int,
    quote_interval_seconds: float = 0.0,
    call_timestamps: tuple[datetime, ...] = (),
    api_flags: tuple[str, ...],
    source: str,
    observed_latency_ms: int | None = None,
) -> dict[str, Any]:
    observed_at = call_timestamps[-1] if call_timestamps else datetime.now(timezone.utc)
    return build_read_call_budget_evidence(
        measured_read_calls=read_call_count,
        measured_peak_per_second=(
            _observed_peak_per_second(call_timestamps)
            if call_timestamps
            else _scheduled_peak_per_second(
                read_call_count=read_call_count,
                quote_call_count=quote_call_count,
                quote_interval_seconds=quote_interval_seconds,
            )
        ),
        observed_at=normalize_to_kst(observed_at),
        source=source,
        observed_latency_ms=observed_latency_ms,
        api_flags=api_flags,
    ).as_dict()


def _scheduled_peak_per_second(
    *,
    read_call_count: int,
    quote_call_count: int,
    quote_interval_seconds: float,
) -> int:
    if read_call_count <= 0:
        return 0
    if quote_call_count <= 0:
        return read_call_count
    if quote_interval_seconds <= 0:
        return read_call_count
    return min(read_call_count, max(1, ceil(1 / quote_interval_seconds)))


def _observed_peak_per_second(call_timestamps: tuple[datetime, ...]) -> int:
    if not call_timestamps:
        return 0
    offsets = sorted(timestamp.timestamp() for timestamp in call_timestamps)
    peak = 1
    right = 0
    for left, start in enumerate(offsets):
        while right < len(offsets) and offsets[right] - start < 1.0:
            right += 1
        peak = max(peak, right - left)
    return peak


def _read_auth_cooldown(path: Path | None, *, profile: str) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        item = payload.get(profile) or {}
        recorded_at = datetime.fromisoformat(str(item.get("recorded_at")))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - recorded_at >= timedelta(minutes=1):
        return None
    item["reason"] = _sanitize_auth_cooldown_reason(
        flag=str(item.get("flag") or "api_auth_cooldown"),
        reason=str(item.get("reason") or ""),
    )
    return item


def _write_auth_cooldown(path: Path | None, *, profile: str, flag: str, reason: str) -> None:
    if path is None:
        return
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    payload[profile] = {
        "flag": flag,
        "reason": _sanitize_auth_cooldown_reason(flag=flag, reason=reason),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sanitize_auth_cooldown_reason(*, flag: str, reason: str) -> str:
    normalized_flag = flag.strip().lower()
    normalized_reason = reason.strip().lower()
    if "timeout" in normalized_flag or "timeout" in normalized_reason or "network" in normalized_reason:
        return "auth timeout or network error"
    if "rate" in normalized_flag or "throttle" in normalized_reason or "limit" in normalized_reason:
        return "auth rate limit"
    if "schema" in normalized_flag or "schema" in normalized_reason or "missing" in normalized_reason:
        return "auth schema mismatch"
    if "expired" in normalized_reason:
        return "auth token expired immediately"
    if "auth" in normalized_flag:
        return "auth error"
    return "auth failure"


def _clear_auth_cooldown(path: Path | None, *, profile: str) -> None:
    if path is None or not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if profile not in payload:
        return
    del payload[profile]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _run_kis_paper_probes(
    env: dict[str, str],
    client: JsonHttpClient,
    *,
    symbol: str,
    auth_cooldown_path: Path | None = None,
) -> list[ApiSmokeResult]:
    missing = _missing(env, ("KIS_PAPER_APP_KEY", "KIS_PAPER_APP_SECRET"))
    if missing:
        skipped = ApiSmokeResult("kis-paper-auth", "skipped", message="missing environment", detail={"missing_env": missing})
        return [skipped, ApiSmokeResult("kis-paper-market-data", "skipped", message="missing KIS paper auth")]
    cooldown = _read_auth_cooldown(auth_cooldown_path, profile="paper")
    if cooldown is not None:
        flag = str(cooldown.get("flag") or "api_auth_cooldown")
        reason = str(cooldown.get("reason") or "prior KIS paper auth failure")
        auth_result = ApiSmokeResult(
            "kis-paper-auth",
            "failed",
            message=f"KIS auth cooldown after {reason}",
            diagnostics={"flags": [flag], "reason": reason},
        )
        return [auth_result, ApiSmokeResult("kis-paper-market-data", "skipped", message="missing KIS paper token")]

    token_cache = KisTokenCache(
        app_key=env["KIS_PAPER_APP_KEY"],
        app_secret=env["KIS_PAPER_APP_SECRET"],
        client=client,
        base_url=KIS_PAPER_BASE_URL,
    )
    try:
        token, from_cache, token_response = token_cache.get_token()
    except (OSError, URLError) as exc:
        _write_auth_cooldown(
            auth_cooldown_path,
            profile="paper",
            flag="api_timeout",
            reason="auth timeout or network error",
        )
        auth_result = ApiSmokeResult(
            "kis-paper-auth",
            "failed",
            message=_safe_message(exc),
            diagnostics={"flags": ["api_timeout"], "reason": "KIS auth timeout or network error"},
        )
        return [auth_result, ApiSmokeResult("kis-paper-market-data", "skipped", message="missing KIS paper token")]
    auth_diagnostic = _kis_diagnostic(
        probe_name="kis-paper-auth",
        http_status=token_response.status_code if token_response else None,
        payload=token_response.payload if token_response else {},
        expected_fields=("access_token",),
    )
    auth_result = ApiSmokeResult(
        "kis-paper-auth",
        "passed" if token else "failed",
        http_status=token_response.status_code if token_response else None,
        message="" if token else _kis_message(token_response.payload if token_response else {}),
        detail={"token_present": bool(token), "from_cache": from_cache},
        diagnostics=auth_diagnostic,
    )
    if not token:
        _write_auth_cooldown(
            auth_cooldown_path,
            profile="paper",
            flag=str((auth_diagnostic["flags"] or ["api_auth_error"])[0]),
            reason=str(auth_diagnostic["reason"]),
        )
        return [auth_result, ApiSmokeResult("kis-paper-market-data", "skipped", message="missing KIS paper token")]
    _clear_auth_cooldown(auth_cooldown_path, profile="paper")

    try:
        price_response = _kis_inquire_price(
            env,
            client,
            token=token,
            symbol=symbol,
            profile=KIS_ENDPOINT_PROFILES["paper"],
        )
    except (OSError, URLError) as exc:
        return [
            auth_result,
            ApiSmokeResult(
                "kis-paper-market-data",
                "failed",
                message=_safe_message(exc),
                diagnostics={"flags": ["api_timeout"], "reason": "network or timeout error"},
            ),
        ]
    output = price_response.payload.get("output") or {}
    rt_cd = str(price_response.payload.get("rt_cd", ""))
    diagnostics = _kis_diagnostic(
        probe_name="kis-paper-market-data",
        http_status=price_response.status_code,
        payload=price_response.payload,
        expected_fields=("output.stck_prpr",),
    )
    return [
        auth_result,
        ApiSmokeResult(
            "kis-paper-market-data",
            "passed" if price_response.status_code == 200 and rt_cd == "0" and bool(output.get("stck_prpr")) else "failed",
            http_status=price_response.status_code,
            message=_kis_message(price_response.payload),
            detail={"rt_cd": rt_cd, "price_present": bool(output.get("stck_prpr")), "symbol": symbol},
            diagnostics=diagnostics,
        ),
    ]


def _kis_inquire_price(
    env: dict[str, str],
    client: JsonHttpClient,
    *,
    token: str,
    symbol: str,
    profile: KisEndpointProfile,
) -> JsonHttpResponse:
    query = urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol})
    return client.get_json(
        f"{profile.base_url}/uapi/domestic-stock/v1/quotations/inquire-price?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "appkey": env[profile.app_key_env],
            "appsecret": env[profile.app_secret_env],
            "tr_id": "FHKST01010100",
            "custtype": "P",
        },
    )


def _kis_inquire_daily_itemchartprice(
    env: dict[str, str],
    client: JsonHttpClient,
    *,
    token: str,
    symbol: str,
    start_date: date,
    end_date: date,
    profile: KisEndpointProfile,
) -> JsonHttpResponse:
    query = urlencode(
        {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_DATE_1": start_date.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": end_date.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "1",
        }
    )
    return client.get_json(
        f"{profile.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "appkey": env[profile.app_key_env],
            "appsecret": env[profile.app_secret_env],
            "tr_id": "FHKST03010100",
            "custtype": "P",
        },
    )


def _kis_chk_holiday(
    env: dict[str, str],
    client: JsonHttpClient,
    *,
    token: str,
    base_date: date,
    profile: KisEndpointProfile,
) -> JsonHttpResponse:
    query = urlencode({"BASS_DT": base_date.strftime("%Y%m%d"), "CTX_AREA_FK": "", "CTX_AREA_NK": ""})
    return client.get_json(
        f"{profile.base_url}/uapi/domestic-stock/v1/quotations/chk-holiday?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "appkey": env[profile.app_key_env],
            "appsecret": env[profile.app_secret_env],
            "tr_id": "CTCA0903R",
            "custtype": "P",
        },
    )


def _kis_inquire_asking_price_exp_ccn(
    env: dict[str, str],
    client: JsonHttpClient,
    *,
    token: str,
    symbol: str,
    profile: KisEndpointProfile,
) -> JsonHttpResponse:
    query = urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol})
    return client.get_json(
        f"{profile.base_url}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "appkey": env[profile.app_key_env],
            "appsecret": env[profile.app_secret_env],
            "tr_id": "FHKST01010200",
            "custtype": "P",
        },
    )


def _parse_kis_daily_bar_rows(
    symbol: str,
    output_rows: object,
    *,
    start_date: date,
    end_date: date,
) -> tuple[list[KisDailyBar], tuple[str, ...]]:
    if not isinstance(output_rows, list):
        return [], ("daily_bar_output2_not_list",)
    rows: list[KisDailyBar] = []
    flags: list[str] = []
    required_fields = (
        "stck_bsop_date",
        "stck_oprc",
        "stck_hgpr",
        "stck_lwpr",
        "stck_clpr",
        "acml_vol",
        "acml_tr_pbmn",
    )
    for raw in output_rows:
        if not isinstance(raw, dict):
            flags.append("daily_bar_row_not_object")
            continue
        missing = [field for field in required_fields if raw.get(field) in (None, "")]
        if missing:
            flags.append("daily_bar_field_incomplete:" + ",".join(missing))
            continue
        try:
            trading_date = datetime.strptime(str(raw["stck_bsop_date"]), "%Y%m%d").date()
            open_ = _positive_decimal_string(raw["stck_oprc"])
            high = _positive_decimal_string(raw["stck_hgpr"])
            low = _positive_decimal_string(raw["stck_lwpr"])
            close = _positive_decimal_string(raw["stck_clpr"])
            volume = str(int(str(raw["acml_vol"])))
            traded_value = _non_negative_decimal_string(raw["acml_tr_pbmn"])
        except (ValueError, ArithmeticError) as exc:
            flags.append(f"daily_bar_invalid_value:{type(exc).__name__}")
            continue
        if trading_date < start_date or trading_date > end_date:
            flags.append("daily_bar_out_of_range")
            continue
        rows.append(
            KisDailyBar(
                symbol=symbol,
                trading_date=trading_date,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                traded_value=traded_value,
            )
        )
    rows.sort(key=lambda item: item.trading_date)
    return rows, tuple(dict.fromkeys(flags))


def _parse_kis_holiday_rows(output_rows: object) -> tuple[list[KisHolidayRow], tuple[str, ...]]:
    if not isinstance(output_rows, list):
        return [], ("holiday_calendar_output_not_list",)
    rows: list[KisHolidayRow] = []
    flags: list[str] = []
    required_fields = ("bass_dt", "wday_dvsn_cd", "bzdy_yn", "tr_day_yn", "opnd_yn", "sttl_day_yn")
    for raw in output_rows:
        if not isinstance(raw, dict):
            flags.append("holiday_calendar_row_not_object")
            continue
        missing = [field for field in required_fields if raw.get(field) in (None, "")]
        if missing:
            flags.append("holiday_calendar_field_incomplete:" + ",".join(missing))
            continue
        try:
            bass_dt = datetime.strptime(str(raw["bass_dt"]), "%Y%m%d").date()
        except ValueError:
            flags.append("holiday_calendar_invalid_date")
            continue
        rows.append(
            KisHolidayRow(
                bass_dt=bass_dt,
                wday_dvsn_cd=str(raw["wday_dvsn_cd"]),
                bzdy_yn=str(raw["bzdy_yn"]).upper(),
                tr_day_yn=str(raw["tr_day_yn"]).upper(),
                opnd_yn=str(raw["opnd_yn"]).upper(),
                sttl_day_yn=str(raw["sttl_day_yn"]).upper(),
            )
        )
    return rows, tuple(dict.fromkeys(flags))


def _positive_decimal_string(value: object) -> str:
    parsed = Decimal(str(value))
    if parsed <= 0:
        raise ValueError("value must be positive")
    return str(parsed)


def _non_negative_decimal_string(value: object) -> str:
    parsed = Decimal(str(value))
    if parsed < 0:
        raise ValueError("value must be non-negative")
    return str(parsed)


def _validate_date_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")


def _kis_endpoint_profile(name: str) -> KisEndpointProfile:
    try:
        return KIS_ENDPOINT_PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown KIS endpoint profile: {name}") from exc


def _kis_diagnostic(
    *,
    probe_name: str,
    http_status: int | None,
    payload: dict[str, Any],
    expected_fields: tuple[str, ...],
) -> dict[str, Any]:
    flags: list[str] = []
    rt_cd = str(payload.get("rt_cd", ""))
    raw_message = _raw_kis_message(payload)
    message = _sanitize_external_api_message(raw_message)
    if payload.get("auth_cooldown"):
        flags.append("api_auth_cooldown")
    elif http_status in {401, 403}:
        flags.append("api_auth_error")
    elif http_status == 429:
        flags.append("api_rate_limit_risk")
    elif http_status is not None and http_status >= 400:
        flags.append("api_rate_limit_risk" if _looks_like_rate_limit(message) else "api_command_error")
    if rt_cd and rt_cd != "0":
        flags.append("api_rate_limit_risk" if _looks_like_rate_limit(message) else "api_command_error")
    missing_fields = [field for field in expected_fields if not _nested_present(payload, field)]
    if payload.get("token_expired_immediately") and "auth" in probe_name:
        flags.append("api_auth_error")
    elif http_status == 200 and rt_cd in {"", "0"} and missing_fields:
        if "auth" in probe_name and "access_token" in missing_fields:
            flags.append("api_auth_error")
        else:
            flags.append("api_schema_mismatch")
    if payload.get("auth_cooldown"):
        reason = "auth cooldown"
    elif not flags:
        reason = "ok"
    elif payload.get("token_expired_immediately") and "auth" in probe_name:
        reason = "auth mismatch: token expired immediately"
    elif "api_auth_error" in flags and message:
        reason = message
    elif "api_auth_error" in flags and "auth" in probe_name and "access_token" in missing_fields:
        reason = f"auth mismatch: missing {','.join(missing_fields)}"
    elif "api_schema_mismatch" in flags:
        reason = f"schema mismatch: missing {','.join(missing_fields)}"
    elif message:
        reason = message
    else:
        reason = f"{probe_name} returned unexpected response"
    return {
        "flags": list(dict.fromkeys(flags)),
        "reason": reason,
        "rt_cd": rt_cd,
        "missing_fields": missing_fields,
    }


def _looks_like_rate_limit(message: str) -> bool:
    normalized = message.lower()
    return any(token in normalized for token in ("rate limit", "too many", "초당", "거래건수", "호출"))


def _api_flags(results: list[ApiSmokeResult]) -> list[str]:
    flags: list[str] = []
    for result in results:
        if result.diagnostics:
            flags.extend(str(flag) for flag in result.diagnostics.get("flags", []))
    return list(dict.fromkeys(flags))


def _nested_present(payload: dict[str, Any], dotted_path: str) -> bool:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or not current.get(part):
            return False
        current = current[part]
    return True


def _normalize_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in symbols:
        symbol = str(item).strip()
        if not symbol:
            continue
        if symbol.startswith("A") and len(symbol) == 7:
            symbol = symbol[1:]
        if not (len(symbol) == 6 and symbol.isdigit()):
            raise ValueError(f"invalid KIS stock symbol: {item}")
        normalized.append(symbol.zfill(6))
    return tuple(dict.fromkeys(normalized))


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


def _raw_kis_message(payload: dict[str, Any]) -> str:
    return str(payload.get("msg1") or payload.get("error_description") or payload.get("message") or "")[:200]


def _kis_message(payload: dict[str, Any]) -> str:
    return _sanitize_external_api_message(_raw_kis_message(payload))


def _sanitize_external_api_message(message: str) -> str:
    normalized = message.strip().lower()
    if not normalized:
        return ""
    if _looks_like_rate_limit(normalized):
        return "api rate limit"
    if "timeout" in normalized or "timed out" in normalized:
        return "api timeout"
    if "schema" in normalized or "missing" in normalized:
        return "api schema mismatch"
    if "auth" in normalized or "app_key" in normalized or "appkey" in normalized or "appsecret" in normalized:
        return "api auth error"
    return "api provider error"


def _kis_token_expiry(payload: dict[str, Any], now: datetime) -> datetime:
    raw_expires_in = payload.get("expires_in", 3600)
    try:
        expires_in = int(raw_expires_in)
    except (TypeError, ValueError):
        expires_in = 0
    return now + timedelta(seconds=max(0, expires_in - 60))
