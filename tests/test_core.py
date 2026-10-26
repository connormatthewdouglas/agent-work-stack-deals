import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core import DealError, FeedLoader, compare, get_deal, search
from core.deals import PUBLIC_FIELDS

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


def D(i, **kw):
    base = {"id": i, "title": f"{i} deal", "advertiser": i.title(), "category": "search", "tags": [],
            "offer_type": "standard_referral", "affiliate": False, "price_usd": None,
            "verified_at": None, "redeem_url": f"https://{i}.test"}
    base.update(kw)
    return base


DEALS = [
    D("aff", affiliate=True, commission_pct=50, payout="$100"),
    D("free", offer_type="free_tier", price_usd=0, tags=["api"]),
    D("disc", offer_type="verified_discount", price_usd=20, verified_at="2026-10-20T00:00:00Z", tags=["api", "proxy"]),
    D("cheap", price_usd=5, category="email"),
    D("old", offer_type="verified_discount", price_usd=20, verified_at="2025-01-01T00:00:00Z"),
]


def test_rank_customer_value_not_affiliate():
    ids = [r["id"] for r in search(DEALS, now=NOW)["results"]]
    assert ids[:3] == ["disc", "old", "free"]
    assert ids.index("aff") > ids.index("cheap")  # affiliate gives no boost


def test_affiliate_flag_does_not_change_rank():
    a = [r["id"] for r in search(DEALS, now=NOW)["results"]]
    flipped = [dict(d, affiliate=not d["affiliate"]) for d in DEALS]
    assert [r["id"] for r in search(flipped, now=NOW)["results"]] == a


def test_filters():
    assert [r["id"] for r in search(DEALS, category="email")["results"]] == ["cheap"]
    assert {r["id"] for r in search(DEALS, max_price=10)["results"]} == {"free", "cheap"}
    assert [r["id"] for r in search(DEALS, tags=["api", "proxy"])["results"]] == ["disc"]
    assert [r["id"] for r in search(DEALS, offer_type="free_tier")["results"]] == ["free"]
    assert search(DEALS, query="nomatchzzz")["total"] == 0
    assert search(DEALS, query="cheap")["results"][0]["id"] == "cheap"


def test_pagination():
    p1 = search(DEALS, limit=2, now=NOW)
    p2 = search(DEALS, limit=2, cursor=p1["next_cursor"], now=NOW)
    p3 = search(DEALS, limit=2, cursor=p2["next_cursor"], now=NOW)
    ids = [r["id"] for p in (p1, p2, p3) for r in p["results"]]
    assert sorted(ids) == sorted(d["id"] for d in DEALS) and p3["next_cursor"] is None


@pytest.mark.parametrize("kw,code", [({"offer_type": "x"}, "invalid_argument"), ({"limit": 0}, "invalid_argument"),
                                     ({"limit": 26}, "invalid_argument"), ({"cursor": "!!"}, "invalid_cursor"),
                                     ({"max_price": -1}, "invalid_argument")])
def test_search_errors(kw, code):
    with pytest.raises(DealError) as e:
        search(DEALS, **kw)
    assert e.value.code == code


def test_no_private_fields():
    d = get_deal(DEALS, "aff")
    assert "commission_pct" not in d and "payout" not in d
    assert set(d) <= set(PUBLIC_FIELDS)
    for r in search(DEALS)["results"] + compare(DEALS, ["aff", "free"])["deals"]:
        assert not any(k.startswith(("commission", "payout")) for k in r)


def test_get_and_compare_errors():
    with pytest.raises(DealError) as e:
        get_deal(DEALS, "nope")
    assert e.value.code == "not_found"
    for ids in (["free"], ["a", "b", "c", "d", "e", "f"], ["free", "free"]):
        with pytest.raises(DealError):
            compare(DEALS, ids)
    with pytest.raises(DealError) as e:
        compare(DEALS, ["free", "zzz"])
    assert e.value.code == "not_found"
    assert [d["id"] for d in compare(DEALS, ["cheap", "disc"])["deals"]] == ["disc", "cheap"]


def test_loader_file_and_examples(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"deals": [D("x"), D("y", example=True)]}))
    assert [d["id"] for d in FeedLoader(file=str(p)).deals()] == ["x"]
    with pytest.raises(DealError) as e:
        FeedLoader(file=str(tmp_path / "missing.json")).load()
    assert e.value.code == "feed_unavailable"


def test_real_feed_snapshot_is_public_clean():
    feed = Path(__file__).resolve().parents[1] / "api" / "v1" / "deals.json"
    deals = FeedLoader(file=str(feed)).deals()
    r = search(deals, limit=25)
    assert r["total"] == len(deals) and r["count"] == 25
    assert r["results"][0]["offer_type"] in ("verified_discount", "free_tier")
