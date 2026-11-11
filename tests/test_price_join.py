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
    import pytest
    # every GPU with a live claim (data-dependent: when all H100 claims have expired, H100 alone has none)
    rs = []
    for g in sorted({x["gpu"] for x in feed["rates"]}):
        try:  # T59: MI250 is reserved-only; gpus=1024 so multi-GPU-only rows rank too (#130)
            rs.extend(deals.compare_gpu_prices(feed, g, limit=25, include_reserved=True, gpus=1024)["results"])
        except deals.DealError:
            continue  # only held or serverless prices: nothing ranked to audit
    claims = [r["availability"] for r in rs if (r.get("availability") or {}).get("in_stock") is not None]
    if not claims:
        pytest.skip("no live stock claim in the committed feed right now")
    assert all("price_at_claim_usd" in a and "price_read_at" in a and "stock_read_at" in a for a in claims)


def test_lambda_8x_claim_price_is_per_gpu(monkeypatch):
    """Gauge T73 F1-F6 #1: an 8x server priced $31.92/h is $3.99 per GPU; the join compares per-GPU prices."""
    key = "Lambda|H100 SXM|On-demand instance (8x GPU)|80|8"
    monkeypatch.setattr(ga, "_SNAP_CACHE", {key: [("2026-11-01T17:46:30+00:00", 3.99)]})
    rec = {"vendor": "Lambda", "gpu": "H100 SXM", "tier": "On-demand instance (8x GPU)", "vram_gb": 80, "gpu_count": 8,
           "billing_unit": "hourly", "price_usd": 31.92, "hourly_usd": 3.99, "verified_at": "2026-11-02T11:57:29+00:00"}
    c = {"in_stock": True, "status": "available when checked", "checked_at": "2026-11-02T12:19:13Z", "origin": "scout"}
    out = ga.price_join_guard(c, rec)
    assert out["in_stock"] is True and out["price_at_claim_usd"] == 3.99 and out["gpu_count"] == 8
    # the per-GPU price moved since the stock read: dropped, even though the server price is still in the record
    monkeypatch.setattr(ga, "_SNAP_CACHE", {key: [("2026-11-02T12:00:00+00:00", 3.79)]})
    rec2 = dict(rec, verified_at="2026-11-02T13:00:00+00:00")
    assert ga.price_join_guard(c, rec2)["in_stock"] is None


def test_feed_claim_prices_are_per_gpu():
    import json
    from pathlib import Path
    feed = json.loads((Path(__file__).resolve().parents[1] / "api/v1/gpu-prices.json").read_text())
    for r in feed["rates"]:
        a = r["availability"]
        if a.get("in_stock") is not None and a.get("price_at_claim_usd") is not None:
            assert abs(a["price_at_claim_usd"] - r["price_usd"]) <= 0.005 + 1e-9, (r["advertiser"], r["gpu"], r["tier"])


def test_expired_claim_keeps_audit_fields():
    from datetime import datetime, timezone
    a = {"in_stock": True, "status": "available when checked", "checked_at": "2026-11-02T10:00:00Z", "origin": "scout",
         "availability_expires_at": "2026-11-02T11:00:00Z", "stock_read_at": "2026-11-02T10:00:00Z",
         "price_read_at": "2026-11-02T09:00:00Z", "price_at_claim_usd": 2.79, "gpu_count": 8}
    out = ga.stale_guard(a, datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
    assert out["availability_stale"] and out["in_stock"] is None
    assert (out["stock_read_at"], out["price_read_at"], out["price_at_claim_usd"], out["gpu_count"]) == (
        "2026-11-02T10:00:00Z", "2026-11-02T09:00:00Z", 2.79, 8)


def test_mcp_brief_rows_add_audit_fields_only():
    from core import contract
    row = {"rank": 1, "rate_id": "r", "advertiser": "Lambda", "gpu": "A100 SXM", "hourly_usd": 2.79, "source_url": "u",
           "in_stock": True, "availability": {"in_stock": True, "stock_read_at": "s", "price_read_at": "p", "price_at_claim_usd": 2.79}}
    out = contract.finalize("compare_gpu_prices", {"gpu": "A100", "summary": "x", "count": 1, "results": [row]}, "brief")
    b = out["results"][0]
    assert (b["stock_read_at"], b["price_read_at"], b["price_at_claim_usd"]) == ("s", "p", 2.79)
    assert "availability" not in b and b["in_stock"] is True  # existing brief keys unchanged


def test_price_change_drop_keeps_firm_dated_claim_as_last_known(monkeypatch):
    """A firm, dated claim dropped because the price changed is kept as last_known_* (not invented)."""
    from datetime import datetime, timezone
    monkeypatch.setattr(ga, "_SNAP_CACHE", {"VendorX|A100 SXM|On-demand|80|1": [("2026-11-01T17:48:57+00:00", 2.248)]})
    rec = _rec(2.27, "2026-11-02T11:59:59+00:00")
    for firm in (True, False):
        c = dict(_claim("2026-11-02T11:38:46Z"), in_stock=firm,
                 status="available when checked" if firm else "out of stock when checked")
        out = ga.price_join_guard(c, rec)
        assert out["in_stock"] is None and out["price_join_failed"] is True  # in_stock still dropped
        assert out["last_known_in_stock"] is firm and out["last_known_at"] == "2026-11-02T11:38:46Z"

    # No check time: the join cannot drop the claim, and last_known is not invented.
    undated = {"in_stock": True, "status": "available when checked", "origin": "scout"}
    out = ga.price_join_guard(undated, rec)
    assert out["in_stock"] is True and not out.get("price_join_failed")
    assert out.get("last_known_in_stock") is None and out.get("last_known_at") is None

    # Already unknown: early return, nothing invented.
    already = {"in_stock": None, "status": "unknown", "checked_at": "2026-11-02T11:38:46Z", "origin": "scout"}
    out = ga.price_join_guard(already, rec)
    assert out is already and out.get("last_known_in_stock") is None


def test_price_change_then_stale_still_keeps_last_known(monkeypatch):
    """The live path: price_join_guard drops the claim, then stale_guard lapses it. last_known must survive."""
    from datetime import datetime, timezone
    monkeypatch.setattr(ga, "_SNAP_CACHE", {"VendorX|A100 SXM|On-demand|80|1": [("2026-11-01T17:48:57+00:00", 2.248)]})
    rec = _rec(2.27, "2026-11-02T11:59:59+00:00")
    c = dict(_claim("2026-11-02T11:38:46Z"), in_stock=True, status="available when checked",
             availability_expires_at="2026-11-02T12:38:46Z")
    dropped = ga.price_join_guard(c, rec)
    assert dropped["in_stock"] is None and dropped["last_known_in_stock"] is True
    later = ga.stale_guard(dropped, datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc))
    assert later["in_stock"] is None and later.get("availability_stale") is True
    assert later["last_known_in_stock"] is True and later["last_known_at"] == "2026-11-02T11:38:46Z"
    from core import deals as core
    assert core.out_of_stock({"availability": later}) is False  # still unknown for ranking
