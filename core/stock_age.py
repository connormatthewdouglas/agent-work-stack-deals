"""P74: stock age measured at read/serve time (display only).

stock_age_hours is the reader clock minus availability.stock_read_at, falling back to
availability.checked_at (the stock claim time). It is not price data_age_hours, and it
never uses price verified_at/checked_at or probe_attempted_at.

stock_read_state distinguishes never_read (no stock check timestamp) from read and
read_expired (a check was taken and the claim has lapsed). Timestamps are never invented.
Ranking, TTL and stale_guard do not read these fields.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .data_age import _clock

NEVER_READ = "never_read"
READ = "read"
READ_EXPIRED = "read_expired"

# Prefer the stock-claim stamps named in Brain #1142. Never the price row or a crashed probe.
_STOCK_TS_KEYS = ("stock_read_at", "checked_at")


def _parse_ts(raw) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        ts = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def stock_timestamp(av: dict | None) -> tuple[datetime | None, str | None]:
    """Return (timestamp, basis key) from the availability object only. Never invent one.

    Age is how old the stock *claim* is. On a lapsed claim, last_known_at is that claim
    time; checked_at may be a later scout touch and must not make an expired claim look fresh.
    A current firm claim uses stock_read_at, then checked_at.
    """
    if not isinstance(av, dict):
        return None, None
    # Lapsed or unknown-after-a-firm-answer: last_known_at is the claim, if present.
    if av.get("last_known_at") and (av.get("availability_stale") or av.get("in_stock") is None):
        ts = _parse_ts(av.get("last_known_at"))
        if ts is not None:
            return ts, "last_known_at"
    for key in _STOCK_TS_KEYS:
        ts = _parse_ts(av.get(key))
        if ts is not None:
            return ts, key
    return None, None


def claim_expired(av: dict | None, now: datetime | None = None) -> bool:
    """True when a prior stock claim has expired. Does not invent expiry."""
    if not isinstance(av, dict):
        return False
    if av.get("availability_stale"):
        return True
    exp = _parse_ts(av.get("availability_expires_at"))
    if exp is None:
        return False
    clock = _clock(now)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(timezone.utc) > exp


def stock_age_fields(av: dict | None, now: datetime | None = None) -> dict:
    """Additive display fields. Safe to call with None or a non-dict."""
    clock = _clock(now)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    clock = clock.astimezone(timezone.utc)
    ts, basis = stock_timestamp(av)
    if ts is None:
        return {
            "stock_age_hours": None,
            "stock_age_basis": None,
            "stock_read_state": NEVER_READ,
        }
    hours = round(max(0.0, (clock - ts).total_seconds() / 3600.0), 1)
    state = READ_EXPIRED if claim_expired(av, clock) else READ
    return {
        "stock_age_hours": hours,
        "stock_age_basis": basis,
        "stock_read_state": state,
    }


def attach_stock_age(row: dict, now: datetime | None = None) -> dict:
    """Add stock-age fields on the result row only. Availability is passed through unchanged."""
    av = row.get("availability") if isinstance(row.get("availability"), dict) else None
    out = dict(row)
    out.update(stock_age_fields(av, now))
    return out


def stock_age_phrase(av: dict | None, now: datetime | None = None) -> str:
    """Short render label, or empty when there is no stock timestamp (never read)."""
    fields = stock_age_fields(av, now)
    if fields["stock_read_state"] == NEVER_READ or fields["stock_age_hours"] is None:
        return ""
    h = fields["stock_age_hours"]
    if h < 1:
        mins = int(round(h * 60))
        return f"stock read {mins}m ago"
    if h < 48:
        text = str(int(h)) if h == int(h) else str(h)
        return f"stock read {text}h ago"
    days = int(h // 24)
    return f"stock read {days}d ago"
