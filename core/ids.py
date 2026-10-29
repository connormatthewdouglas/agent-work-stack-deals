"""Stable identities shared by the GPU price history, get_price_changes and (T39) quote receipts.

rate_id: one economic offer (vendor, GPU, VRAM, GPU count, tier CLASS, billing unit, and the commitment
term for reserved/monthly rates). Built from the tier class,
not the display label, so a cosmetic tier rename keeps the same id; a change in GPU/VRAM/count/billing/tier class
is a different configuration. event_id / snapshot_id / cursors identify price-change events for lossless watchers.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

RATE_ID_LEN = 12
CURSOR_VERSION = 1


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def _int(v, default=None):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


_TERM_RE = re.compile(r"(\d+)\s*-?\s*(month|mo|year|yr|week|wk)s?\b", re.I)
_TERM_UNIT = {"month": "mo", "mo": "mo", "year": "yr", "yr": "yr", "week": "wk", "wk": "wk"}


def commitment_term(tier: str | None) -> str | None:
    """'3 Month (reserved)' -> '3mo'. A commitment length is part of the economic offer (1-month vs 3-month)."""
    m = _TERM_RE.search(tier or "")
    return f"{int(m.group(1))}{_TERM_UNIT[m.group(2).lower()]}" if m else None


def rate_identity(row: dict) -> str:
    """The normalized identity string a rate_id hashes (exposed for debugging and tests)."""
    from .deals import tier_class  # lazy: deals imports a lot and must not import ids at module load
    tc = tier_class(row)
    term = commitment_term(row.get("tier")) if tc in ("reserved", "dedicated-monthly") else None
    return "|".join([_norm(row.get("vendor") or row.get("advertiser")), _norm(row.get("gpu")),
                     str(_int(row.get("vram_gb"), "")), str(_int(row.get("gpu_count"), 1) or 1),
                     tc, _norm(row.get("billing_unit") or "hourly")] + ([term] if term else []))


def rate_id(row: dict) -> str:
    return "r_" + hashlib.sha1(rate_identity(row).encode("utf-8")).hexdigest()[:RATE_ID_LEN]


def snapshot_id(snap: dict) -> str:
    """Date + content hash of a daily snapshot (same file content -> same id)."""
    rows = sorted(((r.get("key"), r.get("price_usd"), r.get("hourly_usd"), r.get("status")) for r in snap.get("rows") or []),
                  key=lambda t: str(t[0]))
    h = hashlib.sha1(json.dumps(rows, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8]
    return f"{snap.get('date')}.{h}"


def event_id(day: str, rid: str, kind: str) -> str:
    return f"{day}:{rid}:{kind}"


def encode_cursor(seq: int, eid: str | None) -> str:
    raw = json.dumps({"v": CURSOR_VERSION, "seq": int(seq), "eid": eid}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict | None:
    """{'seq', 'eid'} or None if the cursor is malformed."""
    try:
        s = str(cursor).strip()
        d = json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8"))
        if d.get("v") != CURSOR_VERSION or not isinstance(d.get("seq"), int) or d["seq"] < 0:
            return None
        return {"seq": d["seq"], "eid": d.get("eid")}
    except Exception:
        return None
