"""Agent Stack Optimizer: cited prices only, unknown stays unknown, pulled/manual_only respected."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import stack  # noqa: E402

FEED = json.loads((ROOT / "api" / "v1" / "deals.json").read_text())
DEALS = FEED["deals"] if isinstance(FEED, dict) else FEED
GPU = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
PUB = json.loads((ROOT / "api" / "v1" / "stack-pricing.json").read_text())


def test_records_valid_and_published_matches_build():
    docs = stack.load_vendor_files()
    assert docs and not [p for d in docs for p in stack.record_problems(d)]
    built = stack.build_payload(DEALS)
    assert built["offers"] == PUB["offers"] and built["untracked"] == PUB["untracked"]


def test_every_offer_cited():
    for o in PUB["offers"]:
        assert o["source_url"].startswith("https://") and o["checked_at"][:4] == "2026" and o["quote"].strip()
        assert o["deal_id"] in {d["id"] for d in DEALS}


def test_no_commission_fields_public():
    txt = (ROOT / "api" / "v1" / "stack-pricing.json").read_text().lower()
    assert "commission" not in txt and "payout" not in txt


def offer(**kw):
    base = {"vendor": "V", "deal_id": "deal-v-001", "need": "emails_sent", "plan": "P", "monthly_usd": 10, "included": 1000,
            "overage_usd": 1, "overage_per": 100, "units_per_item": 1, "quote": "q", "assumptions": [], "source_url": "https://v",
            "checked_at": "2026-10-27T00:00:00-04:00", "signup": None, "signup_note": None, "affiliate": False,
            "redeem_url": "https://v", "deal_url": "https://x/deals/deal-v-001/", "min_purchase_usd": None}
    base.update(kw)
    return base


def test_cost_math_and_unknowns():
    assert stack.offer_cost(offer(), 500)["cost"] == 10
    assert stack.offer_cost(offer(), 1050)["cost"] == 11  # 1 pack of 100
    assert stack.offer_cost(offer(min_purchase_usd=20), 1050)["cost"] == 30
    assert "unsuitable" in stack.offer_cost(offer(overage_usd=None, overage_per=None), 5000)
    assert "unknown" in stack.offer_cost(offer(included=None), 5)
    assert "unknown" in stack.offer_cost(offer(units_per_item=None), 5)
    assert stack.offer_cost(offer(units_per_item=5), 300)["cost"] == 15  # 1500 credits


def test_unknown_never_guessed():
    data = {"offers": [offer(vendor="A", included=None)], "untracked": {}, "manual_only_deal_ids": []}
    r = stack.optimize(data, {"emails_sent": 100})
    l = r["lines"][0]
    assert l["status"] == "unknown" and l["monthly_cost_usd"] == "unknown" and l["unknown_price"][0]["vendor"] == "A"
    assert r["total_is_complete"] is False and r["unknown_needs"] == ["emails_sent"]


def test_manual_only_flag_and_exclude():
    data = {"offers": [offer(vendor="M", monthly_usd=1, signup="manual_only"), offer(vendor="N", monthly_usd=5)],
            "untracked": {}, "manual_only_deal_ids": []}
    l = stack.optimize(data, {"emails_sent": 10})["lines"][0]
    assert l["choice"]["vendor"] == "M" and l["choice"]["manual_signup_only"] is True
    l = stack.optimize(data, {"emails_sent": 10}, exclude_manual_signup=True)["lines"][0]
    assert l["choice"]["vendor"] == "N" and l["excluded"][0]["vendor"] == "M"


def test_pulled_deal_dropped():
    docs = stack.load_vendor_files() + [{"vendor": "Gone", "deal_id": "deal-not-in-feed-001", "source_url": "https://g",
                                         "checked_at": "2026-10-27T00:00:00-04:00", "offers": [{k: v for k, v in offer().items() if k in stack.OFFER_FIELDS}]}]
    p = stack.build_payload(DEALS, docs)
    assert "Gone" in p["dropped_vendors"] and all(o["vendor"] != "Gone" for o in p["offers"])


def test_affiliate_not_a_ranking_factor():
    data = {"offers": [offer(vendor="Ref", monthly_usd=9, affiliate=True), offer(vendor="Pub", monthly_usd=8)],
            "untracked": {}, "manual_only_deal_ids": []}
    assert stack.optimize(data, {"emails_sent": 10})["lines"][0]["choice"]["vendor"] == "Pub"


def test_example_stack_real_data():
    r = stack.optimize(PUB, {"scrape_pages": 50000, "proxy_gb": 10, "emails_sent": 10000, "gpu_hours": 100}, GPU, gpu_model="H100")
    assert r["total_is_complete"]
    for l in r["lines"]:
        assert "H100" in l["choice"]["plan"] if l["need"] == "gpu_hours" else True
    gpu = [l for l in r["lines"] if l["need"] == "gpu_hours"][0]
    assert gpu["choice"]["manual_signup_only"] == (gpu["choice"]["deal_id"] in PUB["manual_only_deal_ids"])


def test_bad_inputs():
    for bad in ({}, {"nope": 1}, {"emails_sent": -1}, {"emails_sent": True}, {"emails_sent": 0}):
        with pytest.raises(stack.StackError):
            stack.optimize(PUB, bad, GPU)


def test_page_static_and_tracked():
    html = (ROOT / "tools" / "stack-optimizer" / "index.html").read_text()
    assert '<form id="opt"' in html and " hidden>" in html.split('<form id="opt"')[1][:80]  # form hidden without JS
    assert "cheapest among tracked providers" in html and 'detail:"optimizer"' in html
    assert "Every tracked offer" in html and "unknown" in html and "Manual signup only" in html
    assert "replaceState" not in html and "localStorage" not in html and "document.cookie" not in html
    assert "/tools/stack-optimizer/" in (ROOT / "sitemap.xml").read_text()
