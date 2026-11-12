"""P39 (hermesagentj, additive, display only): a batch due ledger for scheduled builds and collections.

For each scheduled build: expected_at (next due slot at or after now), last_expected_at (most recently
due slot, including now), and the member rate_ids that build covers. Derived only from the repo's
workflow schedules (tests assert each constant against its yml) and the current feed's membership.
A reader can tell "in this batch, not yet renewed" from "never in the batch" by comparing a row's
checked_at to last_expected_at; this module does not invent whether a run actually happened.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .ids import rate_id

GPU_REFRESH_UTC = ((10, 23), (14, 47))  # gpu-refresh.yml: "23 10 * * *" primary, "47 14 * * *" fallback
LIUM_COLLECT = (2, 40)                  # lium-collect.yml: "40 */2 * * *"
SCOUT_IMPORT = (4, 10)                  # scout-import.yml gate: now.hour % 4 == 0 and 10 <= now.minute < 25

BUILDS = ("gpu-refresh", "lium-collect", "scout-import", "scout-wider")


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)


def _daily_next(now: datetime, hm: tuple) -> datetime:
    t = now.replace(hour=hm[0], minute=hm[1], second=0)
    return t if t >= now else t + timedelta(days=1)


def _daily_last(now: datetime, hm: tuple) -> datetime:
    t = now.replace(hour=hm[0], minute=hm[1], second=0)
    return t if t <= now else t - timedelta(days=1)


def _every_next(now: datetime, step_h: int, minute: int) -> datetime:
    base = now.replace(minute=minute, second=0, hour=0)
    for h in range(0, 24 + step_h):
        t = base + timedelta(hours=h)
        if t.hour % step_h == 0 and t >= now:
            return t
    raise AssertionError("unreachable")


def _every_last(now: datetime, step_h: int, minute: int) -> datetime:
    last = None
    base = now.replace(hour=0, minute=minute, second=0)
    for h in range(-24, 24 + step_h):
        t = base + timedelta(hours=h)
        if t.hour % step_h == 0 and t <= now:
            last = t
    if last is None:
        raise AssertionError("unreachable")
    return last


def _vendor(row: dict) -> str:
    return str(row.get("advertiser") or row.get("vendor") or "")


def _is_lium(row: dict) -> bool:
    return _vendor(row).split(" ")[0] == "Lium"


def _ids(rows: list) -> list[str]:
    return sorted(rate_id(r) for r in rows)


def members_gpu_refresh(rates: list) -> list:
    return [r for r in rates if r.get("price_check") in ("daily", "rotating snapshot") and not _is_lium(r)]


def members_lium(rates: list) -> list:
    return [r for r in rates if _is_lium(r)]


def members_scout_import(rates: list) -> list:
    """Rows Scout is scheduled to re-check for stock. no_api is out of scope, not in the batch."""
    out = []
    for r in rates:
        av = r.get("availability") if isinstance(r.get("availability"), dict) else {}
        if av.get("origin") != "scout":
            continue
        if (r.get("availability_reason_detail") or av.get("availability_reason_detail")) == "no_api":
            continue
        out.append(r)
    return out


def members_scout_wider(rates: list) -> list:
    return [r for r in rates if r.get("price_check") == "batch"]


def _entry(build: str, expected: datetime, last: datetime, rows: list, basis: str,
           fallback: datetime | None = None) -> dict:
    ids = _ids(rows)
    out = {"build": build, "expected_at": _iso(expected), "last_expected_at": _iso(last),
           "fallback_expected_at": _iso(fallback) if fallback else None,
           "member_count": len(ids), "member_rate_ids": ids, "schedule_basis": basis}
    return out


def ledger(feed: dict, now: datetime | None = None) -> list[dict]:
    """Due ledger for the current feed. One entry per scheduled build, always in BUILDS order."""
    now = _utc(now)
    rates = [r for r in (feed.get("rates") or []) if isinstance(r, dict)]
    g_next, g_last = _daily_next(now, GPU_REFRESH_UTC[0]), _daily_last(now, GPU_REFRESH_UTC[0])
    g_fb = _daily_next(now, GPU_REFRESH_UTC[1])
    s_next, s_last = _every_next(now, *SCOUT_IMPORT), _every_last(now, *SCOUT_IMPORT)
    l_next, l_last = _every_next(now, *LIUM_COLLECT), _every_last(now, *LIUM_COLLECT)
    return [
        _entry("gpu-refresh", g_next, g_last, members_gpu_refresh(rates),
               "gpu-refresh.yml daily 10:23 UTC, fallback 14:47 UTC; members are daily / rotating-snapshot prices (not Lium)",
               fallback=g_fb),
        _entry("lium-collect", l_next, l_last, members_lium(rates),
               "lium-collect.yml every 2 h at :40 UTC (scripts/collect_lium.py); members are Lium rows"),
        _entry("scout-import", s_next, s_last, members_scout_import(rates),
               "scout-import.yml 4-hourly slot (00/04/08/12/16/20 UTC from :10); members are Scout-origin stock rows (not no_api)"),
        _entry("scout-wider", s_next, s_last, members_scout_wider(rates),
               "scripts/import_scout_wider.py in the same scout-import.yml 4-hourly run; members are price_check=batch rows"),
    ]
