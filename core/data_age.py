"""Per-row data-age flags (T37): data_age_hours, degraded, stale, plus an optional max_data_age_hours filter.

Age is measured from the row's verified_at (when its price was last parsed from the vendor page), falling back to
checked_at. degraded = older than DEGRADED_HOURS (the daily refresh missed at least one run); stale = older than
gpu.STALE_DAYS (such rows are normally held out at build time, so a stale row here means the published data is old).
A row with no parseable timestamp is flagged stale with data_age_hours null and never passes a max-age filter.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .gpu import STALE_DAYS

DEGRADED_HOURS = 48
STALE_HOURS = STALE_DAYS * 24


def _ts(row: dict) -> datetime | None:
    for k in ("verified_at", "checked_at"):
        v = row.get(k)
        if isinstance(v, str) and v:
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                continue
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def age_fields(row: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ts = _ts(row)
    if ts is None:
        return {"data_age_hours": None, "degraded": True, "stale": True}
    h = round(max(0.0, (now - ts).total_seconds() / 3600), 1)
    return {"data_age_hours": h, "degraded": h > DEGRADED_HOURS, "stale": h > STALE_HOURS}


def validate_max_age(max_data_age_hours) -> float | None:
    if max_data_age_hours is None:
        return None
    if isinstance(max_data_age_hours, bool) or not isinstance(max_data_age_hours, (int, float)) or max_data_age_hours <= 0:
        raise ValueError("max_data_age_hours must be a number > 0")
    return float(max_data_age_hours)


def too_old(row: dict, max_h: float | None, now: datetime | None = None) -> bool:
    if max_h is None:
        return False
    a = age_fields(row, now)["data_age_hours"]
    return a is None or a > max_h


# Gauge re28: current recommendations never rank a price older than this unless max_data_age_hours says otherwise.
CURRENT_MAX_HOURS = STALE_HOURS


def stale_label(row: dict, now: datetime | None = None) -> str:
    h = age_fields(row, now)["data_age_hours"]
    return "stale price (check time unknown)" if h is None else f"stale price ({h / 24:.0f} days old)"


def split_current(rows: list, max_h: float | None, now: datetime | None = None, get=lambda r: r) -> tuple[list, list]:
    """(current, stale). Default limit CURRENT_MAX_HOURS (168 h); an explicit max_data_age_hours replaces it."""
    lim = CURRENT_MAX_HOURS if max_h is None else max_h
    cur, old = [], []
    for r in rows:
        (old if too_old(get(r), lim, now) else cur).append(r)
    return cur, old


def stale_view(row: dict, now: datetime | None = None, price_key: str = "hourly_equiv_usd") -> dict:
    from .ids import rate_id
    return {"rate_id": rate_id(row), "vendor": row.get("advertiser") or row.get("vendor"), "gpu": row.get("gpu"),
            "vram_gb": row.get("vram_gb"), "tier": row.get("tier"), "price": row.get(price_key),
            "source_url": row.get("source_url"), "verified_at": row.get("verified_at"),
            **age_fields(row, now), "label": stale_label(row, now)}


def stale_option(o: dict, now: datetime | None = None) -> dict:
    keys = ("rate_id", "vendor", "plan", "monthly_cost_usd", "calc", "source_url", "checked_at", "verified_at")
    return {**{k: o.get(k) for k in keys if k in o}, **age_fields(o, now), "label": stale_label(o, now)}


def all_stale_note(n: int) -> str:
    return (f"All {n} tracked GPU prices that match are older than {CURRENT_MAX_HOURS} h (stale), so no current cheapest is "
            "named; see stale_prices, or pass max_data_age_hours to rank them anyway.")
