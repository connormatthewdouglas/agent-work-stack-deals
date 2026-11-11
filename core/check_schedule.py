"""P40 (scraplingdata, additive, display only): when a stale or unknown row is next checked, and whether that check
can fill it ("filling") or no scheduled check covers it ("scope limit").

Derived only from the repo's own schedules (tests assert each constant against its workflow file) and per-row config:
  - stock (availability unknown or lapsed): a row with Scout stock data (availability.origin "scout") is re-read by
    Scout and imported on the 4-hourly slot of .github/workflows/scout-import.yml (UTC hours 00/04/08/12/16/20, from
    :10). A row with no stock source (no Scout row, or Scout reason no_source/no_api) is a scope limit.
  - price (stale_prices): price_check "daily" -> .github/workflows/gpu-refresh.yml (10:23 UTC, fallback 14:47 UTC);
    Lium -> .github/workflows/lium-collect.yml ("40 */2 * * *", scripts/collect_lium.py); price_check "batch" (Scout
    wider-GPU batch) -> imported by scripts/import_scout_wider.py in the scout-import.yml 4-hourly run; any other "manual snapshot" -> scope limit.
Fields: next_check_at = next scheduled run at or after `now` (ISO UTC; GitHub cron can start late); will_backfill =
true (a scheduled check covers the row) / false (scope limit) / null (not derivable); backfill_eta = the last scheduled
attempt of that cycle (daily price: the 14:47 fallback; other schedules have no fallback, so it equals next_check_at);
next_check_basis = which schedule or config gave the answer. A scheduled run fills the row only if the source answers;
a missed check is never re-run for the past.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

GPU_REFRESH_UTC = ((10, 23), (14, 47))  # gpu-refresh.yml: "23 10 * * *" primary, "47 14 * * *" fallback
LIUM_COLLECT = (2, 40)                  # lium-collect.yml: "40 */2 * * *"
SCOUT_IMPORT = (4, 10)                  # scout-import.yml gate: now.hour % 4 == 0 and 10 <= now.minute < 25
KEYS = ("next_check_at", "will_backfill", "backfill_eta", "next_check_basis")


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)


def _daily(now: datetime, hm: tuple) -> datetime:
    t = now.replace(hour=hm[0], minute=hm[1], second=0)
    return t if t >= now else t + timedelta(days=1)


def _every(now: datetime, step_h: int, minute: int) -> datetime:
    base = now.replace(minute=minute, second=0)
    for h in range(0, 24 + step_h):
        t = base.replace(hour=0) + timedelta(hours=h)
        if h % step_h == 0 and t >= now:
            return t
    raise AssertionError("unreachable")


def _out(nxt, eta, basis) -> dict:
    if nxt is None:
        return {"next_check_at": None, "will_backfill": False, "backfill_eta": None, "next_check_basis": basis}
    return {"next_check_at": _iso(nxt), "will_backfill": True, "backfill_eta": _iso(eta or nxt), "next_check_basis": basis}


def stock(row: dict, now: datetime | None = None) -> dict:
    """For a row whose stock is unknown (in_stock null, including a lapsed claim). {} when the row has a firm answer."""
    av = row.get("availability") if isinstance(row.get("availability"), dict) else {}
    if av.get("in_stock") is not None or row.get("in_stock") is not None:
        return {}
    now = _utc(now)
    if av.get("origin") != "scout":
        return _out(None, None, "scope limit: no scheduled stock check covers this row (no Scout stock source)")
    if (row.get("availability_reason_detail") or av.get("availability_reason_detail")) == "no_api":
        return _out(None, None, "scope limit: Scout has no stock API for this vendor (no_source/no_api)")
    t = _every(now, *SCOUT_IMPORT)
    return _out(t, t, "scout-import.yml 4-hourly slot (00/04/08/12/16/20 UTC from :10); a Scout push can import sooner")


def price(row: dict, now: datetime | None = None) -> dict:
    """For a row whose price is stale. Uses the row's price_check and vendor; null when not derivable."""
    now = _utc(now)
    pc, vendor = row.get("price_check"), str(row.get("advertiser") or row.get("vendor") or "")
    if vendor.split(" ")[0] == "Lium":
        t = _every(now, *LIUM_COLLECT)
        return _out(t, t, "lium-collect.yml every 2 h at :40 UTC (scripts/collect_lium.py)")
    if pc == "batch":
        t = _every(now, *SCOUT_IMPORT)
        return _out(t, t, "scout-import.yml 4-hourly slot (from :10 UTC) imports Scout's wider-GPU batch when Scout has published one")
    if pc in ("daily", "rotating snapshot"):
        p = _daily(now, GPU_REFRESH_UTC[0])
        f = p.replace(hour=GPU_REFRESH_UTC[1][0], minute=GPU_REFRESH_UTC[1][1])
        return _out(p, f, "gpu-refresh.yml daily 10:23 UTC, fallback 14:47 UTC")
    if pc == "manual snapshot":
        return _out(None, None, "scope limit: manual snapshot, no scheduled re-read")
    return {"next_check_at": None, "will_backfill": None, "backfill_eta": None,
            "next_check_basis": "not derivable: no known schedule for this row"}
