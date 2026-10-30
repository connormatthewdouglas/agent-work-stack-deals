"""Gauge re28: by default a price older than 168 h never ranks or heads 'cheapest'; it is listed separately as
'stale price (N days old)'. If every candidate is stale no current cheapest is named. max_data_age_hours overrides."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import agent_stack, cost_per_job, data_age, stack
from core.deals import compare_gpu_prices
from core.gpu import build_rates, load_vendor_files

ROOT = Path(__file__).resolve().parents[1]
GPU = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
DEALS = json.loads((ROOT / "api" / "v1" / "deals.json").read_text())["deals"]
STACK = json.loads((ROOT / "api" / "v1" / "stack-pricing.json").read_text())
NOW = datetime.now(timezone.utc)


def _iso(h):
    return (NOW - timedelta(hours=h)).isoformat()


def _row(vendor, hours_old, price, tier="On-demand"):
    return {"advertiser": vendor, "gpu": "H100 PCIe", "vram_gb": 80, "hourly_equiv_usd": price, "price_usd": price,
            "unit": "hour", "tier": tier, "tier_class": "on_demand", "interruptible": False, "billing_unit": "hourly",
            "billing": "per hour while running", "verified_at": _iso(hours_old), "checked_at": _iso(hours_old),
            "source_url": f"https://example.com/{vendor}", "deal_id": None, "gpu_count": 1, "min_gpus": 1}


AGED = {"rates": [_row("Aged", 717, 1.99), _row("Fresh", 2, 2.50), _row("Fresh2", 5, 2.75)]}
ALL_AGED = {"rates": [_row("Aged", 717, 1.99), _row("Aged2", 300, 2.50)]}


def test_compare_aged_cheapest_not_headline():
    out = compare_gpu_prices(AGED, "H100", now=NOW)
    assert [r["advertiser"] for r in out["results"]] == ["Fresh", "Fresh2"]
    assert "Fresh" in out["summary"].split(".")[0] and "Aged" not in out["summary"].split(".")[0]
    assert out["excluded_stale"] == 1 and out["stale_prices"][0]["vendor"] == "Aged"
    assert out["stale_prices"][0]["label"] == "stale price (30 days old)"
    assert "not ranked" in out["summary"]


def test_compare_all_stale_names_no_cheapest():
    out = compare_gpu_prices(ALL_AGED, "H100", now=NOW)
    assert out["results"] == [] and out["count"] == 0 and out["ok_current"] is False
    assert "no current cheapest" in out["summary"] and "Cheapest among" not in out["summary"]
    assert [s["vendor"] for s in out["stale_prices"]] == ["Aged", "Aged2"]


def test_override_ranks_aged_rows():
    out = compare_gpu_prices(AGED, "H100", max_data_age_hours=1000, now=NOW)
    assert out["results"][0]["advertiser"] == "Aged" and out["results"][0]["stale"] is True


def test_estimate_job_cost_aged():
    out = cost_per_job.estimate_job_cost(AGED, "H100", 1, job_hours=10, now=NOW)
    assert out["results"][0]["vendor"] == "Fresh" and out["stale_prices"][0]["vendor"] == "Aged"
    allx = cost_per_job.estimate_job_cost(ALL_AGED, "H100", 1, job_hours=10, now=NOW)
    assert allx["results"] == [] and "no current cheapest" in allx["summary"]
    o = cost_per_job.estimate_job_cost(AGED, "H100", 1, job_hours=10, max_data_age_hours=1000, now=NOW)
    assert o["results"][0]["vendor"] == "Aged"


def _gpu(rates):
    g = copy.deepcopy(GPU)
    g["rates"] = copy.deepcopy(rates)
    return g


def test_stack_optimizer_aged():
    line = stack.optimize(STACK, {"gpu_hours": 100}, _gpu(AGED["rates"]))["lines"][0]
    assert line["choice"]["vendor"] == "Fresh" and line["stale_prices"][0]["vendor"] == "Aged"
    line = stack.optimize(STACK, {"gpu_hours": 100}, _gpu(ALL_AGED["rates"]))["lines"][0]
    assert line["choice"] is None and "no current cheapest" in line["note"]


def test_agent_stack_aged():
    r = agent_stack.plan("fine-tune on H100 100 gpu hours", DEALS, STACK, _gpu(AGED["rates"]), now=NOW)
    line = next(l for l in r["lines"] if l["component"] == "gpu")
    assert line["choice"]["vendor"] == "Fresh" and line["stale_prices"][0]["label"].startswith("stale price (")
    r = agent_stack.plan("fine-tune on H100 100 gpu hours", DEALS, STACK, _gpu(ALL_AGED["rates"]), now=NOW)
    line = next(l for l in r["lines"] if l["component"] == "gpu")
    assert line["choice"] is None and "no current cheapest" in line["note"]


def test_build_rates_holds_aged_record():
    docs = copy.deepcopy(load_vendor_files())
    doc = next(d for d in docs if not d.get("stale") and not d.get("manual_snapshot") and d["records"]
               and not any(r.get("stale") for r in d["records"]))
    rec = doc["records"][0]
    rec["verified_at"] = rec["checked_at"] = _iso(717)
    out = build_rates(DEALS, docs)
    assert not any(r["advertiser"] == rec["vendor"] and r["gpu"] == rec["gpu"] and r.get("tier") and r["verified_at"] == rec["verified_at"]
                   for r in out["rates"])
    assert any(h["reason"] == "stale price (30 days old)" for h in out["held_stale"])


def test_default_is_168():
    assert data_age.CURRENT_MAX_HOURS == 168
