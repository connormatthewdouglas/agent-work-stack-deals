"""Brain #584 / eddie_compute (additive, display only): when a rate's price took effect, and the smallest hourly bill.

effective_at (with effective_at_basis) answers "since when has the vendor charged this price?", which is a different
question from last_verified / verified_at ("when did we last confirm it?"):
  - "vendor_stated": the vendor's own page dates the price (price_effective_at, e.g. Lambda's public list), and the price
    has not changed since that instant. effective_at is that instant, exactly as the vendor states it.
  - "first_observed": our daily snapshots saw a different price for this exact rate before, and effective_at is the
    verified_at recorded in the first daily snapshot that showed the current price. It is an upper bound: the vendor
    changed the price at or before this instant (and after the earlier price was last seen); we do not know the exact
    instant.
  - null (effective_at null): we cannot date it from real data. The price is the first one we ever recorded for this rate
    (it predates our tracking), the rate dropped out of tracking in between, or the price changed since the latest daily
    snapshot. Never guessed.

min_bill_usd_per_hour = min_gpus x the per-GPU hourly price (hourly_equiv_usd in the feed, hourly_usd in MCP rows): the
least a caller pays per hour for one allocation. min_bill_basis says what that hourly price is:
  - "hourly_rate": the vendor's own per-GPU hourly rate (billing_unit hourly);
  - "per_second_rate": the vendor's per-second rate x 3600 (billing_unit per-second, billed per second while running);
  - "monthly_equivalent": a derived figure for a flat monthly server (monthly price / 730 h); the vendor bills the month,
    not the hour, so this is an equivalent, never a quoted hourly rate.
Both are null when min_gpus or the hourly price is missing. Ranking never reads any of these fields.
"""
from __future__ import annotations

from datetime import datetime, timezone

EFFECTIVE_KEYS = ("effective_at", "effective_at_basis")
MIN_BILL_KEYS = ("min_bill_usd_per_hour", "min_bill_basis")
_BASIS_BY_UNIT = {"hourly": "hourly_rate", "per-second": "per_second_rate", "monthly": "monthly_equivalent"}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _ts(s) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def first_observed(points: list, price) -> str | None:
    """verified_at of the first daily-snapshot point at `price`, counted back from the latest point, provided an earlier
    point showed a different price (so a change was actually observed). None otherwise."""
    if not _num(price) or not points:
        return None
    same = lambda p: _num(p.get("hourly_usd")) and abs(p["hourly_usd"] - price) < 1e-9  # noqa: E731
    last = points[-1]
    if last.get("status") == "removed" or not same(last):
        return None  # untracked now, or the price moved after the latest snapshot: not datable from history
    i = len(points) - 1
    while i > 0 and points[i - 1].get("status") != "removed" and same(points[i - 1]):
        i -= 1
    if i == 0 or points[i - 1].get("status") == "removed" or not _num(points[i - 1].get("hourly_usd")):
        return None  # first price we ever recorded, or the rate was out of tracking just before: no observed change
    t = points[i].get("verified_at")
    return t if _ts(t) else None


def effective_at(row: dict, series: dict | None) -> tuple[str | None, str | None]:
    """(effective_at, effective_at_basis) for a feed rate row; (None, None) when real data cannot date it."""
    price = row.get("hourly_equiv_usd", row.get("hourly_usd"))
    seen = first_observed((series or {}).get("points") or [], price)
    stated = row.get("price_effective_at")
    st = _ts(stated)
    if st is not None and (seen is None or _ts(seen) <= st):
        return stated, "vendor_stated"  # a later observed change would mean the stated date belongs to an older price
    return (seen, "first_observed") if seen else (None, None)


def min_bill(row: dict) -> tuple[float | None, str | None]:
    """(min_bill_usd_per_hour, min_bill_basis): min_gpus x per-GPU hourly price; (None, None) when an input is missing."""
    n = row.get("min_gpus")
    price = row.get("hourly_equiv_usd", row.get("hourly_usd"))
    if not (isinstance(n, int) and not isinstance(n, bool) and n >= 1) or not _num(price):
        return None, None
    return round(n * price, 6), _BASIS_BY_UNIT.get(row.get("billing_unit"))


def series_key(row: dict) -> str:
    """Same key as core.gpu_history.series_key for a feed rate row (advertiser|gpu|tier|vram_gb|gpu_count)."""
    return f"{row.get('advertiser')}|{row.get('gpu')}|{row.get('tier')}|{row.get('vram_gb')}|{row.get('gpu_count') or 1}"


def annotate(rates: list, history: dict | None) -> list:
    """Add effective_at / effective_at_basis and min_bill_usd_per_hour / min_bill_basis to every feed rate (in place)."""
    series = {s.get("key"): s for s in (history or {}).get("series") or [] if isinstance(s, dict)}
    for r in rates:
        r["effective_at"], r["effective_at_basis"] = effective_at(r, series.get(series_key(r)))
        r["min_bill_usd_per_hour"], r["min_bill_basis"] = min_bill(r)
    return rates
