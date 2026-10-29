import json, pathlib
from core import gpu as G


def test_clore_thin_markets_held_not_ranked():
    d = json.loads(pathlib.Path("data/gpu_pricing/clore.json").read_text())
    for r in d["records"]:
        if r["offer_count"] < G.MIN_MARKET_OFFERS or r["gpu"].startswith(("A100", "H100", "L40S")):
            assert r.get("stale"), r["gpu"]
        assert r["tier_class"] == "marketplace"
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
    assert clore and all(r["price_check"] == "manual snapshot" and r["snapshot_at"] and r["hold_after"] for r in clore)
    assert all(r["price_check"] == "daily" for r in feed["rates"] if r["advertiser"] not in ("Clore.ai", "Spheron"))
    sph = [r for r in feed["rates"] if r["advertiser"] == "Spheron" and r["gpu"] == "RTX 5090"]
    assert sph and sph[0]["price_check"] == "rotating snapshot" and "..." not in sph[0]["evidence"]["quote"]
    page = pathlib.Path("gpu/price-comparison/index.html").read_text()
    assert "manual snapshot 2026-10-29 15:27 UTC; held after 2026-11-05" in page and "Price verified (daily)" not in page
