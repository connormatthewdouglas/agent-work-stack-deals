"""Stale vs missing data for the T41 release gate (Gauge NO-GO B2, Bjorn decision 2026-11-17).

Bjorn 2026-11-17: warn >36h, hard fail >7d; empty or zero-row = fail.
  * T41-12: a checkout feed_updated_at older than 36h warns; older than 168h (7 days) fails.
  * T41-24 / T41-26: an in-stock claim past its own expiry is stale. It warns while it is at most 168h past
    expiry and fails beyond that. Missing data (no checked_at, no availability_expires_at, zero rows, an empty
    source) always fails. Rule violations (region-derived claim without regions, vendor-API claim > 1h,
    RunPod without a confirmed region) are not staleness and always fail.
Kept import-free (no core/, no network) so tests can exercise it directly.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

FEED_WARN_H = 36
STALE_FAIL_H = 168  # 7 days


def _h(td: timedelta) -> float:
    return td.total_seconds() / 3600


def feed_age(fu: datetime, now: datetime) -> tuple[list[str], list[str]]:
    """(failures, warnings) for the checkout feed_updated_at."""
    age = _h(now - fu)
    msg = f"T41-12: checkout feed_updated_at {fu.isoformat()} is {age:.1f}h old"
    if age > STALE_FAIL_H:
        return [f"{msg} (> {STALE_FAIL_H}h hard cap)"], []
    if age > FEED_WARN_H:
        return [], [f"{msg} (> {FEED_WARN_H}h; warns up to {STALE_FAIL_H}h)"]
    return [], []


def past_expiry(label: str, exp: datetime, now: datetime) -> tuple[list[str], list[str]]:
    """An expired claim: warn up to STALE_FAIL_H past expiry, fail beyond."""
    late = _h(now - exp)
    if late <= 0:
        return [], []
    msg = f"{label} expired {exp.isoformat()} ({late:.1f}h ago)"
    return ([f"{msg} (> {STALE_FAIL_H}h hard cap)"], []) if late > STALE_FAIL_H else ([], [f"stale: {msg}"])


def claims_t41_24(name: str, rates: list, now: datetime, lim: timedelta, ts, rid) -> tuple[list[str], list[str], int]:
    """JSON in-stock claims past checked_at + lim (or availability_expires_at). Returns (failures, warnings, n)."""
    f: list[str] = []
    w: list[str] = []
    n = 0
    if not rates:
        return [f"{name}: zero rows (missing data, not stale)"], [], 0
    for r in rates:
        a = r.get("availability") if isinstance(r.get("availability"), dict) else {}
        if a.get("in_stock") is not True:
            continue
        n += 1
        if not a.get("checked_at"):
            f.append(f"{name}: {rid(r)} in stock with no checked_at")
            continue
        if not a.get("availability_expires_at"):
            f.append(f"{name}: {rid(r)} in stock without availability_expires_at")
        exp = ts(a["availability_expires_at"]) if a.get("availability_expires_at") else ts(a["checked_at"]) + lim
        exp = min(exp, ts(a["checked_at"]) + lim)
        ff, ww = past_expiry(f"{name}: {rid(r)} in stock, checked {a['checked_at']},", exp, now)
        f += ff
        w += ww
    return f, w, n


def claims_t41_26(rates: list, now: datetime, ts, rid) -> tuple[list[str], list[str], int]:
    f: list[str] = []
    w: list[str] = []
    n = 0
    if not rates:
        return ["gpu-prices.json: zero rows (missing data, not stale)"], [], 0
    for r in rates:
        a = r.get("availability") if isinstance(r.get("availability"), dict) else {}
        if a.get("in_stock") is not True:
            continue
        n += 1
        if a.get("availability_expires_at"):
            ff, ww = past_expiry(f"{rid(r)} in stock past availability_expires_at", ts(a["availability_expires_at"]), now)
            f += ff
            w += ww
        if a.get("derived_from_regions"):
            if not a.get("regions_expires_at"):
                f.append(f"{rid(r)} region-derived claim in stock without regions_expires_at")
            else:
                ff, ww = past_expiry(f"{rid(r)} region-derived claim: regions", ts(a["regions_expires_at"]), now)
                f += ff
                w += ww
        if (str(r.get("advertiser")).startswith(("Lambda", "Verda")) or a.get("derived_from_regions")) and a.get("checked_at") \
                and a.get("availability_expires_at") and (ts(a["availability_expires_at"]) - ts(a["checked_at"])).total_seconds() > 3600:
            f.append(f"{rid(r)} vendor-API/derived claim lasts longer than 1 h (re20 P3)")
        if r.get("advertiser") == "RunPod" and a.get("origin") == "scout" and not a.get("available_regions"):
            f.append(f"{rid(r)} RunPod in stock with no confirmed region")
    return f, w, n


def note(case: str, warnings: list[str]) -> None:
    """One line per case to $LW_STALE_NOTES (routed to the freshness-watchdog issue on main)."""
    if warnings and os.environ.get("LW_STALE_NOTES"):
        with open(os.environ["LW_STALE_NOTES"], "a", encoding="utf-8") as fh:
            fh.write(f"{case}: {len(warnings)} stale in-stock claim(s) (warn up to {STALE_FAIL_H}h), e.g. {warnings[0]}\n")
