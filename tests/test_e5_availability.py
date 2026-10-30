"""E5: availability passes through compare_gpu_prices; out-of-stock rows are demoted (not dropped) and never 'cheapest'."""
import pytest
from core.contract import EXTRA_PROPS
from core.deals import RATE_FIELDS, compare_gpu_prices
from scripts.home_page import spread

OOS = {"status": "out of stock when checked", "in_stock": False, "checked_at": "2026-10-29T15:19:43Z", "note": None}
UNK = {"status": "unknown", "in_stock": None, "checked_at": None, "note": "unknown, not sold out."}


def _row(adv, price, avail="absent", vram=40, tier="On-demand"):
    r = {"advertiser": adv, "gpu": "A100 SXM", "vram_gb": vram, "hourly_equiv_usd": price, "tier": tier,
         "verified_at": "2026-10-29T19:00:00Z", "source_url": "https://example.com"}
    if avail != "absent":
        r["availability"] = avail
    return r


@pytest.fixture
def feed():
    return {"rates": [_row("Verda (formerly DataCrunch)", 0.7965, OOS, tier="Spot instance (1x GPU)"),
                      _row("Lambda", 1.99, UNK), _row("Hyperstack", 1.08)]}


def test_rate_fields_and_schema():
    assert "availability" in RATE_FIELDS
    props = EXTRA_PROPS["compare_gpu_prices"]["results"]["items"]["properties"]
    assert "availability" in props and "null" in props["availability"]["type"]


def test_verda_oos_demoted_not_dropped(feed):
    r = compare_gpu_prices(feed, "A100")
    names = [x["advertiser"] for x in r["results"]]
    assert names == ["Hyperstack", "Lambda", "Verda (formerly DataCrunch)"]
    v = r["results"][-1]
    assert v["availability"] == OOS and v["in_stock"] is False
    assert "out of stock when checked at 2026-10-29T15:19:43Z" in v["availability_note"]
    assert "Hyperstack" in r["summary"].split(".")[0]
    assert "Cheaper but out of stock when checked at 2026-10-29T15:19:43Z" in r["summary"] and "0.7965" in r["summary"]


def test_passthrough_never_invented(feed):
    res = {x["advertiser"]: x for x in compare_gpu_prices(feed, "A100")["results"]}
    assert res["Hyperstack"]["availability"] is None and res["Hyperstack"]["in_stock"] is None
    assert res["Lambda"]["availability"] == UNK and "availability_note" not in res["Lambda"]


def test_all_oos_still_returned():
    r = compare_gpu_prices({"rates": [_row("Verda", 0.7965, OOS)]}, "A100")
    assert r["count"] == 1 and "out of stock when checked" in r["summary"]


def test_home_spread_excludes_oos(feed):
    a = [s for s in spread(feed["rates"]) if s["slug"] == "a100"][0]
    assert a["cheapest_vendor"] == "Hyperstack" and a["min"] == 1.08
    assert "Verda" in a["oos_caveat"] and "$0.7965 out of stock when checked" in a["oos_caveat"]  # F3: digits kept
