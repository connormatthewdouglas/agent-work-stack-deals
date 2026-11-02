import json, pathlib
from core import gpu as G


def test_clore_thin_markets_held_not_ranked():
    d = json.loads(pathlib.Path("data/gpu_pricing/clore.json").read_text())
    for r in d["records"]:
        if r["offer_count"] < G.MIN_MARKET_OFFERS or r["gpu"].startswith(("A100", "H100", "L40S")):
            assert r.get("stale"), r["gpu"]
        assert r["tier_class"] == "marketplace"
        if r["hourly_usd"] is not None:  # held thin groups withhold the price (Gauge Nov 1)
            assert r["lowest_offer_usd"] <= r["hourly_usd"] <= r["highest_offer_usd"]


def test_manual_snapshot_not_auto_refreshed_but_ages_out():
    import copy, importlib.util, sys
    from datetime import datetime, timedelta
    spec = importlib.util.spec_from_file_location("rgp", "scripts/refresh_gpu_prices.py")
    m = importlib.util.module_from_spec(spec); sys.modules["rgp"] = m; spec.loader.exec_module(m)
    d = json.loads(pathlib.Path("data/gpu_pricing/clore.json").read_text())

    class F:
        def get(self, u):
            raise AssertionError("manual snapshot must not be fetched")
    now = datetime.fromisoformat(d["checked_at"])
    a = copy.deepcopy(d); m.refresh([a], F(), now + timedelta(days=1))
    assert [r.get("stale") for r in a["records"]] == [r.get("stale") for r in d["records"]]
    b = copy.deepcopy(d); m.refresh([b], F(), now + timedelta(days=8))
    assert all(r.get("stale") for r in b["records"])


def test_manual_snapshot_fields_in_feed_and_page():
    feed = json.loads(pathlib.Path("api/v1/gpu-prices.json").read_text())
    clore = [r for r in feed["rates"] if r["advertiser"] == "Clore.ai"]
    if not clore:  # all Clore rows held pending a fresh manual snapshot (Nov 1)
        assert "Clore.ai" in {h["vendor"] for h in feed["held_stale"]}
    assert all(r["price_check"] == "manual snapshot" and r["snapshot_at"] and r["hold_after"] for r in clore)
    assert all(r["price_check"] == ("batch" if r.get("last_read") else "daily") for r in feed["rates"] if r["advertiser"] != "Clore.ai")  # G5
    sph = [r for r in feed["rates"] if r["advertiser"] == "Spheron" and r["gpu"] == "RTX 5090"]
    # T73 (2026-11-02): record-level hold while the quoted span is off the page; the held record keeps its source
    sph = sph or [dict(rec, source_url=h["source_url"]) for h in feed["held_stale"] if h["vendor"] == "Spheron"
                  for rec in h["records"] if rec["gpu"] == "RTX 5090"]
    # Nov 1 (Gauge): sourced from the model's own page, a stable span the daily check parses (no longer rotating)
    assert sph and sph[0]["source_url"] == "https://www.spheron.network/gpu-rental/rtx-5090/" and "/hr per GPU" in sph[0]["evidence"]["quote"]
    page = pathlib.Path("gpu/price-comparison/index.html").read_text()
    assert (not clore or "manual snapshot 2026-11-01 22:22 UTC; held after 2026-11-08" in page) and "Price verified (daily)" not in page
