import json, pathlib
from core import gpu as G


def test_clore_thin_markets_held_not_ranked():
    d = json.loads(pathlib.Path("data/gpu_pricing/clore.json").read_text())
    for r in d["records"]:
        if r["offer_count"] < G.MIN_MARKET_OFFERS or r["gpu"].startswith(("A100", "H100", "L40S")):
            assert r.get("stale"), r["gpu"]
        assert r["tier_class"] == "marketplace"
        assert r["lowest_offer_usd"] <= r["hourly_usd"] <= r["highest_offer_usd"]
