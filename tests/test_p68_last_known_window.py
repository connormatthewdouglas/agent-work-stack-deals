"""P68 (Brain #1081): flag last_known against each row's own stock-claim window and show that window.

Deterministic: fixtures and a frozen clock only. No live feed, no wall clock,
no pins to committed history or gpu-prices.json.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from core import contract
from core.deals import find_available_gpus, compare_gpu_prices
from core.gpu_availability import (
    AVAIL_MAX_AGE_H,
    annotate_last_known_window,
    apply_probe_outcome,
    last_known_window,
    publish_availability,
    stale_guard,
)

NOW = datetime(2026, 11, 26, 17, 0, 0, tzinfo=timezone.utc)
# Verda-style 15-minute live claim
VERDA_KNOWN = "2026-11-26T16:00:00Z"       # 1h before NOW
VERDA_EXPIRES = "2026-11-26T16:15:00Z"     # 0.25h window; outside at NOW
VERDA_FRESH = "2026-11-26T16:50:00Z"
VERDA_FRESH_EXP = "2026-11-26T17:05:00Z"
# 1h firm claim, then a later no_source read
FIRM_AT = "2026-11-26T12:00:00Z"
FIRM_EXPIRES = "2026-11-26T13:00:00Z"      # last good 1h window
FAILED_AT = "2026-11-26T16:00:00Z"         # later failed read; must not extend


def _firm(vendor="Verda", gpu="H100", checked=VERDA_KNOWN, expires=VERDA_EXPIRES, in_stock=True, max_age=0.25):
    return {
        "status": "available when checked" if in_stock else "out of stock when checked",
        "in_stock": in_stock, "checked_at": checked, "origin": "scout",
        "availability_expires_at": expires, "max_age_hours": max_age,
        "advertiser": vendor, "vendor": vendor, "tier": "Spot",
    }


def _lapsed(firm, failed_at=FAILED_AT, max_age=8.0, expires="2026-11-27T00:00:00Z"):
    """A later no_source read that keeps last_known and the last good claim window."""
    failed = apply_probe_outcome(
        {"in_stock": None, "checked_at": failed_at, "origin": "scout",
         "availability_reason": "no_source", "availability_status": "unknown",
         "max_age_hours": max_age, "availability_expires_at": expires},
        firm,
    )
    exp, h = last_known_window(firm)
    if exp:
        failed["last_known_expires_at"] = exp
    if h is not None:
        failed["last_known_max_age_hours"] = h
    return failed


def _rate(vendor, gpu="H100", price=2.0, av=None, **kw):
    r = {
        "advertiser": vendor, "gpu": gpu, "tier": "On-demand", "vram_gb": 80,
        "gpu_count": 1, "min_gpus": 1, "hourly_equiv_usd": price, "hourly_usd": price,
        "price_usd": price, "unit": "hour", "billing_unit": "hourly", "price_status": "listed",
        "tier_class": "on-demand",
        "source_url": f"https://example.test/{vendor.lower()}",
        "verified_at": (av or {}).get("checked_at") or FIRM_AT,
        "checked_at": (av or {}).get("checked_at") or FIRM_AT,
        "availability": av or {},
    }
    r.update(kw)
    return r


def _feed(rates):
    return {"rates": rates, "held_stale": [],
            "availability_collected_at": "2026-11-26T16:00:00Z",
            "feed_updated_at": "2026-11-26T16:00:00Z"}


def test_verda_last_known_flagged_after_its_own_15_minute_window():
    # Firm 0.25h claim, then a later unknown reading that keeps last_known.
    firm = _firm()
    failed = _lapsed(firm)
    out = annotate_last_known_window(failed, NOW)
    assert out["last_known_in_stock"] is True and out["last_known_at"] == VERDA_KNOWN
    assert out["last_known_expires_at"] == VERDA_EXPIRES
    assert out["last_known_max_age_hours"] == pytest.approx(0.25)
    assert out["last_known_outside_window"] is True
    # P64 stale_guard 8h clock is not tripped at +1h
    g = stale_guard(failed, NOW)
    assert g.get("availability_stale") is not True or g.get("in_stock") is None
    # last_known still visible; we only flag, we do not cap/drop it
    assert out["last_known_in_stock"] is True


def test_verda_last_known_inside_its_own_window_is_not_flagged():
    firm = _firm(checked=VERDA_FRESH, expires=VERDA_FRESH_EXP)
    out = annotate_last_known_window(firm, NOW)
    assert out["last_known_outside_window"] is False
    assert out["last_known_expires_at"] == VERDA_FRESH_EXP
    assert stale_guard(firm, NOW) is firm or stale_guard(firm, NOW)["in_stock"] is True


def test_failed_read_keeps_last_good_window_never_extends():
    firm = _firm(checked=FIRM_AT, expires=FIRM_EXPIRES, max_age=1.0, vendor="RunPod")
    failed = _lapsed(firm)
    exp, h = last_known_window(failed)
    assert exp == FIRM_EXPIRES and h == pytest.approx(1.0)
    out = annotate_last_known_window(failed, NOW)
    assert out["last_known_expires_at"] == FIRM_EXPIRES
    assert out["last_known_outside_window"] is True
    # Must not adopt the failed read's later 8h expiry
    assert out["last_known_expires_at"] != failed.get("availability_expires_at")
    assert out["last_known_expires_at"] < failed["availability_expires_at"]


def test_no_source_row_with_last_known_but_null_live_expiry_still_shows_window():
    """The marxsignal case: last_known true, max_age_hours / availability_expires_at null."""
    av = {
        "status": "unknown", "in_stock": None, "origin": "scout",
        "availability_reason": "no_source",
        "last_known_in_stock": True, "last_known_at": FIRM_AT,
        "last_known_expires_at": FIRM_EXPIRES, "last_known_max_age_hours": 1.0,
        "max_age_hours": None, "availability_expires_at": None,
    }
    # MCP path: stale_guard + P72 (publish) then P68 window annotation (serializers).
    out = annotate_last_known_window(publish_availability(av, "RunPod", "On-demand", NOW, annotate=True), NOW)
    assert out["last_known_in_stock"] is True
    assert out["last_known_expires_at"] == FIRM_EXPIRES
    assert out["last_known_outside_window"] is True
    assert out["last_known_expires_at"].endswith("Z")


def test_p64_eight_hour_stale_guard_unchanged():
    # A default 8h claim is still live at +7.9h and stale just after 8h.
    start = "2026-11-26T08:00:00Z"  # 9h before NOW would be stale; use 7.9h
    checked = "2026-11-26T09:10:00Z"  # 7h 50m before NOW
    av = _firm(checked=checked, expires="2026-11-26T17:10:00Z", max_age=8.0, vendor="Acme")
    live = stale_guard(av, NOW)
    assert live["in_stock"] is True and live.get("availability_stale") is not True
    later = datetime(2026, 11, 26, 17, 10, 1, tzinfo=timezone.utc)
    stale = stale_guard(av, later)
    assert stale["in_stock"] is None and stale["availability_stale"] is True
    assert stale["last_known_in_stock"] is True and stale["last_known_at"] == checked


def test_timestamps_are_utc_z():
    out = annotate_last_known_window(_firm(), NOW)
    for k in ("last_known_at", "last_known_expires_at", "availability_expires_at"):
        assert out[k].endswith("Z") and "T" in out[k]


def test_compare_brief_shows_window_on_every_row(monkeypatch):
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-26T17:00:00Z")
    lapsed = _lapsed(_firm(checked=FIRM_AT, expires=FIRM_EXPIRES, max_age=1.0, vendor="RunPod"))
    fresh = _firm(checked=VERDA_FRESH, expires=VERDA_FRESH_EXP, vendor="Verda")
    feed = _feed([
        _rate("RunPod", price=1.5, av=lapsed),
        _rate("Verda", price=2.5, av=fresh),
    ])
    brief = compare_gpu_prices(feed, "H100", limit=10, now=NOW)
    brief = contract.finalize("compare_gpu_prices", brief, "brief")
    rows = {r["advertiser"]: r for r in brief["results"]}
    rp, vd = rows["RunPod"], rows["Verda"]
    # Window present on both the lapsed and the firm row
    assert vd["availability_expires_at"] == VERDA_FRESH_EXP
    assert vd["max_age_hours"] == pytest.approx(0.25)
    assert rp["last_known_in_stock"] is True
    assert rp["last_known_expires_at"] == FIRM_EXPIRES
    assert rp["last_known_outside_window"] is True
    assert rp["last_known_expires_at"].endswith("Z")
    # last_known window is not shown on the current firm row in brief (P36: only when in_stock is null)
    assert "last_known_in_stock" not in vd
    # P40 may also add next_check_at / will_backfill; every P68 window key is in the brief contract.
    p68 = {"max_age_hours", "availability_expires_at", "last_known_expires_at",
           "last_known_max_age_hours", "last_known_outside_window"}
    assert p68 <= set(contract.SPEC["compare_gpu_prices"][4])
    import jsonschema
    jsonschema.validate(brief, contract.output_schema("compare_gpu_prices"))


def test_find_available_unknown_row_surfaces_window_and_flag():
    lapsed = _lapsed(_firm(checked=FIRM_AT, expires=FIRM_EXPIRES, max_age=1.0, vendor="RunPod"))
    feed = _feed([_rate("RunPod", gpu="RTX 4090", price=0.4, av=lapsed)])
    out = find_available_gpus(feed, "RTX 4090", now=NOW)
    assert out["available"] == []
    u = out["unknown"][0]
    assert u["last_known_in_stock"] is True
    assert u["last_known_expires_at"] == FIRM_EXPIRES
    assert u["last_known_outside_window"] is True
    assert u["last_known_expires_at"].endswith("Z")
    assert u.get("in_stock") is None  # never a live claim from last_known
    # current-reading window still present (P72); last-known window is the last good 1h one
    assert u.get("availability_expires_at") == "2026-11-27T00:00:00Z"
    assert u["last_known_expires_at"] != u["availability_expires_at"]


def test_no_last_known_does_not_invent_a_flag():
    av = {"status": "unknown", "in_stock": None, "origin": "scout", "availability_reason": "no_source"}
    out = annotate_last_known_window(av, NOW)
    assert "last_known_outside_window" not in out
    assert out.get("last_known_in_stock") not in (True, False)
    assert last_known_window(out) == (None, None)
