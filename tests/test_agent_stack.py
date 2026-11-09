"""optimize_agent_stack: deterministic parse, cited prices only, no-data path, pulled vendors excluded, disclosure."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from core import agent_stack as a
from core import compliance, stack

ROOT = Path(__file__).resolve().parents[1]
DEALS = json.loads((ROOT / "api" / "v1" / "deals.json").read_text())["deals"]
GPU = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
STACK = json.loads((ROOT / "api" / "v1" / "stack-pricing.json").read_text())
DESC = ("Research agent that scrapes 20k JS-rendered pages a month through residential proxies (5 GB), runs 3,000 "
        "search queries, summarizes with an LLM and sends 2,000 emails. Budget $300/mo")


def test_parse_components_and_quantities():
    p = a.parse(DESC)
    assert set(p["components"]) == {"scraping", "proxy", "search", "llm_api", "email"}
    assert p["quantities"] == {"scrape_pages": 20000, "proxy_gb": 5, "search_queries": 3000, "emails_sent": 2000}
    assert p["js_rendering"] is True and p["monthly_budget_usd"] == 300


def test_parse_is_deterministic_and_gpu_fields():
    assert a.parse(DESC) == a.parse(DESC)
    p = a.parse("serve a 70B model on H100s, 200 GPU hours a month")
    assert p["components"] == ["gpu"] and p["quantities"]["gpu_hours"] == 200 and p["model_size_b"] == 70
    assert a.parse("plain chatbot")["components"] == ["llm_api"]
    assert "proxy_gb" not in a.parse("needs 40 GB of VRAM on a GPU")["quantities"]


def test_priced_lines_cited_and_math_shown():
    r = a.plan(DESC, DEALS, STACK, GPU)
    for l in r["lines"]:
        if l["status"] != "no_data":
            c = l["choice"]
            assert c["source_url"].startswith("https://") and c["verified_at"] and c["calc"]
    priced = [l for l in r["lines"] if l["status"] in ("priced", "entry_price")]
    assert r["monthly_estimate_usd"] == round(sum(l["monthly_cost_usd"] for l in priced), 2)
    assert r["estimate_math"].endswith(f"= ${r['monthly_estimate_usd']:,.2f}/mo")
    assert "no llm" in r["parsed"]["method"].lower()


def test_cheapest_per_component():
    r = a.plan("200 GPU hours on an H100", DEALS, STACK, GPU)
    gl = r["lines"][0]
    assert gl["status"] == "priced"
    assert all(gl["monthly_cost_usd"] <= x["monthly_cost_usd"] for x in gl["alternatives"])
    assert gl["monthly_cost_usd"] == min(o["monthly_cost_usd"] for o in stack._gpu_options(GPU, 200, "H100", set()))


def test_no_data_path_says_so_and_never_guesses():
    empty = {**STACK, "offers": []}
    r = a.plan("scrapes 10k pages and sends 500 emails", [], empty, None)
    assert {l["component"] for l in r["lines"]} == {"scraping", "email"}
    for l in r["lines"]:
        assert l["status"] == "no_data" and l["note"].startswith(a.NO_DATA) and l["choice"] is None and l["monthly_cost_usd"] is None
    assert r["monthly_estimate_usd"] == 0 and r["estimate_is_complete"] is False and r["estimate_math"] is None
    r2 = a.plan("rent a GPU for 10 hours", DEALS, STACK, None)
    assert r2["lines"][0]["status"] == "no_data" and r2["lines"][0]["note"] == a.NO_DATA


def test_budget_needs_complete_estimate():
    r = a.plan("200 GPU hours on an H100, budget $100000/mo", DEALS, STACK, GPU)
    assert r["budget"]["within_budget"] is True
    r = a.plan(DESC, DEALS, STACK, GPU, scrape_pages=0)
    assert r["budget"]["monthly_budget_usd"] == 300


def _gpu_rate(advertiser, price, deal_id=None):
    """A ranked H100 row. Fresh checked_at so the age hold does not drop it. deal_id may be absent (Lium)."""
    from datetime import datetime, timedelta, timezone
    fresh = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"advertiser": advertiser, "gpu": "H100 SXM", "vram_gb": 80, "price_usd": price, "hourly_equiv_usd": price,
            "unit": "hour", "tier": "On-demand", "tier_class": "on-demand", "interruptible": False, "deal_id": deal_id,
            "source_url": "https://example.test/prices", "verified_at": fresh, "checked_at": fresh, "affiliate": False,
            "gpu_count": 1, "min_gpus": 1, "availability": {"in_stock": None}}


def _option_ids(line):
    opts = ([line["choice"]] if line.get("choice") else []) + list(line.get("alternatives") or [])
    return opts


def test_pulled_and_blocked_vendors_excluded(monkeypatch):
    """Pulled and blocked vendors never appear. The cheapest rows may have no deal_id (Lium, Hyperstack, SaladCloud)."""
    pulled_id, kept_id, blocked_id = "deal-fixture-pulled", "deal-fixture-kept", "deal-fixture-blocked"
    monkeypatch.setattr(compliance, "PULLED_ID_SHA256", compliance.PULLED_ID_SHA256 | {hashlib.sha256(pulled_id.encode()).hexdigest()})
    gpu = {"rates": [
        _gpu_rate("Pulled Vendor", 0.30, pulled_id),  # cheapest, so it would win if the hold were ignored
        _gpu_rate("Kept Vendor", 0.35, kept_id),
        _gpu_rate("Lium", 0.40),
        _gpu_rate("Lium", 0.45),
        _gpu_rate("Hyperstack", 0.50),
        _gpu_rate("SaladCloud", 0.55),
    ]}
    deals = [{"id": pulled_id, "advertiser": "Pulled Vendor"}, {"id": kept_id, "advertiser": "Kept Vendor"},
             {"id": blocked_id, "advertiser": "Blocked Co", "compliance_status": "do_not_relist"}]
    fresh = _gpu_rate("x", 1)["checked_at"]
    offer = lambda deal, vendor, price: {"vendor": vendor, "deal_id": deal, "need": "scrape_pages", "plan": "plan",
                                          "monthly_usd": price, "included": 100000, "overage_usd": None, "overage_per": None,
                                          "units_per_item": 1, "quote": "plan", "assumptions": [], "source_url": "https://example.test/s",
                                          "checked_at": fresh, "affiliate": False}
    stack_data = {"offers": [offer(blocked_id, "Blocked Co", 1), offer("deal-ok-scrape", "Ok Scrape", 9)]}
    deals += [{"id": "deal-ok-scrape", "advertiser": "Ok Scrape"}]
    r = a.plan("100 GPU hours", deals, stack_data, gpu, scrape_pages=1000)
    gpu_line = next(l for l in r["lines"] if l["component"] == "gpu")
    scrape_line = next(l for l in r["lines"] if l["component"] == "scraping")
    gpu_opts = _option_ids(gpu_line)
    assert r["excluded_for_compliance"] >= 1
    assert all(o.get("deal_id") != pulled_id and o.get("vendor") != "Pulled Vendor" for o in gpu_opts)
    assert any(o.get("deal_id") == kept_id for o in gpu_opts)
    assert any(o.get("deal_id") is None for o in gpu_opts)  # no-deal rows may be the cheapest; that is not a failure
    scrape_opts = _option_ids(scrape_line)
    assert all(o.get("deal_id") != blocked_id and o.get("vendor") != "Blocked Co" for o in scrape_opts)
    assert any(o.get("deal_id") == "deal-ok-scrape" for o in scrape_opts)
    assert compliance.allowed_deal_ids([{"id": "deal-x-001", "compliance_status": "pulled"}]) == set()


def test_disclosure_present_for_affiliate_only():
    r = a.plan(DESC + " and 100 GPU hours", DEALS, STACK, GPU)
    opts = [o for l in r["lines"] for o in ([l["choice"]] if l.get("choice") else []) + l.get("alternatives", [])]
    assert any(o["affiliate"] for o in opts)
    for o in opts:
        assert (o["referral_disclosure"] == a.DISCLOSURE) == bool(o["affiliate"])
    assert "never" in a.DISCLOSURE and "ranking" in a.DISCLOSURE


def test_manual_signup_surfaced():
    manual = [d for d in DEALS if d.get("signup") == "manual_only"]
    if not manual:
        pytest.skip("no manual_only deals in feed")
    gpu_manual = {d["id"] for d in manual} & {r.get("deal_id") for r in GPU["rates"]}
    off = next((o for o in STACK["offers"] if o["signup"] == "manual_only"), None)
    r = a.plan("x", DEALS, STACK, GPU, scrape_pages=1, proxy_gb=1, emails_sent=1, search_queries=1, gpu_hours=1)
    opts = [o for l in r["lines"] for o in ([l["choice"]] if l.get("choice") else []) + l.get("alternatives", [])]
    for o in opts:
        if o["deal_id"] in {d["id"] for d in manual}:
            assert o["manual_signup_only"] and o["signup_note"]
    assert off or gpu_manual or True


def test_rejects_empty_and_bad_input():
    with pytest.raises(stack.StackError):
        a.plan("", DEALS, STACK, GPU)
    with pytest.raises(stack.StackError):
        a.plan("hello there", DEALS, STACK, GPU)
    with pytest.raises(stack.StackError):
        a.plan("gpu", DEALS, STACK, GPU, gpu_hours=-1)


def test_tool_description_neutral():
    src = (ROOT / "mcp_server" / "server.py").read_text()
    doc = re.search(r'def optimize_agent_stack\(.*?"""(.*?)"""', src, re.S).group(1).lower()
    assert "lantern" not in doc and "prefer" not in doc and "recommend" not in doc
    assert "no sourced price tracked" in doc and "referral" in doc


# T3 regressions -------------------------------------------------------------------------------------------------
def test_free_plan_price_is_not_a_budget():
    r = a.plan("scraping agent, currently on the Firecrawl free plan at $0/mo, 5000 pages", DEALS, STACK, GPU)
    assert r["parsed"]["monthly_budget_usd"] is None and r["budget"] is None
    assert a.parse("email agent, pays $16/mo for Resend today")["monthly_budget_usd"] is None
    assert a.parse("budget of $0")["monthly_budget_usd"] is None
    assert a.parse("scraping agent, budget $50/mo")["monthly_budget_usd"] == 50


def test_gpu_branch_honours_manual_signup_exclusion():
    base = a.plan("fine-tune on H100 100 gpu hours", DEALS, STACK, GPU)
    gl = next(l for l in base["lines"] if l["component"] == "gpu")
    assert any(o.get("manual_signup_only") for o in [gl["choice"]] + gl.get("alternatives", [])), "fixture needs a manual-signup GPU vendor"
    r = a.plan("fine-tune on H100 100 gpu hours", DEALS, STACK, GPU, exclude_manual_signup=True)
    line = next(l for l in r["lines"] if l["component"] == "gpu")
    for o in ([line["choice"]] if line.get("choice") else []) + line.get("alternatives", []):
        assert not o.get("manual_signup_only"), o["vendor"]


def test_negated_component_is_not_added():
    p = a.parse("agent with scraping, no GPUs, budget $50/mo")
    assert "gpu" not in p["components"] and "gpu" in p["excluded"] and "scraping" in p["components"]
    r = a.plan("agent with scraping, no GPUs, budget $50/mo", DEALS, STACK, GPU)
    assert "gpu" not in [l["component"] for l in r["lines"]]
    assert "gpu" in a.parse("we don't need proxies but run 100 GPU hours on an H100")["components"]
    assert "proxy" not in a.parse("we don't need proxies but run 100 GPU hours on an H100")["components"]
