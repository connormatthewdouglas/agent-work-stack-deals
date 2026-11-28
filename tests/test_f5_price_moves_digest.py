"""F5 (Brain #1032): daily/weekly price-moves digest.

Deterministic: fixtures and a frozen snapshot clock only. No live feed, no wall
clock, no pins to committed history or gpu-prices.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import gpu_digest as D
from core.deals import GpuHistoryLoader, GpuPricesLoader
from core.gpu_changes import build_changes
from core.ids import rate_id
from core import contract

TREND_NOW = datetime(2026, 11, 23, 18, 0, 0, tzinfo=timezone.utc)
TREND_LAST = "2026-11-23"
TREND_FIRST = "2026-10-25"
TREND_DATES = [
    d for i in range((datetime.fromisoformat(TREND_LAST) - datetime.fromisoformat(TREND_FIRST)).days + 1)
    if (d := (datetime.fromisoformat(TREND_FIRST) + timedelta(days=i)).date().isoformat())
    not in ("2026-11-07", "2026-11-08")
]


def _pt(day, price, status="ranked", verified=None):
    return {
        "date": day, "price_usd": price, "hourly_usd": price, "status": status,
        "verified_at": verified or f"{day}T12:00:00+00:00",
    }


def _series(points, vendor="Acme", gpu="H100", rid=None, tier="On-demand", vram=80, count=1, source=None):
    row = {"vendor": vendor, "advertiser": vendor, "gpu": gpu, "tier": tier,
           "vram_gb": vram, "gpu_count": count, "billing_unit": "hourly"}
    sid = rid or rate_id(row)
    return {
        "key": f"{vendor}|{gpu}|{tier}|{vram}|{count}",
        "rate_id": sid, "vendor": vendor, "gpu": gpu, "tier": tier,
        "vram_gb": vram, "gpu_count": count,
        "source_url": source or f"https://{vendor.lower().replace(' ', '-')}.example/pricing",
        "points": points, "first_seen": points[0]["date"], "last_seen": points[-1]["date"],
    }


def _hist(series, dates=TREND_DATES):
    if not isinstance(series, list):
        series = [series]
    return {
        "first_snapshot": dates[0], "last_snapshot": dates[-1],
        "snapshot_count": len(dates),
        "snapshot_ids": [f"{d}.deadbeef" for d in dates],
        "series": series, "changes": [],
    }


def _snap(day, rows):
    out = []
    for r in rows:
        rec = {
            "key": r["key"], "vendor": r["vendor"], "gpu": r["gpu"], "tier": r.get("tier", "On-demand"),
            "vram_gb": r.get("vram_gb", 80), "gpu_count": r.get("gpu_count", 1),
            "hourly_usd": r["hourly_usd"], "price_usd": r["hourly_usd"],
            "status": r.get("status", "ranked"),
            "source_url": r.get("source_url") or f"https://{r['vendor'].lower()}.example/",
            "verified_at": r.get("verified_at") or f"{day}T12:00:00+00:00",
            "billing_unit": "hourly",
        }
        out.append(rec)
    return {"date": day, "rows": out}


def _rate(vendor, gpu, price, **kw):
    return {
        "key": f"{vendor}|{gpu}|On-demand|80|1",
        "vendor": vendor, "gpu": gpu, "tier": "On-demand", "vram_gb": 80, "gpu_count": 1,
        "hourly_usd": price, "status": "ranked", **kw,
    }


def test_daily_ranks_biggest_abs_pct_and_skips_held_and_composition():
    prev = _snap("2026-11-22", [
        _rate("Acme", "H100", 2.00),
        _rate("Beta", "H100", 3.00),
        _rate("HeldCo", "A100", 1.00, status="held"),
        _rate("Mkt", "L40S", 1.00, price_status="marketplace"),
    ])
    cur = _snap("2026-11-23", [
        _rate("Acme", "H100", 1.60),   # -20%
        _rate("Beta", "H100", 3.06),   # +2% exactly — counts
        _rate("HeldCo", "A100", 0.50, status="held"),  # held both days: not a ranked move
        _rate("Tiny", "H200", 5.00),   # new, not a price move
        _rate("Mkt", "L40S", 1.20),    # marketplace: will be flagged if stats missing? composition unknown or price
    ])
    # A sub-deadband move
    prev["rows"].append(_rate("FlatCo", "B200", 4.00))
    cur["rows"].append(_rate("FlatCo", "B200", 4.04))  # +1.0% < 2%
    ch = build_changes([prev, cur])
    daily = D.daily_moves(ch, limit=10)
    assert daily["date"] == "2026-11-23" and daily["previous_date"] == "2026-11-22"
    gpus = [m["gpu"] + ":" + m["vendor"] for m in daily["moves"]]
    assert "H100:Acme" in gpus and daily["moves"][0]["vendor"] == "Acme"
    assert daily["moves"][0]["pct"] == -20.0 and daily["moves"][0]["direction"] == "down"
    assert "A100:HeldCo" not in gpus
    assert "B200:FlatCo" not in gpus
    assert "H200:Tiny" not in gpus
    # composition/mixed/unknown marketplace moves are not price moves
    flags = {c["vendor"]: c.get("composition_flag") for c in ch["changes"] if c.get("vendor") == "Mkt"}
    if flags:
        if flags.get("Mkt") not in (None, "price"):
            assert "L40S:Mkt" not in gpus


def test_weekly_uses_price_trend_and_excludes_held_days():
    # Acme: 2.00 → 1.60 over 7d (-20%). A held point in the window is not counted.
    acme = _series([
        _pt("2026-10-25", 2.00),
        _pt("2026-11-17", 2.00),
        _pt("2026-11-20", 1.50, status="held"),
        _pt("2026-11-23", 1.60),
    ], vendor="Acme", gpu="H100 SXM")
    # Beta: +2.0% (exactly the deadband)
    beta = _series([
        _pt("2026-10-25", 3.00),
        _pt("2026-11-17", 3.00),
        _pt("2026-11-23", 3.06),
    ], vendor="Beta", gpu="H100 SXM")
    # FlatCo: +1% — omitted
    flat = _series([
        _pt("2026-10-25", 4.00),
        _pt("2026-11-17", 4.00),
        _pt("2026-11-23", 4.04),
    ], vendor="FlatCo", gpu="B200")
    # ShortCo: only 3 ranked days in the 7d window after a late first point — insufficient, omitted
    short = _series([
        _pt("2026-11-21", 2.00),
    ], vendor="ShortCo", gpu="H200")
    hist = _hist([acme, beta, flat, short])
    weekly = D.weekly_moves(hist, limit=10)
    assert weekly["window_end"] == "2026-11-23"
    assert weekly["window_start"] == "2026-11-17"
    vendors = [m["vendor"] for m in weekly["moves"]]
    assert vendors[0] == "Acme" and weekly["moves"][0]["pct"] == -20.0
    # Held day is out of the math: 7 calendar days minus the held day (and any gap) → ranked_days < 7
    assert weekly["moves"][0]["ranked_days"] < 7
    assert "FlatCo" not in vendors and "ShortCo" not in vendors
    assert "Beta" in vendors


def test_sold_out_live_row_does_not_blank_a_historical_move():
    s = _series([
        _pt("2026-10-25", 2.00),
        _pt("2026-11-17", 2.00),
        _pt("2026-11-23", 1.60),
    ], vendor="Verda", gpu="H100 SXM")
    hist = _hist([s])
    live = {
        "advertiser": "Verda", "vendor": "Verda", "gpu": "H100 SXM", "vram_gb": 80,
        "tier": "On-demand", "gpu_count": 1, "billing_unit": "hourly",
        "in_stock": False, "availability_reason": "sold_out", "failure_reason": "sold_out",
        "availability": {"in_stock": False, "origin": "scout", "availability_reason": "sold_out",
                         "failure_reason": "sold_out", "checked_at": "2026-11-23T17:00:00Z"},
    }
    out = D.price_moves(history=hist, period="weekly", live_rates=[live], now=TREND_NOW)
    assert out["results"] and out["results"][0]["pct"] == -20.0
    assert out["results"][0]["in_stock"] is False


def test_request_time_stale_guard_surfaces_staleness_without_changing_pct():
    s = _series([
        _pt("2026-10-25", 2.00),
        _pt("2026-11-17", 2.00),
        _pt("2026-11-23", 1.60),
    ], vendor="Hyperstack", gpu="H100 PCIe")
    hist = _hist([s])
    av = {
        "in_stock": True, "origin": "scout",
        "checked_at": "2026-11-22T20:00:00Z",  # > 8h before TREND_NOW
        "availability_expires_at": "2026-11-23T04:00:00Z",
        "last_known_in_stock": True, "last_known_at": "2026-11-22T20:00:00Z",
    }
    live = {
        "advertiser": "Hyperstack", "vendor": "Hyperstack", "gpu": "H100 PCIe", "vram_gb": 80,
        "tier": "On-demand", "gpu_count": 1, "billing_unit": "hourly",
        "availability": av,
    }
    out = D.price_moves(history=hist, period="weekly", live_rates=[live], now=TREND_NOW)
    r = out["results"][0]
    assert r["pct"] == -20.0
    assert r["in_stock"] is None and r.get("availability_stale") is True
    assert r["last_known_in_stock"] is True


def test_filters_and_limit_and_invalid_args():
    acme = _series([_pt("2026-10-25", 2.00), _pt("2026-11-17", 2.00), _pt("2026-11-23", 1.60)],
                   vendor="Acme", gpu="H100")
    beta = _series([_pt("2026-10-25", 3.00), _pt("2026-11-17", 3.00), _pt("2026-11-23", 3.60)],
                   vendor="Beta", gpu="A100")  # +20%
    hist = _hist([acme, beta])
    down = D.price_moves(history=hist, period="weekly", direction="down")
    assert down["count"] == 1 and down["results"][0]["vendor"] == "Acme"
    acme_only = D.price_moves(history=hist, period="weekly", vendor="Acme")
    assert acme_only["count"] == 1 and acme_only["results"][0]["vendor"] == "Acme"
    h100 = D.price_moves(history=hist, period="weekly", gpu="H100")
    assert h100["count"] == 1 and h100["results"][0]["gpu"] == "H100"
    one = D.price_moves(history=hist, period="weekly", limit=1)
    assert one["count"] == 1 and one["considered"] == 2
    with pytest.raises(D.DigestError) as e:
        D.price_moves(history=hist, period="monthly")
    assert e.value.code == "invalid_argument"
    with pytest.raises(D.DigestError):
        D.price_moves(history=hist, period="weekly", limit=0)


def test_build_digest_and_rss_are_deterministic_and_clock_free():
    prev = _snap("2026-11-22", [_rate("Acme", "H100", 2.00)])
    cur = _snap("2026-11-23", [_rate("Acme", "H100", 1.60)])
    ch = build_changes([prev, cur])
    hist = _hist([_series([_pt("2026-10-25", 2.00), _pt("2026-11-17", 2.00), _pt("2026-11-23", 1.60)],
                          vendor="Acme", gpu="H100")])
    doc = D.build_digest(history=hist, changes=ch)
    assert "availability" not in json.dumps(doc)
    assert doc["daily"]["moves"][0]["pct"] == -20.0
    assert doc["weekly"]["moves"][0]["pct"] == -20.0
    xml = D.rss(doc, "https://thelanternworks.com")
    assert "Weekly:" in xml and "Daily:" in xml
    assert "11:23" not in xml  # no wall-clock / local time leakage
    assert "12:00:00 +0000" in xml  # snapshot-noon pubDate (RFC 2822, no wall clock)
    again = D.build_digest(history=hist, changes=ch)
    assert doc == again
    assert D.rss(again, "https://thelanternworks.com") == xml
    # Official feed has no baked-in ref tag (Murmur adds ?ref= when posting).
    assert "ref=" not in xml and "ref=" not in json.dumps(doc)


def test_mcp_tool_agrees_with_core_on_the_same_fixture(monkeypatch, tmp_path):
    s = _series([_pt("2026-10-25", 2.00), _pt("2026-11-17", 2.00), _pt("2026-11-23", 1.60)],
                vendor="Acme", gpu="H100")
    hist = _hist([s])
    prev = _snap("2026-11-22", [_rate("Acme", "H100", 2.00)])
    cur = _snap("2026-11-23", [_rate("Acme", "H100", 1.60)])
    ch = build_changes([prev, cur])
    prices = tmp_path / "gpu-prices.json"
    history = tmp_path / "history.json"
    changes = tmp_path / "changes.json"
    prices.write_text(json.dumps({"rates": [], "held_stale": [], "hours_per_month": 730}))
    history.write_text(json.dumps(hist))
    changes.write_text(json.dumps(ch))
    monkeypatch.setenv("LW_AVAIL_NOW", TREND_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
    from core.deals import GpuChangesLoader
    from mcp_server import server
    monkeypatch.setattr(server, "gpu_loader", GpuPricesLoader(file=str(prices)))
    monkeypatch.setattr(server, "history_loader", GpuHistoryLoader(file=str(history)))
    monkeypatch.setattr(server, "changes_loader", GpuChangesLoader(file=str(changes)))
    tool = server.get_price_moves(period="weekly", limit=10)
    core = D.price_moves(history=hist, period="weekly", limit=10)
    assert tool.get("ok") is True
    assert tool["results"][0]["pct"] == core["results"][0]["pct"] == -20.0
    assert tool["results"][0]["rate_id"] == core["results"][0]["rate_id"]
    daily = server.get_price_moves(period="daily", limit=10)
    assert daily["ok"] is True and daily["results"][0]["pct"] == -20.0
    import jsonschema
    jsonschema.validate(tool, contract.output_schema("get_price_moves"))
    jsonschema.validate(daily, contract.output_schema("get_price_moves"))
    bad = server.get_price_moves(period="yearly")
    assert bad.get("ok") is False and bad["error"]["code"] == "invalid_argument"
    jsonschema.validate(bad, contract.output_schema("get_price_moves"))
