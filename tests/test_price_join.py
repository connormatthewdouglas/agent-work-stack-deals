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
    assert ga.price_join_guard(c, _rec(2.27, "2026-11-02T11:59:59+00:00")) is c


def test_claim_after_new_price_read_stands(monkeypatch):
    monkeypatch.setattr(ga, "_SNAP_CACHE", {"VendorX|A100 SXM|On-demand|80|1": [("2026-11-01T17:48:57+00:00", 2.248)]})
    c = _claim("2026-11-02T12:10:00Z")
    assert ga.price_join_guard(c, _rec(2.27, "2026-11-02T11:59:59+00:00")) is c
