"""Gauge T73 F1: a stock claim stands only if the price in force at stock-read time is within $0.005 of today's."""
from core import gpu_availability as ga


def _rec(price, at):
    return {"vendor": "VendorX", "gpu": "A100 SXM", "tier": "On-demand", "vram_gb": 80, "gpu_count": 1,
            "price_usd": price, "verified_at": at}


def _claim(at):
    return {"in_stock": False, "status": "out of stock when checked", "checked_at": at, "origin": "scout"}


def test_claim_read_against_older_price_is_dropped(monkeypatch):
    monkeypatch.setattr(ga, "_SNAP_CACHE", {"VendorX|A100 SXM|On-demand|80|1": [("2026-11-01T17:48:57+00:00", 2.248)]})
    out = ga.price_join_guard(_claim("2026-11-02T11:38:46Z"), _rec(2.27, "2026-11-02T11:59:59+00:00"))
    assert out["in_stock"] is None and out["price_join_failed"] is True


def test_claim_within_half_cent_stands(monkeypatch):
    monkeypatch.setattr(ga, "_SNAP_CACHE", {"VendorX|A100 SXM|On-demand|80|1": [("2026-11-01T17:48:57+00:00", 2.266)]})
    c = _claim("2026-11-02T11:38:46Z")
    out = ga.price_join_guard(c, _rec(2.27, "2026-11-02T11:59:59+00:00"))
    assert out["in_stock"] is False and out["price_at_claim_usd"] == 2.266
    assert out["stock_read_at"] == "2026-11-02T11:38:46Z" and out["price_read_at"] == "2026-11-01T17:48:57+00:00"


def test_claim_after_new_price_read_stands(monkeypatch):
    monkeypatch.setattr(ga, "_SNAP_CACHE", {"VendorX|A100 SXM|On-demand|80|1": [("2026-11-01T17:48:57+00:00", 2.248)]})
    c = _claim("2026-11-02T12:10:00Z")
    out = ga.price_join_guard(c, _rec(2.27, "2026-11-02T11:59:59+00:00"))
    assert out["in_stock"] is False and out["price_at_claim_usd"] == 2.27 and out["price_read_at"] == "2026-11-02T11:59:59+00:00"


def test_feed_and_mcp_claims_carry_read_times_and_price():
    import json
    from pathlib import Path
    from core import deals
    feed = json.loads((Path(__file__).resolve().parents[1] / "api/v1/gpu-prices.json").read_text())
    claims = [r["availability"] for r in feed["rates"] if r["availability"].get("in_stock") is not None]
    assert all({"stock_read_at", "price_read_at", "price_at_claim_usd"} <= set(a) for a in claims)
    assert all(a["stock_read_at"] == a["checked_at"] for a in claims)


def test_mcp_compare_output_carries_claim_audit_fields():
    import json
    from pathlib import Path
    from core import deals
    feed = json.loads((Path(__file__).resolve().parents[1] / "api/v1/gpu-prices.json").read_text())
    rs = deals.compare_gpu_prices(feed, "H100", limit=25)["results"]
    claims = [r["availability"] for r in rs if (r.get("availability") or {}).get("in_stock") is not None]
    assert claims and all("price_at_claim_usd" in a and "price_read_at" in a and "stock_read_at" in a for a in claims)
