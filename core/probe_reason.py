"""P41 (marxsignal, additive, display only): a fixed failure reason on failed / "no" availability
probes, kept when the claim later lapses. Never guessed.

Enum: sold_out, region, quota, other, or null when the source does not say. Ranking never reads these
fields (it still reads in_stock). Computed at MCP finalize time from the probe outcome already on the
row; HTTP-failed probes that Scout never wrote into a snapshot cannot be invented.
"""
from __future__ import annotations

import re

REASONS = ("sold_out", "region", "quota", "other")
KEYS = ("failure_reason", "failure_reason_detail")

# Only source-stated codes or phrases. derived_from_regions, "no confirmed region", and a blank
# region list are not a `region` reason (those are unknown / no_source, never guessed).
_REGION_CODES = frozenset({"region", "region_unavailable", "not_in_region", "no_capacity_in_region", "wrong_region"})
_QUOTA_CODES = frozenset({"quota", "quota_exceeded", "over_quota", "out_of_quota"})
_REGION_PHRASE = re.compile(
    r"\b(region[ _]unavailable|not available in (this |the |requested )?region|"
    r"wrong region|region (not available|unavailable|excluded))\b",
    re.I,
)
_QUOTA_PHRASE = re.compile(r"\b(quota exceeded|over[_ ]quota|out of quota|quota[_ ]exceeded)\b", re.I)
_FAILED = ("check_failed_http", "check_failed_timeout")
_OURS = "this availability check is past its availability_expires_at"


def _av(src: dict) -> dict:
    return src.get("availability") if isinstance(src.get("availability"), dict) else {}


def _get(src: dict, key: str):
    v = src.get(key)
    return v if v is not None else _av(src).get(key)


def _strings(src: dict) -> list[str]:
    out = []
    for key in ("availability_reason", "availability_reason_detail", "availability_observation",
                "observation", "availability_note", "note"):
        for d in (src, _av(src)):
            v = d.get(key)
            if isinstance(v, str) and v.strip() and v.strip() not in out:
                out.append(v.strip())
    return out


def _codes(src: dict) -> set[str]:
    codes = set()
    for key in ("availability_reason", "availability_reason_detail"):
        v = _get(src, key)
        if isinstance(v, str) and v.strip():
            codes.add(v.strip().lower())
    return codes


def _explicit(src: dict) -> str | None:
    """region or quota only when the source itself states it. Never inferred."""
    text = " ".join(_strings(src))
    if _codes(src) & _QUOTA_CODES or _QUOTA_PHRASE.search(text):
        return "quota"
    if _codes(src) & _REGION_CODES or _REGION_PHRASE.search(text):
        return "region"
    return None


def _detail(src: dict) -> str | None:
    """Pass through Scout/vendor detail only. Never invent, and never use our stale-claim note."""
    for key in ("availability_reason_detail", "availability_observation", "observation"):
        v = _get(src, key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for key in ("availability_note", "note"):
        v = _get(src, key)
        if isinstance(v, str) and v.strip() and _OURS not in v.lower():
            if _QUOTA_PHRASE.search(v) or _REGION_PHRASE.search(v):
                return v.strip()
    return None


def classify(src: dict) -> dict:
    """Return failure_reason + failure_reason_detail for a tool row or an availability dict.

    sold_out: a firm out-of-stock answer (in_stock false, or a lapsed claim whose last_known_in_stock
    is false) when the source did not state region or quota. This keeps a failed "no" that would
    otherwise be dropped when the claim lapses.
    region / quota: only when the source states that reason.
    other: a recorded probe failure (check_failed_http / check_failed_timeout) that is not those three.
    null: the source does not say (unknown, no_source, a last-known in-stock, or never probed).
    """
    if not isinstance(src, dict):
        return {"failure_reason": None, "failure_reason_detail": None}
    in_stock = _get(src, "in_stock")
    last = _get(src, "last_known_in_stock")
    reason = _get(src, "availability_reason")
    explicit = _explicit(src)
    detail = _detail(src)

    if in_stock is True:
        return {"failure_reason": None, "failure_reason_detail": None}

    if explicit and (in_stock is False or last is False or (isinstance(reason, str) and reason.startswith("check_failed"))):
        return {"failure_reason": explicit, "failure_reason_detail": detail}

    if in_stock is False or last is False:
        return {"failure_reason": "sold_out", "failure_reason_detail": detail}

    if isinstance(reason, str) and (reason.startswith("check_failed") or reason in _FAILED):
        return {"failure_reason": "other", "failure_reason_detail": detail}

    return {"failure_reason": None, "failure_reason_detail": None}


def apply(av: dict, row: dict | None = None) -> dict:
    """Write KEYS onto an availability dict. Returns the same object. Display only."""
    src = {**(row or {}), "availability": av} if row is not None else av
    av.update(classify(src))
    return av
