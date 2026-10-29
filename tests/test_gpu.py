import json
from pathlib import Path
from core.gpu import build_rates, estimate, load_vendor_files

FEED = json.loads((Path(__file__).resolve().parents[1] / "deals.json").read_text())["deals"]


def _rec(vendor, gpu, tier=None):
    """Current record (prices refresh daily, so tests derive expectations from the data, not pinned numbers)."""
    return next(r for d in load_vendor_files() if d["vendor"] == vendor for r in d["records"]
                if r["gpu"] == gpu and (tier is None or r["tier"] == tier))


def test_all_specs_verified_against_feed():
    r = build_rates(FEED)
    live = [d for d in load_vendor_files() if not d.get("stale")]
    assert r["problems"] == [] and len(r["rates"]) == sum(1 for d in live for x in d["records"] if not x.get("stale"))


def test_estimate_hourly_vs_flat_and_rank():
    rates = build_rates(FEED)["rates"]
    e = estimate(rates, 100, gpu_filter="A100")
    key = [(x["tier_class"] == "reserved", x["monthly_cost_usd"]) for x in e]
    assert key == sorted(key) and e[0]["tier_class"] != "reserved"  # reservations never rank first
    th = next(x for x in e if x["deal_id"] == "deal-thundercompute-001")
    assert th["monthly_cost_usd"] == round(_rec("Thunder Compute", "A100")["hourly_usd"] * 100, 2)
    uc = next(x for x in e if x["deal_id"] == "deal-ucartz-001")
    a100 = _rec("Ucartz", "A100")
    # T35: whole servers only. 1 GPU on a 2x A100 monthly server bills the full server (2 GPUs), not half of it.
    assert uc["monthly_cost_usd"] == round(round(a100["price_usd"] / 2, 2) * 2, 2) and uc["gpu_count"] == 2
    e4090 = estimate(rates, 1000, gpu_filter="4090")
    assert next(x for x in e4090 if x["deal_id"] == "deal-ucartz-001")["monthly_cost_usd"] == round(_rec("Ucartz", "RTX 4090")["price_usd"] * 2, 2)
    assert [x["monthly_cost_usd"] for x in e4090] == sorted(x["monthly_cost_usd"] for x in e4090)


def test_affiliate_not_rank_input():
    rates = build_rates(FEED)["rates"]
    a = [(x["advertiser"], x["gpu"], x["tier"]) for x in estimate(rates, 200)]
    b = [(x["advertiser"], x["gpu"], x["tier"]) for x in estimate([{**r, "affiliate": not r["affiliate"]} for r in rates], 200)]
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
    assert abs(h200["price_usd"] - _rec("Modal", "H200 SXM")["price_usd"] * 3600) < 1e-4


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
    doc["records"] = doc["records"][:3]
    for x in doc["records"]:
        x.pop("stale", None)
        x["verified_at"] = x["checked_at"] = doc["records"][0]["checked_at"]
    r = doc["records"][0]
    assert stale_records([doc], now=datetime.fromisoformat(r["verified_at"]) + timedelta(days=6)) == []
    assert stale_records([doc], now=datetime.fromisoformat(r["verified_at"]) + timedelta(days=8))
    r["billing_unit"] = "weekly"; r["interruptible"] = "no"; r["hourly_usd"] = 999
    del doc["records"][-1]["source_url"]
    probs = " ".join(record_problems(doc))
    assert "billing_unit" in probs and "interruptible" in probs and "missing ['source_url']" in probs
    assert build_rates(FEED, [doc])["problems"]


def test_published_api_matches_records():
    api = json.loads((Path(__file__).resolve().parents[1] / "api" / "v1" / "gpu-prices.json").read_text())
    assert api["rates"] == build_rates(FEED)["rates"]
    assert {v["vendor"] for v in api["vendors"]} == {d["vendor"] for d in load_vendor_files() if not d.get("stale")}
    held = {d["vendor"] for d in load_vendor_files() if d.get("stale") or any(r.get("stale") for r in d["records"])}
    assert {h["vendor"] for h in api["held_stale"]} == held


def test_gpu_pages_carry_accuracy_notes_and_tracked_wording():
    import re
    root = Path(__file__).resolve().parents[1]
    pages = [p for p in (root / "gpu").glob("*/index.html") if p.parent.name not in ("free-credits", "index")] + [root / "tools/gpu-cost-calculator/index.html"]
    pages += [root / "compare" / s / "index.html" for s in ("cheap-gpu-rental", "cheapest-gpu-per-gb-vram",
                                                          "runpod-vs-thunder-compute-vs-modal-h100", "runpod-community-vs-secure-cloud-prices")]
    assert len(pages) >= 11
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
            assert set(ev) in ({"source_url", "quote", "checked_at"}, {"source_url", "quote", "checked_at", "interruption_quote", "interruption_source_url", "interruption_checked_at"}), r["gpu"]
            assert ev["source_url"].startswith("https://") and 0 < len(ev["quote"]) <= 200
            assert ev["checked_at"] == (r.get("verified_at") or r["checked_at"])  # evidence = last parsed price
            from datetime import datetime
            assert datetime.fromisoformat(r["checked_at"]) >= datetime.fromisoformat(ev["checked_at"])
            n += 1
    assert n == 119  # + RTX 4090 depth 2026-10-29: Nova Cloud 1, RunC.AI 1, held Genesis Cloud/SimplePod/Runcrate/Beam 4; + Clore.ai 5 (3 held thin) + Gauge L40S/RTX 5090 coverage 10 (Massed Compute pulled 2026-10-29, OVHcloud 1, Koyeb 1, CloudRift 6, Spheron 2; Crusoe/Lightning AI pulled); 36 original + Lambda 13 + TensorDock 10 (held stale) + Vast 2 + Verda 12 + Nebius 3 + DigitalOcean 4 + CoreWeave 5 + SaladCloud 1 + Novita 1 + Hyperstack 12 - Ucartz Radeon 780M 1 (integrated GPU)
    blob = "".join(p.read_text() for p in (Path(__file__).resolve().parents[1] / "data" / "gpu_pricing").glob("*.json"))
    assert "/private" not in blob and "referral_terms" not in blob and not re.search(r"commission|payout", blob, re.I)


def test_multi_gpu_server_is_per_gpu():
    from core.gpu import record_problems
    uc = next(d for d in load_vendor_files() if d["vendor"] == "Ucartz")
    a100 = next(r for r in uc["records"] if r["gpu"] == "A100")
    p = a100["price_usd"]
    assert (a100["gpu_count"], a100["hourly_usd"], a100["server_hourly_usd"]) == (2, round(p / 730 / 2, 4), round(p / 730, 4))
    bad = {**uc, "records": [{**a100, "hourly_usd": a100["server_hourly_usd"]}]}
    assert any("per GPU" in p for p in record_problems(bad))
    bad = {**uc, "records": [{k: v for k, v in a100.items() if k != "server_hourly_usd"}]}
    assert any("server_hourly_usd" in p for p in record_problems(bad))
    bad = {**uc, "records": [{k: v for k, v in a100.items() if k != "evidence"}]}
    assert any("evidence" in p for p in record_problems(bad))
    rate = next(r for r in build_rates(FEED)["rates"] if r["deal_id"] == "deal-ucartz-001" and r["gpu"] == "A100")
    assert (rate["hourly_equiv_usd"], rate["price_usd"], rate["server_price_usd"]) == (a100["hourly_usd"], round(p / 2, 2), p)


def test_compare_tool_and_optimizer_rank_ucartz_per_gpu():
    from core.deals import compare_gpu_prices
    from core.stack import _gpu_options
    data = json.loads((Path(__file__).resolve().parents[1] / "api" / "v1" / "gpu-prices.json").read_text())
    res = compare_gpu_prices(data, "A100", limit=25)["results"]
    uc = next(r for r in res if r["advertiser"] == "Ucartz")
    a100 = _rec("Ucartz", "A100")
    assert uc["hourly_usd"] == a100["hourly_usd"] and uc["gpu_count"] == 2 and uc["server_hourly_usd"] == a100["server_hourly_usd"]
    assert [(r["in_stock"] is False, r["hourly_usd"]) for r in res] == sorted((r["in_stock"] is False, r["hourly_usd"]) for r in res)  # E5: out-of-stock last
    opts = _gpu_options(data, 730, "A100", set())
    o = next(x for x in opts if x["vendor"] == "Ucartz")
    # T35: whole servers only. The optimizer bills the full 2x A100 server for 1 GPU.
    assert o["monthly_cost_usd"] == round(round(a100["price_usd"] / 2, 2) * 2, 2) and "2-GPU" in o["calc"]


def test_new_vendor_flags():
    from core.deals import compare_gpu_prices
    from core.stack import _gpu_options
    from core.gpu import record_problems
    root = Path(__file__).resolve().parents[1]
    api = json.loads((root / "api" / "v1" / "gpu-prices.json").read_text())
    rates = api["rates"]
    # TensorDock: stale, held out of every ranking surface
    td = [h for h in api["held_stale"] if h["vendor"] == "TensorDock"]
    assert len(td) == 1 and td[0]["page_last_updated"] == "2024-07-24"
    assert not any(r["advertiser"] == "TensorDock" for r in rates)
    for g in ("RTX 4090", "A100", "H100", "V100"):
        assert all(r["advertiser"] != "TensorDock" for r in compare_gpu_prices(api, g, limit=25)["results"])
    assert all(o["vendor"] != "TensorDock" for o in _gpu_options(api, 100, None, set()))
    for page in ("gpu/price-comparison/index.html", "gpu/cheapest-rtx-4090-rental/index.html"):
        f = root / page
        if f.exists():
            body = f.read_text().split("</head>")[1]
            assert "TensorDock" not in body.split("Held out")[0], page
    # Vast: 3 marketplace medians (no H100), tied to the existing affiliate deal, labeled with lowest offer
    vast = [r for r in rates if r["advertiser"] == "Vast.ai"]
    assert {r["gpu"] for r in vast} <= {"RTX 4090", "A100 SXM"}  # a market below 5 qualifying offers is auto-held
    for r in vast:
        x = _rec("Vast.ai", r["gpu"])
        assert (r["hourly_equiv_usd"], r["lowest_offer_usd"], r["offer_count"]) == (x["hourly_usd"], x["lowest_offer_usd"], x["offer_count"])
    assert all('"verified":{"eq":true}' in __import__("urllib.parse").parse.unquote(r["source_url"]) for r in vast)
    assert all(r["deal_id"] == "deal-vastai-001" and r["price_status"] == "marketplace"
               and r["lowest_offer_usd"] <= r["hourly_equiv_usd"] and r["offer_count"] >= 5 for r in vast)
    if vast:
        res = compare_gpu_prices(api, "RTX 4090", limit=25)["results"]
        v = next(r for r in res if r["advertiser"] == "Vast.ai")
        assert v["price_status"] == "marketplace" and v["lowest_offer_usd"] == _rec("Vast.ai", "RTX 4090")["lowest_offer_usd"]
        o = next(x for x in _gpu_options(api, 100, "RTX 4090", set()) if x["vendor"] == "Vast.ai")
        assert any("marketplace" in a for a in o["assumptions"])
    doc = next(d for d in load_vendor_files() if d["vendor"] == "Vast.ai")
    thin = {**doc, "records": [{**doc["records"][0], "offer_count": 4}]}
    assert any("offer_count" in p for p in record_problems(thin))
    # Lambda: 13 records, no deal (links to vendor page), 8x-only instances charge 8 GPUs
    lam = [r for r in rates if r["advertiser"] == "Lambda"]
    assert len(lam) == 13 - sum(1 for d in load_vendor_files() if d["vendor"] == "Lambda" for r in d["records"] if r.get("stale")) and all(r["deal_id"] is None and not r["affiliate"] and r["redeem_url"] == "https://lambda.ai/pricing" for r in lam)
    e = estimate(rates, 100, gpu_filter="V100")
    v100 = next(x for x in e if x["advertiser"] == "Lambda")
    assert v100["monthly_cost_usd"] == round(_rec("Lambda", "V100")["hourly_usd"] * 100 * 8, 2) and "8-GPU" in v100["calc"]


def test_marketplace_hold_is_automatic_and_tracks_offer_count():
    """Vast records follow the automatic rule: ranked iff >= MIN_MARKET_OFFERS qualifying offers, else held (auto)."""
    from core.deals import compare_gpu_prices
    from core.gpu import MIN_MARKET_OFFERS
    from core.stack import _gpu_options
    api = json.loads((Path(__file__).resolve().parents[1] / "api" / "v1" / "gpu-prices.json").read_text())
    vast = next(d for d in load_vendor_files() if d["vendor"] == "Vast.ai")
    for r in vast["records"]:
        ranked = any(x["advertiser"] == "Vast.ai" and x["gpu"] == r["gpu"] for x in api["rates"])
        held = any(h["vendor"] == "Vast.ai" and h["records"][0]["gpu"] == r["gpu"] for h in api["held_stale"])
        if r.get("stale"):
            assert r["stale"].get("auto") is True and "too thin" in r["stale"]["reason"].lower() or "not re-verified" in r["stale"]["reason"]
            assert held and not ranked
            assert all(not (x["advertiser"] == "Vast.ai" and x["gpu"] == r["gpu"])
                       for x in compare_gpu_prices(api, r["gpu"].split()[0], limit=25)["results"])
            assert all(not (o["vendor"] == "Vast.ai" and r["gpu"] in o.get("plan", "")) for o in _gpu_options(api, 100, r["gpu"].split()[0], set()))
        else:
            assert r["offer_count"] >= MIN_MARKET_OFFERS and ranked and not held
            assert f"{r['offer_count']} verified" in r["evidence"]["quote"] and f"${r['hourly_usd']:.4f}" in r["evidence"]["quote"]


def test_record_level_stale_needs_reason():
    from core.gpu import record_problems
    doc = json.loads((Path(__file__).resolve().parents[1] / "data" / "gpu_pricing" / "vast.json").read_text())
    doc["records"][0]["stale"] = {}
    assert any("stale needs a reason" in p for p in record_problems(doc))


def test_whole_server_billing_9_gpus_on_8_gpu_h100_bills_16():
    """T35: 9 GPUs on an 8-GPU server row must bill two whole servers (16 GPUs), never 9."""
    from core import gpu as _gpu, stack as _stack
    row = {"advertiser": "X", "gpu": "H100", "vram_gb": 80, "price_usd": 2.0, "unit": "hour", "gpu_count": 8,
           "min_gpus": 8, "server_price_usd": 16.0, "tier": "On-demand", "tier_class": "on_demand", "deal_id": None}
    est = _gpu.estimate([row], 10, gpus=9)[0]
    assert est["monthly_cost_usd"] == 2.0 * 10 * 16
    assert "9 requested" in est["calc"] and "16 billed" in est["calc"]
    assert _gpu.estimate([row], 10, gpus=8)[0]["monthly_cost_usd"] == 2.0 * 10 * 8
    opt = _stack._gpu_options({"rates": [row]}, 10, None, set(), gpus=9)[0]
    assert opt["monthly_cost_usd"] == 2.0 * 10 * 16
    assert "9 requested" in opt["calc"] and "16 billed" in opt["calc"]
    assert _stack._gpu_options({"rates": [row]}, 10, None, set())[0]["monthly_cost_usd"] == 2.0 * 10 * 8



def test_cheapest_pages_canonical_to_rental_price_page():
    import re, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    sitemap = (root / "sitemap.xml").read_text()
    pages = sorted((root / "gpu").glob("cheapest-*-rental/index.html"))
    assert pages
    for p in pages:
        m = re.search(r'<link rel="canonical" href="https://thelanternworks.com/(gpu/[^"]+-rental-price/)"', p.read_text())
        assert m, p
        assert (root / m.group(1) / "index.html").exists(), m.group(1)
        assert f"/gpu/{p.parent.name}/" not in sitemap
    for p in sorted((root / "gpu").glob("*-rental-price/index.html")):
        assert f'<link rel="canonical" href="https://thelanternworks.com/gpu/{p.parent.name}/"' in p.read_text()
        assert f"/gpu/{p.parent.name}/" in sitemap


def test_tier_labels_ascii_normalized():
    import json
    from pathlib import Path
    from core.gpu import normalize_tier
    assert normalize_tier("On\u2011Demand") == "On-demand"
    assert normalize_tier("Spot") == "Spot"
    feed = json.loads((Path(__file__).resolve().parents[1] / "api/v1/gpu-prices.json").read_text(encoding="utf-8"))
    for r in feed["rates"]:
        assert r["tier"] == normalize_tier(r["tier"]), r["tier"]
    assert not any(u["deal_id"] == "deal-cloreai-001" for u in feed.get("unpriced", []))
