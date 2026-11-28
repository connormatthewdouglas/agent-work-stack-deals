"""Cross-tool consistency for two Murmur findings on hosted 0.6.6.

1) estimate_job_cost and find_available_gpus must share the P64 request-time
   stale_guard: a lapsed in_stock claim is unknown, never in_stock true.
2) get_price_trend and compare_gpu_prices must agree on history windows for the
   same rate; current sold_out does not blank windows (held/stale days stay out
   of the math).

Deterministic: the same fixture is fed to both tools under a frozen clock.
No live feed, no wall clock, no pins to committed history or gpu-prices.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import gpu_history as H
from core.cost_per_job import estimate_job_cost
from core.deals import GpuHistoryLoader, GpuPricesLoader, compare_gpu_prices, find_available_gpus
from core.ids import rate_id

# After the Hyperstack claim expired (11:11 PM ET Nov 27, 2026 = 2026-11-28T04:11:00Z).
PLANNER_NOW = datetime(2026, 11, 28, 6, 8, 0, tzinfo=timezone.utc)
CLAIM_CHECKED = "2026-11-27T20:11:00Z"  # 3:11 PM ET Nov 27 (8h claim)
CLAIM_EXPIRES = "2026-11-28T04:11:00Z"  # 11:11 PM ET Nov 27
PRICE_FRESH = "2026-11-28T05:00:00Z"    # still fresh for the 48h price-age gate

# F2-style history clock for the sold_out trend case.
TREND_NOW = datetime(2026, 11, 23, 18, 0, 0, tzinfo=timezone.utc)
TREND_LAST = "2026-11-23"
TREND_FIRST = "2026-10-25"  # 30d window ending 2026-11-23 starts this day
TREND_DATES = [
    d for i in range((datetime.fromisoformat(TREND_LAST) - datetime.fromisoformat(TREND_FIRST)).days + 1)
    if (d := (datetime.fromisoformat(TREND_FIRST) + timedelta(days=i)).date().isoformat())
    not in ("2026-11-07", "2026-11-08")
]


def _hyperstack_row(*, expired: bool, in_stock: bool = True) -> dict:
    # Lapsed case uses Murmur's 11:11 PM ET Nov 27 expiry. The still-live control is a
    # fresh check within AVAIL_MAX_AGE_H of PLANNER_NOW (the 8h bar would lapse the
    # Murmur checked_at even if expires_at were pushed later).
    if expired:
        checked, expires = CLAIM_CHECKED, CLAIM_EXPIRES
    else:
        checked, expires = PRICE_FRESH, "2026-11-28T13:00:00Z"
    av = {
        "in_stock": in_stock,
        "origin": "scout",
        "checked_at": checked,
        "availability_expires_at": expires,
        "last_known_in_stock": in_stock,
        "last_known_at": checked,
    }
    return {
        "advertiser": "Hyperstack",
        "vendor": "Hyperstack",
        "gpu": "H100 PCIe",
        "vram_gb": 80,
        "price_usd": 2.40,
        "unit": "hour",
        "hourly_equiv_usd": 2.40,
        "hourly_usd": 2.40,
        "gpu_count": 1,
        "min_gpus": 1,
        "tier": "On-demand",
        "tier_class": "on-demand",
        "interruptible": False,
        "billing_unit": "hourly",
        "price_status": "listed",
        "verified_at": PRICE_FRESH,
        "checked_at": PRICE_FRESH,
        "source_url": "https://hyperstack.example/h100-pcie",
        "availability": av,
    }


def _feed(rates, held=None):
    return {"rates": rates, "held_stale": held or [], "hours_per_month": 730}


def test_lapsed_hyperstack_claim_is_unknown_on_planner_and_finder():
    row = _hyperstack_row(expired=True)
    data = _feed([row])
    found = find_available_gpus(data, "H100 PCIe", now=PLANNER_NOW)
    quote = estimate_job_cost(data, "H100 PCIe", 1, job_hours=1, now=PLANNER_NOW)

    assert found["available"] == [] and found["available_total"] == 0
    stale = [r for r in found["unknown"] if r["advertiser"] == "Hyperstack"]
    assert len(stale) == 1
    u = stale[0]
    assert u["reason"] == "stale" and u["in_stock"] is None
    assert u["availability_stale"] is True
    assert u["last_known_in_stock"] is True
    assert u["last_known_at"].endswith("Z")

    r = quote["results"][0]
    assert r["vendor"] == "Hyperstack"
    assert r["in_stock"] is None
    assert r["availability"]["in_stock"] is None
    assert r["availability"].get("availability_stale") is True
    assert r["availability"]["last_known_in_stock"] is True
    # Cross-tool: the same fixture + clock must not disagree on the live claim.
    assert r["in_stock"] is u["in_stock"]
    assert r["availability"].get("availability_stale") is u["availability_stale"]
    assert r["availability"]["last_known_in_stock"] is u["last_known_in_stock"]


def test_unexpired_hyperstack_claim_is_in_stock_on_both_tools():
    row = _hyperstack_row(expired=False)
    data = _feed([row])
    found = find_available_gpus(data, "H100 PCIe", now=PLANNER_NOW)
    quote = estimate_job_cost(data, "H100 PCIe", 1, job_hours=1, now=PLANNER_NOW)
    assert [r["advertiser"] for r in found["available"]] == ["Hyperstack"]
    assert found["available"][0]["in_stock"] is True
    r = quote["results"][0]
    assert r["in_stock"] is True and r["availability"]["in_stock"] is True
    assert r["availability"].get("availability_stale") is not True


def _pt(day, price, status="ranked", verified=None):
    return {
        "date": day,
        "price_usd": price,
        "hourly_usd": price,
        "status": status,
        "verified_at": verified or f"{day}T12:00:00+00:00",
    }


def _verda_sold_out_fixture():
    """One currently sold-out Verda H100 SXM rate plus enough ranked history for 7d/30d."""
    ts = (TREND_NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    av = {
        "in_stock": False,
        "origin": "scout",
        "checked_at": ts,
        "availability_reason": "sold_out",
        "failure_reason": "sold_out",
        "last_known_in_stock": False,
        "last_known_at": ts,
    }
    row = {
        "advertiser": "Verda",
        "vendor": "Verda",
        "gpu": "H100 SXM",
        "vram_gb": 80,
        "price_usd": 1.80,
        "unit": "hour",
        "hourly_equiv_usd": 1.80,
        "hourly_usd": 1.80,
        "gpu_count": 1,
        "min_gpus": 1,
        "tier": "On-demand",
        "tier_class": "on-demand",
        "interruptible": False,
        "billing_unit": "hourly",
        "price_status": "listed",
        "verified_at": ts,
        "checked_at": ts,
        "source_url": "https://verda.example/h100-sxm",
        "availability": av,
        "availability_reason": "sold_out",
        "in_stock": False,
        "failure_reason": "sold_out",
    }
    rid = rate_id(row)
    # Ranked change points spanning 30d; one held day in the 7d window stays out of the math.
    points = [
        _pt("2026-10-25", 2.00),
        _pt("2026-11-17", 2.00),
        _pt("2026-11-20", 1.90, status="held"),  # held day: not counted
        _pt("2026-11-23", 1.80),
    ]
    series = {
        "key": "Verda|H100 SXM|On-demand|80|1",
        "rate_id": rid,
        "vendor": "Verda",
        "gpu": "H100 SXM",
        "tier": "On-demand",
        "vram_gb": 80,
        "gpu_count": 1,
        "points": points,
        "first_seen": points[0]["date"],
        "last_seen": points[-1]["date"],
    }
    hist = {
        "first_snapshot": TREND_DATES[0],
        "last_snapshot": TREND_DATES[-1],
        "snapshot_count": len(TREND_DATES),
        "snapshot_ids": [f"{d}.deadbeef" for d in TREND_DATES],
        "series": [series],
        "changes": [],
    }
    return row, rid, series, hist


def _window_core(windows):
    return {
        w["days"]: {k: w[k] for k in ("days", "pct", "direction", "start_usd", "end_usd", "ranked_days") if k in w}
        for w in windows
    }


def test_sold_out_verda_trend_windows_agree_on_compare_and_get_price_trend():
    row, rid, series, hist = _verda_sold_out_fixture()
    data = _feed([row])
    compared = compare_gpu_prices(data, "H100 SXM", 5, history=hist, now=TREND_NOW, on_demand_only=False)
    assert compared["results"] and compared["results"][0]["rate_id"] == rid
    cmp_tr = compared["results"][0]["trend"]
    assert cmp_tr and cmp_tr.get("trend_reason") != "sold_out"
    assert cmp_tr["windows"], "compare must surface 7d/30d windows despite current sold_out"

    direct = H.price_trend(series, history=hist, live=row, held=False, now=TREND_NOW, windows=[7, 30])
    assert direct.get("trend_reason") != "sold_out"
    assert _window_core(cmp_tr["windows"]) == _window_core(direct["windows"])

    # Held day in the 7d window is excluded from ranked_days (Frosty: held/stale days stay out).
    by_days = {w["days"]: w for w in direct["windows"]}
    assert "pct" in by_days[7] and by_days[7]["ranked_days"] < 7
    assert "pct" in by_days[30]


def test_mcp_tools_agree_on_the_same_sold_out_fixture(monkeypatch, tmp_path):
    row, rid, series, hist = _verda_sold_out_fixture()
    prices = tmp_path / "gpu-prices.json"
    history = tmp_path / "history.json"
    prices.write_text(json.dumps(_feed([row])))
    history.write_text(json.dumps(hist))
    monkeypatch.setenv("LW_AVAIL_NOW", TREND_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
    from mcp_server import server
    monkeypatch.setattr(server, "gpu_loader", GpuPricesLoader(file=str(prices)))
    monkeypatch.setattr(server, "history_loader", GpuHistoryLoader(file=str(history)))
    compared = server.compare_gpu_prices("H100 SXM", limit=5, on_demand_only=False)
    trend = server.get_price_trend(rid, windows=[7, 30])
    assert compared.get("ok") is not False
    assert trend.get("ok") is True
    assert trend.get("trend_reason") != "sold_out"
    assert trend["windows"]
    cmp_tr = compared["results"][0]["trend"]
    assert cmp_tr.get("trend_reason") != "sold_out"
    assert compared["results"][0]["rate_id"] == rid == trend["rate_id"]
    assert _window_core(cmp_tr["windows"]) == _window_core(trend["windows"])
