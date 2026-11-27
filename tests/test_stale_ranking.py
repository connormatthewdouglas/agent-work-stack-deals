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


def test_build_rates_holds_aged_record(monkeypatch):
    """717 h is 30 days only when the build clock is the same instant the stamp was taken from.
    Pin that clock. A pre-set LW_AVAIL_NOW or a later wall clock must not change the label."""
    frozen = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    monkeypatch.setenv("LW_AVAIL_NOW", frozen.isoformat())
    docs = copy.deepcopy(load_vendor_files())
    from core.owner_hold import is_held
    doc = next(d for d in docs if not d.get("stale") and not d.get("manual_snapshot") and not is_held(d.get("vendor")) and d["records"]
               and not any(r.get("stale") for r in d["records"]))
    rec = doc["records"][0]
    rec["verified_at"] = rec["checked_at"] = (frozen - timedelta(hours=717)).isoformat()
    out = build_rates(DEALS, docs)
    assert not any(r["advertiser"] == rec["vendor"] and r["gpu"] == rec["gpu"] and r.get("tier") and r["verified_at"] == rec["verified_at"]
                   for r in out["rates"])
    assert any(h["vendor"] == rec["vendor"] and h["reason"] == "stale price (30 days old)"
               and any(x.get("gpu") == rec["gpu"] for x in h.get("records") or []) for h in out["held_stale"])


def test_default_is_168():
    assert data_age.CURRENT_MAX_HOURS == 168


def test_manual_snapshot_past_hold_after_is_held_without_stale_auto(monkeypatch):
    """Generate-time hold: a manual snapshot older than STALE_DAYS must go to held_stale
    even if refresh() has not yet written stale.auto on the record."""
    docs = copy.deepcopy(load_vendor_files())
    doc = next(d for d in docs if d.get("vendor", "").startswith("Cirrascale") and d.get("manual_snapshot"))
    rec = doc["records"][0]
    rec.pop("stale", None)
    rec["verified_at"] = rec["checked_at"] = "2026-11-09T04:33:11+00:00"
    # Exactly 7 days: still published (refresh uses a strict > STALE_DAYS cutoff).
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-16T04:33:11Z")
    out = build_rates(DEALS, docs)
    assert any(r["advertiser"] == doc["vendor"] and r["gpu"] == rec["gpu"] for r in out["rates"])
    assert not any(h["vendor"] == doc["vendor"] and any(x.get("gpu") == rec["gpu"] for x in h.get("records") or [])
                   for h in out["held_stale"])
    # One second past the cutoff: held, not ranked, verified_at unchanged.
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-16T04:33:12Z")
    out = build_rates(DEALS, docs)
    assert not any(r["advertiser"] == doc["vendor"] and r["gpu"] == rec["gpu"] for r in out["rates"])
    assert any(h["vendor"] == doc["vendor"] and any(x.get("gpu") == rec["gpu"] for x in h.get("records") or [])
               for h in out["held_stale"])


def test_auto_refresh_row_older_than_48h_is_unranked_at_build():
    """A daily-refresh row older than T41-12 (48h) must leave `rates` at generate time.

    lead_key only sorted it after fresh rows, so it stayed ranked and the freshness
    watchdog stayed red (Spheron RTX 5090 at 73.3h, runs 44649405733 / 44649548149). This fixture is 50h (past 48h, under the 72h expiry ceiling).
    The vendor file is not rewritten: no stale.auto, no fresh verified_at. Past the
    cutoff the row is held_stale with an honest age label; just inside 48h it still ranks.
    Clock is injected; no live network and no wall-clock dependence.
    """
    from core.data_age import DEGRADED_HOURS, stale_label
    clock = datetime(2026, 11, 20, 0, 52, 22, tzinfo=timezone.utc)
    url = "https://example.com/gpu-rental/rtx-5090/"
    verified = (clock - timedelta(hours=50)).replace(microsecond=0).isoformat()
    failed = (clock - timedelta(hours=6)).replace(microsecond=0).isoformat()
    rec = {
        "vendor": "SpheronTest", "gpu": "RTX 5090", "vram_gb": 32, "price_usd": 0.78,
        "billing_unit": "hourly", "hourly_usd": 0.78, "interruptible": False,
        "tier": "Marketplace/aggregator listing (on-demand)", "form_factor": "PCIe",
        "quote": "On Spheron the NVIDIA RTX 5090 is $0.78/hr per GPU, billed per minute",
        "source_url": url, "checked_at": verified, "verified_at": verified,
        "last_failed_check_at": failed,
        "evidence": {"source_url": url, "quote": "On Spheron the NVIDIA RTX 5090 is $0.78/hr per GPU, billed per minute",
                     "checked_at": verified},
    }
    doc = {
        "vendor": "SpheronTest", "deal_id": None, "source_url": url, "checked_at": verified,
        "extras": {k: {"status": "unknown", "text": "x", "source_url": url} for k in ("egress", "storage", "interruption")},
        "records": [rec],
    }
    out = build_rates([], [doc], now=clock)
    assert out["rates"] == []
    held = out["held_stale"]
    assert held and held[0]["vendor"] == "SpheronTest"
    assert held[0]["records"][0]["gpu"] == "RTX 5090"
    assert held[0]["reason"] == stale_label(rec, clock)
    # Vendor file shape is unchanged: failed re-read did not mint a verified_at or stale.auto.
    assert rec.get("stale") is None
    assert rec["verified_at"] == rec["checked_at"] == verified
    assert rec["last_failed_check_at"] == failed
    assert rec["price_usd"] == 0.78

    fresh = dict(rec)
    fresh["verified_at"] = fresh["checked_at"] = (clock - timedelta(hours=DEGRADED_HOURS - 1)).isoformat()
    fresh["evidence"] = {**rec["evidence"], "checked_at": fresh["checked_at"]}
    ranked = build_rates([], [{**doc, "records": [fresh]}], now=clock)
    assert ranked["rates"] and ranked["rates"][0]["price_usd"] == 0.78
    assert ranked["held_stale"] == []

