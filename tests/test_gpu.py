import json
from pathlib import Path
from core.gpu import build_rates, estimate, load_vendor_files

FEED = json.loads((Path(__file__).resolve().parents[1] / "deals.json").read_text())["deals"]


def test_all_specs_verified_against_feed():
    r = build_rates(FEED)
    assert r["problems"] == [] and len(r["rates"]) == sum(len(d["records"]) for d in load_vendor_files())


def test_estimate_hourly_vs_flat_and_rank():
    rates = build_rates(FEED)["rates"]
    e = estimate(rates, 100, gpu_filter="A100")
    assert [x["monthly_cost_usd"] for x in e] == sorted(x["monthly_cost_usd"] for x in e)
    th = next(x for x in e if x["deal_id"] == "deal-thundercompute-001")
    assert th["monthly_cost_usd"] == 109.0
    uc = next(x for x in e if x["deal_id"] == "deal-ucartz-001")
    assert uc["monthly_cost_usd"] == 1564.16 and uc["gpu_count"] == 2  # per GPU of a 2x A100 $3,128.32 server
    e4090 = estimate(rates, 1000, gpu_filter="4090")
    assert next(x for x in e4090 if x["deal_id"] == "deal-ucartz-001")["monthly_cost_usd"] == round(798.72 * 2, 2)
    assert e4090[0]["monthly_cost_usd"] == 340.0  # RunPod Community $0.34/hr x 1000 h


def test_affiliate_not_rank_input():
    rates = build_rates(FEED)["rates"]
    a = [x["deal_id"] + x["gpu"] for x in estimate(rates, 200)]
    b = [x["deal_id"] + x["gpu"] for x in estimate([{**r, "affiliate": not r["affiliate"]} for r in rates], 200)]
    assert a == b


def test_no_commission_fields():
    blob = json.dumps(build_rates(FEED)).lower()
    assert "commission" not in blob and "payout" not in blob


def test_families_threshold_and_runpod():
    from core.gpu import MIN_OFFERS, MIN_VENDORS, families
    rates = build_rates(FEED)["rates"]
    assert any(r["deal_id"] == "deal-runpod-001" for r in rates)
    f = families(rates)
    for v in f.values():
        assert v["page"] == (len(v["rates"]) >= MIN_OFFERS and len(v["vendors"]) >= MIN_VENDORS)
    assert f["h100"]["page"] and f["a100"]["page"] and f["rtx-4090"]["page"]
    assert all(r["verified_at"] for v in f.values() for r in v["rates"])


def test_new_families_and_modal_per_second():
    import json
    from pathlib import Path
    from core.gpu import SERVERLESS, build_rates, families
    deals = json.loads((Path(__file__).resolve().parents[1] / "deals.json").read_text())["deals"]
    data = build_rates(deals)
    assert not data["problems"]
    fams = families(data["rates"])
    for slug in ("h200", "l40s", "rtx-a6000", "rtx-5090"):
        assert fams[slug]["page"], slug
    assert not fams["rtx-3090"]["page"]  # only one verified vendor
    modal = [r for r in data["rates"] if r["tier"] == SERVERLESS]
    assert modal and all(r["billing"] == "per second while running" for r in modal)
    h200 = next(r for r in modal if r["gpu"] == "H200 SXM")
    assert abs(h200["price_usd"] - 0.001261 * 3600) < 1e-4


def test_records_schema_and_compat_fields():
    from core.gpu import RECORD_FIELDS, record_problems
    docs = load_vendor_files()
    assert len(docs) >= 5
    for d in docs:
        assert record_problems(d) == [], d["vendor"]
        for r in d["records"]:
            assert set(RECORD_FIELDS) <= set(r)
    old = {"deal_id", "advertiser", "gpu", "vram_gb", "price_usd", "unit", "tier", "hourly_equiv_usd", "billing",
           "offer_type", "affiliate", "verified_at", "source_url", "redeem_url", "basis"}
    for r in build_rates(FEED)["rates"]:
        assert old <= set(r) and r["source_url"].startswith("https://") and r["checked_at"]
        assert r["unit"] in ("hour", "month") and isinstance(r["interruptible"], bool)
    modal = [r for r in build_rates(FEED)["rates"] if r["billing_unit"] == "per-second"]
    assert modal and all(r["interruptible"] and r["price_per_second_usd"] for r in modal)


def test_record_problems_and_staleness_detected():
    import copy
    from datetime import datetime, timedelta
    from core.gpu import record_problems, stale_records
    doc = copy.deepcopy(next(d for d in load_vendor_files() if len(d["records"]) > 2))
    r = doc["records"][0]
    assert stale_records([doc], now=datetime.fromisoformat(r["checked_at"]) + timedelta(days=6)) == []
    assert stale_records([doc], now=datetime.fromisoformat(r["checked_at"]) + timedelta(days=8))
    r["billing_unit"] = "weekly"; r["interruptible"] = "no"; r["hourly_usd"] = 999
    del doc["records"][-1]["source_url"]
    probs = " ".join(record_problems(doc))
    assert "billing_unit" in probs and "interruptible" in probs and "missing ['source_url']" in probs
    assert build_rates(FEED, [doc])["problems"]


def test_published_api_matches_records():
    api = json.loads((Path(__file__).resolve().parents[1] / "api" / "v1" / "gpu-prices.json").read_text())
    assert api["rates"] == build_rates(FEED)["rates"]
    assert {v["vendor"] for v in api["vendors"]} == {d["vendor"] for d in load_vendor_files()}


def test_gpu_pages_carry_accuracy_notes_and_tracked_wording():
    import re
    root = Path(__file__).resolve().parents[1]
    pages = list((root / "gpu").glob("*/index.html")) + [root / "tools/gpu-cost-calculator/index.html"]
    pages += [root / "compare" / s / "index.html" for s in ("cheap-gpu-rental", "h100-rental-price-comparison", "cheapest-gpu-per-gb-vram",
                                                          "runpod-vs-thunder-compute-vs-modal-h100", "runpod-community-vs-secure-cloud-prices")]
    assert len(pages) >= 12
    for p in pages:
        t = p.read_text()
        for h in ("GPU-hours vs wall-clock time", "Hardware differences", "Egress and storage extras", "Interruptible vs on-demand"):
            assert h in t, (p, h)
        text = re.sub(r"<[^>]+>|https?://\S+", " ", t)
        for m in re.finditer(r"cheapest[^.?\n]{0,80}", text, re.I):
            assert "among tracked" in m.group(0).lower() or "tracked h100" in m.group(0).lower(), (p, m.group(0))


def test_every_record_has_live_evidence():
    import re
    n = 0
    for doc in load_vendor_files():
        for r in doc["records"]:
            ev = r["evidence"]
            assert set(ev) == {"source_url", "quote", "checked_at"}, r["gpu"]
            assert ev["source_url"].startswith("https://") and 0 < len(ev["quote"]) <= 200
            assert ev["checked_at"] == r["checked_at"]
            n += 1
    assert n == 36
    blob = "".join(p.read_text() for p in (Path(__file__).resolve().parents[1] / "data" / "gpu_pricing").glob("*.json"))
    assert "/private" not in blob and "referral_terms" not in blob and not re.search(r"commission|payout", blob, re.I)


def test_multi_gpu_server_is_per_gpu():
    from core.gpu import record_problems
    uc = next(d for d in load_vendor_files() if d["vendor"] == "Ucartz")
    a100 = next(r for r in uc["records"] if r["gpu"] == "A100")
    assert (a100["gpu_count"], a100["price_usd"], a100["hourly_usd"], a100["server_hourly_usd"]) == (2, 3128.32, 2.1427, 4.2854)
    bad = {**uc, "records": [{**a100, "hourly_usd": 4.2854}]}
    assert any("per GPU" in p for p in record_problems(bad))
    bad = {**uc, "records": [{k: v for k, v in a100.items() if k != "server_hourly_usd"}]}
    assert any("server_hourly_usd" in p for p in record_problems(bad))
    bad = {**uc, "records": [{k: v for k, v in a100.items() if k != "evidence"}]}
    assert any("evidence" in p for p in record_problems(bad))
    rate = next(r for r in build_rates(FEED)["rates"] if r["deal_id"] == "deal-ucartz-001" and r["gpu"] == "A100")
    assert (rate["hourly_equiv_usd"], rate["price_usd"], rate["server_price_usd"]) == (2.1427, 1564.16, 3128.32)


def test_compare_tool_and_optimizer_rank_ucartz_per_gpu():
    from core.deals import compare_gpu_prices
    from core.stack import _gpu_options
    data = json.loads((Path(__file__).resolve().parents[1] / "api" / "v1" / "gpu-prices.json").read_text())
    res = compare_gpu_prices(data, "A100", limit=25)["results"]
    uc = next(r for r in res if r["advertiser"] == "Ucartz")
    assert uc["hourly_usd"] == 2.1427 and uc["gpu_count"] == 2 and uc["server_hourly_usd"] == 4.2854
    assert [r["hourly_usd"] for r in res] == sorted(r["hourly_usd"] for r in res)
    opts = _gpu_options(data, 730, "A100", set())
    o = next(x for x in opts if x["vendor"] == "Ucartz")
    assert o["monthly_cost_usd"] == 1564.16 and "2-GPU" in o["calc"]
