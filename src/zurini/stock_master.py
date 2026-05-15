from __future__ import annotations

import io
import json
from collections import Counter
from dataclasses import asdict, dataclass
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

KIS_STOCK_MASTER_SOURCE = "kis-stock-master"

KIS_STOCK_MASTER_URLS: dict[str, str] = {
    "KOSPI": "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
    "KOSDAQ": "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
}

_KOSPI_WIDTHS = (
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
)
_KOSDAQ_WIDTHS = (
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
)

_MARKET_SPECS = {
    "KOSPI": {
        "suffix_len": sum(_KOSPI_WIDTHS),
        "widths": _KOSPI_WIDTHS,
        "file_name": "kospi_code.mst",
        "indexes": {
            "group": 0,
            "etp": 12,
            "elw": 13,
            "halt": 34,
            "liquidation": 35,
            "admin": 36,
            "warning": 37,
            "warning_preview": 38,
            "unfaithful": 39,
            "preferred": 54,
        },
    },
    "KOSDAQ": {
        "suffix_len": sum(_KOSDAQ_WIDTHS),
        "widths": _KOSDAQ_WIDTHS,
        "file_name": "kosdaq_code.mst",
        "indexes": {
            "group": 0,
            "etp": 8,
            "halt": 29,
            "liquidation": 30,
            "admin": 31,
            "warning": 32,
            "warning_preview": 33,
            "unfaithful": 34,
            "preferred": 49,
        },
    },
}


@dataclass(frozen=True)
class KisStockMasterEntry:
    symbol: str
    standard_code: str
    name: str
    market: str
    section_kind: str
    status_kind: str
    control_kind: str
    supervision_kind: str
    source: str = KIS_STOCK_MASTER_SOURCE
    included: bool = True
    reason: str = "candidate"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KisStockMasterResult:
    status: str
    mode: str
    collected_at: str
    source_files: dict[str, str]
    market_counts: dict[str, int]
    symbol_count: int
    included_symbols: tuple[str, ...]
    excluded_symbols: tuple[tuple[str, str], ...]
    members: tuple[KisStockMasterEntry, ...]
    api_flags: tuple[str, ...]
    duplicate_symbol_count: int
    safety_boundary: str
    ready_for_broker_or_order_transmission: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "included_symbols": list(self.included_symbols),
            "excluded_symbols": [list(item) for item in self.excluded_symbols],
            "members": [member.as_dict() for member in self.members],
        }


def build_kis_stock_master_plan(*, markets: tuple[str, ...] = ("KOSPI", "KOSDAQ")) -> dict[str, Any]:
    normalized_markets = _normalize_markets(markets)
    source_files = {market: KIS_STOCK_MASTER_URLS[market] for market in normalized_markets}
    return {
        "status": "ready" if normalized_markets else "missing-markets",
        "mode": "network-disabled",
        "markets": list(normalized_markets),
        "source_files": source_files,
        "ready_for_broker_or_order_transmission": False,
        "safety_boundary": _safety_boundary(),
    }


def build_kis_stock_master(
    *,
    markets: tuple[str, ...] = ("KOSPI", "KOSDAQ"),
    fetcher: Callable[[str], bytes] | None = None,
    now: datetime | None = None,
) -> KisStockMasterResult:
    normalized_markets = _normalize_markets(markets)
    collected_at = (now or datetime.now(timezone.utc)).isoformat()
    members: list[KisStockMasterEntry] = []
    flags: list[str] = []
    duplicate_symbol_count = 0
    source_files = {market: KIS_STOCK_MASTER_URLS[market] for market in normalized_markets}
    market_counts: dict[str, int] = {}
    if not normalized_markets:
        flags.append("stock_master_missing_markets")
    for market in normalized_markets:
        url = KIS_STOCK_MASTER_URLS[market]
        try:
            payload = fetcher(url) if fetcher is not None else _fetch_bytes(url)
            market_members = _parse_kis_stock_master_zip(payload, market=market)
        except (OSError, URLError):
            flags.append(f"{market.lower()}_stock_master_network_error")
            market_members = ()
        except (BadZipFile, UnicodeDecodeError, ValueError):
            flags.append(f"{market.lower()}_stock_master_malformed")
            market_members = ()
        market_counts[market] = len(market_members)
        if not market_members:
            flags.append(f"{market.lower()}_stock_master_empty")
        members.extend(market_members)
    members, duplicate_symbol_count = _exclude_duplicate_candidate_symbols(members)
    included_symbols = tuple(member.symbol for member in members if member.included)
    excluded_symbols = tuple((member.symbol, member.reason) for member in members if not member.included)
    if not included_symbols:
        flags.append("stock_master_no_candidates")
    unique_flags = tuple(dict.fromkeys(flags))
    return KisStockMasterResult(
        status="passed" if included_symbols and not unique_flags else "failed",
        mode="network-read-only-stock-master",
        collected_at=collected_at,
        source_files=source_files,
        market_counts=market_counts,
        symbol_count=len(members),
        included_symbols=tuple(dict.fromkeys(included_symbols)),
        excluded_symbols=excluded_symbols,
        members=tuple(members),
        api_flags=unique_flags,
        duplicate_symbol_count=duplicate_symbol_count,
        safety_boundary=_safety_boundary(),
    )


def write_kis_stock_master_report(result: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_kis_stock_master_symbol_list(symbols: tuple[str, ...] | list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{symbol}\n" for symbol in symbols), encoding="utf-8")


def _fetch_bytes(url: str) -> bytes:
    with urlopen(url, timeout=20.0) as response:
        return response.read()


def _parse_kis_stock_master_zip(payload: bytes, *, market: str) -> tuple[KisStockMasterEntry, ...]:
    spec = _MARKET_SPECS[market]
    with ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        expected = str(spec["file_name"])
        if expected not in names:
            raise ValueError("empty stock master zip")
        name = expected
        rows = archive.read(name).decode("cp949").splitlines()
    entries = [_parse_kis_stock_master_row(row, market=market) for row in rows if row.strip()]
    return tuple(entry for entry in entries if entry.symbol)


def _exclude_duplicate_candidate_symbols(members: list[KisStockMasterEntry]) -> tuple[list[KisStockMasterEntry], int]:
    candidate_counts = Counter(member.symbol for member in members if member.included)
    duplicate_symbols = {symbol for symbol, count in candidate_counts.items() if count > 1}
    if not duplicate_symbols:
        return members, 0
    duplicate_member_count = sum(1 for member in members if member.included and member.symbol in duplicate_symbols)
    return (
        [
            replace(member, included=False, reason="duplicate-symbol")
            if member.included and member.symbol in duplicate_symbols
            else member
            for member in members
        ],
        duplicate_member_count,
    )


def _parse_kis_stock_master_row(row: str, *, market: str) -> KisStockMasterEntry:
    spec = _MARKET_SPECS[market]
    suffix_len = int(spec["suffix_len"])
    prefix = row[:-suffix_len]
    suffix = row[-suffix_len:]
    short_code = prefix[0:9].strip()
    standard_code = prefix[9:21].strip()
    name = prefix[21:].strip()
    fields = _split_fixed_width(suffix, spec["widths"])
    indexes = spec["indexes"]
    raw_symbol = short_code[1:] if short_code.startswith("A") else short_code
    symbol = "".join(character for character in raw_symbol if character.isdigit()).zfill(6)
    group = _field(fields, indexes["group"])
    halt = _field(fields, indexes["halt"])
    liquidation = _field(fields, indexes["liquidation"])
    admin = _field(fields, indexes["admin"])
    warning = _field(fields, indexes["warning"])
    preferred = _field(fields, indexes["preferred"])
    etp = _field(fields, indexes["etp"])
    elw = _field(fields, indexes.get("elw", -1))
    status_kind = _status_kind(halt=halt, liquidation=liquidation, admin=admin)
    control_kind = "market-warning" if _truthy_master_flag(warning) else ""
    supervision_kind = _supervision_kind(fields, indexes)
    included, reason = _candidate_decision(
        symbol=symbol,
        group=group,
        status_kind=status_kind,
        preferred=preferred,
        etp=etp,
        elw=elw,
    )
    return KisStockMasterEntry(
        symbol=symbol,
        standard_code=standard_code,
        name=name,
        market=market,
        section_kind=group,
        status_kind=status_kind,
        control_kind=control_kind,
        supervision_kind=supervision_kind,
        included=included,
        reason=reason,
    )


def _split_fixed_width(value: str, widths: tuple[int, ...]) -> list[str]:
    cursor = 0
    fields: list[str] = []
    for width in widths:
        fields.append(value[cursor: cursor + width].strip())
        cursor += width
    return fields


def _field(fields: list[str], index: int) -> str:
    if index < 0 or index >= len(fields):
        return ""
    return fields[index]


def _status_kind(*, halt: str, liquidation: str, admin: str) -> str:
    if _truthy_master_flag(halt):
        return "halted"
    if _truthy_master_flag(liquidation):
        return "liquidation"
    if _truthy_master_flag(admin):
        return "administrative"
    return "normal"


def _supervision_kind(fields: list[str], indexes: dict[str, int]) -> str:
    labels: list[str] = []
    if _truthy_master_flag(_field(fields, indexes["warning_preview"])):
        labels.append("warning-preview")
    if _truthy_master_flag(_field(fields, indexes["unfaithful"])):
        labels.append("unfaithful-disclosure")
    return ",".join(labels)


def _candidate_decision(
    *,
    symbol: str,
    group: str,
    status_kind: str,
    preferred: str,
    etp: str,
    elw: str,
) -> tuple[bool, str]:
    if not symbol.isdigit() or len(symbol) != 6:
        return False, "invalid-symbol"
    if status_kind != "normal":
        return False, status_kind
    if _truthy_master_flag(preferred):
        return False, "preferred-stock"
    if _truthy_master_flag(etp):
        return False, "etp"
    if _truthy_master_flag(elw):
        return False, "elw"
    if group.strip() and group.strip() not in {"ST", "EF"}:
        return False, f"group-{group.strip()}"
    return True, "candidate"


def _truthy_master_flag(value: str) -> bool:
    normalized = value.strip().upper()
    return normalized not in {"", "0", "N", "00", "000"}


def _normalize_markets(markets: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for market in markets:
        name = market.strip().upper()
        if name not in _MARKET_SPECS:
            raise ValueError(f"unknown KIS stock master market: {market}")
        if name not in normalized:
            normalized.append(name)
    return tuple(normalized)


def _safety_boundary() -> str:
    return (
        "KIS stock master refresh downloads public read-only master files only. "
        "It must not call order, balance, account, or real-fill endpoints."
    )
