from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode

from zurini.api_budget import build_read_call_budget_evidence, normalize_to_kst
from zurini.api_smoke import (
    JsonHttpClient,
    JsonHttpResponse,
    KisEndpointProfile,
    KisTokenCache,
    _kis_diagnostic,
    _kis_endpoint_profile,
    _missing,
    _read_auth_cooldown,
    _write_auth_cooldown,
)
from zurini.market import Bar


KIS_INDEX_CODES: dict[str, str] = {
    "KOSPI": "0001",
    "KOSDAQ": "1001",
}
INDEX_POLL_SOURCE = "kis-index-poll-10s"


@dataclass(frozen=True)
class KisIndexSample:
    index_code: str
    timestamp: datetime
    price: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    volume: int = 0
    source: str = INDEX_POLL_SOURCE

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        for key in ("price", "open", "high", "low"):
            payload[key] = str(payload[key])
        return payload


@dataclass(frozen=True)
class KisIndexPollResult:
    status: str
    mode: str
    samples: tuple[KisIndexSample, ...]
    bars: tuple[Bar, ...]
    api_flags: tuple[str, ...]
    read_call_count: int
    budget_evidence: dict[str, Any]
    safety_boundary: str
    ready_for_broker_or_order_transmission: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "samples": [sample.as_dict() for sample in self.samples],
            "bars": [_bar_as_dict(bar) for bar in self.bars],
            "api_flags": list(self.api_flags),
            "read_call_count": self.read_call_count,
            "budget_evidence": self.budget_evidence,
            "safety_boundary": self.safety_boundary,
            "ready_for_broker_or_order_transmission": self.ready_for_broker_or_order_transmission,
        }


def build_kis_index_poll_plan(
    *,
    index_codes: tuple[str, ...] = ("KOSPI", "KOSDAQ"),
    poll_interval_seconds: int = 10,
) -> dict[str, Any]:
    _validate_poll_interval(poll_interval_seconds)
    normalized = _normalize_index_codes(index_codes)
    return {
        "status": "ready" if normalized else "missing-index-codes",
        "mode": "network-disabled",
        "index_codes": list(normalized),
        "poll_interval_seconds": poll_interval_seconds,
        "estimated_read_calls_per_minute": int((60 / poll_interval_seconds) * len(normalized)),
        "ready_for_broker_or_order_transmission": False,
        "safety_boundary": _safety_boundary(),
    }


def build_kis_index_poll_snapshot(
    *,
    index_codes: tuple[str, ...] = ("KOSPI", "KOSDAQ"),
    poll_interval_seconds: int = 10,
    environ: dict[str, str] | None = None,
    client: JsonHttpClient | None = None,
    endpoint_profile: str = "paper",
    auth_cooldown_path: Path | None = None,
    confirm_prod_readonly: bool = False,
    token_cache: KisTokenCache | None = None,
    now: datetime | None = None,
) -> KisIndexPollResult:
    _validate_poll_interval(poll_interval_seconds)
    normalized_codes = _normalize_index_codes(index_codes)
    observed_at = normalize_to_kst(now or datetime.now().astimezone())
    profile = _kis_endpoint_profile(endpoint_profile)
    if profile.name == "prod" and not confirm_prod_readonly:
        raise ValueError("prod read-only KIS index polling requires confirm_prod_readonly=True")

    env = environ if environ is not None else os.environ
    http = client or JsonHttpClient()
    missing = _missing(env, (profile.app_key_env, profile.app_secret_env))
    if not normalized_codes or missing:
        flags = ("missing_index_codes",) if not normalized_codes else ("api_auth_error",)
        return _empty_result(
            status="failed",
            mode=f"network-read-only-index-poll-{profile.name}",
            observed_at=observed_at,
            api_flags=flags,
        )

    token_cache = token_cache or KisTokenCache(
        app_key=env[profile.app_key_env],
        app_secret=env[profile.app_secret_env],
        client=http,
        base_url=profile.base_url,
    )
    cooldown = _read_auth_cooldown(auth_cooldown_path, profile=profile.name)
    if cooldown is not None:
        return _empty_result(
            status="failed",
            mode=f"network-read-only-index-poll-{profile.name}",
            observed_at=observed_at,
            api_flags=(str(cooldown.get("flag") or "api_auth_cooldown"),),
        )

    try:
        token, _, token_response = token_cache.get_token()
    except (OSError, URLError):
        _write_auth_cooldown(
            auth_cooldown_path,
            profile=profile.name,
            flag="api_timeout",
            reason="index poll auth timeout or network error",
        )
        return _empty_result(
            status="failed",
            mode=f"network-read-only-index-poll-{profile.name}",
            observed_at=observed_at,
            api_flags=("api_timeout",),
            read_call_count=1,
        )
    if not token:
        diagnostic = _kis_diagnostic(
            probe_name=profile.auth_probe_name,
            http_status=token_response.status_code if token_response else None,
            payload=token_response.payload if token_response else {},
            expected_fields=("access_token",),
        )
        _write_auth_cooldown(
            auth_cooldown_path,
            profile=profile.name,
            flag=str((diagnostic["flags"] or ["api_auth_error"])[0]),
            reason=str(diagnostic["reason"]),
        )
        return _empty_result(
            status="failed",
            mode=f"network-read-only-index-poll-{profile.name}",
            observed_at=observed_at,
            api_flags=tuple(diagnostic["flags"]),
            read_call_count=1,
        )

    samples: list[KisIndexSample] = []
    flags: list[str] = []
    read_call_count = 1
    for code in normalized_codes:
        response = _kis_inquire_index_snapshot(
            env,
            http,
            token=token,
            index_code=code,
            observed_at=observed_at,
            profile=profile,
        )
        read_call_count += 1
        diagnostic = _kis_diagnostic(
            probe_name=f"{profile.market_data_probe_name}-index-{code}",
            http_status=response.status_code,
            payload=response.payload,
            expected_fields=("output",),
        )
        flags.extend(str(flag) for flag in diagnostic["flags"])
        sample, sample_flags = _sample_from_response(code, observed_at=observed_at, response=response)
        flags.extend(sample_flags)
        if sample is not None:
            samples.append(sample)

    missing_codes = set(normalized_codes) - {sample.index_code for sample in samples}
    flags.extend(f"missing_index:{code}" for code in sorted(missing_codes))
    unique_flags = tuple(dict.fromkeys(flag for flag in flags if flag))
    bars = aggregate_index_samples_to_minute_bars(tuple(samples))
    return KisIndexPollResult(
        status="passed" if len(samples) == len(normalized_codes) and not unique_flags else "failed",
        mode=f"network-read-only-index-poll-{profile.name}",
        samples=tuple(samples),
        bars=bars,
        api_flags=unique_flags,
        read_call_count=read_call_count,
        budget_evidence=build_read_call_budget_evidence(
            measured_read_calls=read_call_count,
            measured_peak_per_second=max(1, len(normalized_codes)),
            observed_at=observed_at,
            source=INDEX_POLL_SOURCE,
            api_flags=unique_flags,
        ).as_dict(),
        safety_boundary=_safety_boundary(),
    )


def aggregate_index_samples_to_minute_bars(samples: tuple[KisIndexSample, ...]) -> tuple[Bar, ...]:
    grouped: dict[tuple[str, datetime], list[KisIndexSample]] = {}
    for sample in sorted(samples, key=lambda item: (item.index_code, item.timestamp)):
        minute = sample.timestamp.replace(second=0, microsecond=0)
        grouped.setdefault((sample.index_code, minute), []).append(sample)

    bars: list[Bar] = []
    for (index_code, _minute), rows in sorted(grouped.items(), key=lambda item: item[0]):
        open_price = rows[0].price
        close_price = rows[-1].price
        high = max(row.price for row in rows)
        low = min(row.price for row in rows)
        bars.append(
            Bar(
                symbol=index_code,
                timestamp=rows[-1].timestamp,
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=sum(max(0, row.volume) for row in rows),
                value=Decimal("0"),
                source=INDEX_POLL_SOURCE,
            )
        )
    return tuple(bars)


def index_bars_from_report(payload: dict[str, Any]) -> tuple[Bar, ...]:
    bars: list[Bar] = []
    for row in payload.get("bars", []):
        if not isinstance(row, dict):
            continue
        bars.append(
            Bar(
                symbol=str(row.get("symbol") or row.get("index_code") or ""),
                timestamp=datetime.fromisoformat(str(row["timestamp"])),
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=int(row.get("volume") or 0),
                value=Decimal(str(row.get("value") or "0")),
                source=str(row.get("source") or INDEX_POLL_SOURCE),
            )
        )
    return tuple(bar for bar in bars if bar.symbol)


def index_samples_from_report(payload: dict[str, Any]) -> tuple[KisIndexSample, ...]:
    samples: list[KisIndexSample] = []
    for row in payload.get("samples", []):
        if not isinstance(row, dict):
            continue
        samples.append(
            KisIndexSample(
                index_code=str(row.get("index_code") or ""),
                timestamp=datetime.fromisoformat(str(row["timestamp"])),
                price=Decimal(str(row["price"])),
                open=Decimal(str(row.get("open") or row["price"])),
                high=Decimal(str(row.get("high") or row["price"])),
                low=Decimal(str(row.get("low") or row["price"])),
                volume=int(row.get("volume") or 0),
                source=str(row.get("source") or INDEX_POLL_SOURCE),
            )
        )
    return tuple(sample for sample in samples if sample.index_code)


def _kis_inquire_index_snapshot(
    env: dict[str, str],
    client: JsonHttpClient,
    *,
    token: str,
    index_code: str,
    observed_at: datetime,
    profile: KisEndpointProfile,
) -> JsonHttpResponse:
    kis_code = KIS_INDEX_CODES[index_code]
    query = urlencode(
        {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": kis_code,
            "FID_INPUT_HOUR_1": observed_at.strftime("%H%M%S"),
        }
    )
    return client.get_json(
        f"{profile.base_url}/uapi/domestic-stock/v1/quotations/inquire-index-tickprice?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "appkey": env[profile.app_key_env],
            "appsecret": env[profile.app_secret_env],
            "tr_id": "FHPUP02110000",
            "custtype": "P",
        },
    )


def _sample_from_response(
    index_code: str,
    *,
    observed_at: datetime,
    response: JsonHttpResponse,
) -> tuple[KisIndexSample | None, tuple[str, ...]]:
    row = _first_output_row(response.payload)
    if not row:
        return None, ("missing_index_output",)
    price = _decimal_field(row, "bstp_nmix_prpr", "stck_prpr", "prpr")
    open_price = _decimal_field(row, "bstp_nmix_oprc", "stck_oprc", default=price)
    high = _decimal_field(row, "bstp_nmix_hgpr", "stck_hgpr", default=price)
    low = _decimal_field(row, "bstp_nmix_lwpr", "stck_lwpr", default=price)
    volume = _int_field(row, "cntg_vol", "acml_vol")
    if price is None or open_price is None or high is None or low is None or price <= 0:
        return None, ("malformed_index_price",)
    return (
        KisIndexSample(
            index_code=index_code,
            timestamp=observed_at,
            price=price,
            open=open_price,
            high=max(high, price, open_price),
            low=min(low, price, open_price),
            volume=volume,
        ),
        (),
    )


def _first_output_row(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("output", "output1", "output2"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
    return {}


def _decimal_field(row: dict[str, Any], *names: str, default: Decimal | None = None) -> Decimal | None:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            try:
                return Decimal(str(value).replace(",", ""))
            except InvalidOperation:
                return None
    return default


def _int_field(row: dict[str, Any], *names: str) -> int:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            try:
                return int(Decimal(str(value).replace(",", "")))
            except (InvalidOperation, ValueError):
                return 0
    return 0


def _normalize_index_codes(index_codes: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for code in index_codes:
        item = code.strip().upper()
        if item in KIS_INDEX_CODES and item not in normalized:
            normalized.append(item)
    return tuple(normalized)


def _validate_poll_interval(poll_interval_seconds: int) -> None:
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    if poll_interval_seconds != 10:
        raise ValueError("current operating contract requires 10-second index polling")


def _empty_result(
    *,
    status: str,
    mode: str,
    observed_at: datetime,
    api_flags: tuple[str, ...],
    read_call_count: int = 0,
) -> KisIndexPollResult:
    return KisIndexPollResult(
        status=status,
        mode=mode,
        samples=(),
        bars=(),
        api_flags=api_flags,
        read_call_count=read_call_count,
        budget_evidence=build_read_call_budget_evidence(
            measured_read_calls=read_call_count,
            measured_peak_per_second=0,
            observed_at=observed_at,
            source=INDEX_POLL_SOURCE,
            api_flags=api_flags,
        ).as_dict(),
        safety_boundary=_safety_boundary(),
    )


def _bar_as_dict(bar: Bar) -> dict[str, Any]:
    return {
        "symbol": bar.symbol,
        "timestamp": bar.timestamp.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": bar.volume,
        "value": str(bar.value),
        "source": bar.source,
    }


def _safety_boundary() -> str:
    return "read-only KIS domestic index polling; no order, account, balance, or real-fill calls"
