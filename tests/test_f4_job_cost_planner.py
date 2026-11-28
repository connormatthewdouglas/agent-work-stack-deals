"""F4 (Brain #1031): estimate_job_cost job_days + tracked /go/ booking links.

Deterministic: fixtures and a frozen clock only. No live feed, no wall clock,
no pins to committed history or gpu-prices.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core import contract, golinks
from core.cost_per_job import JobCostError, estimate_job_cost

NOW = datetime(2026, 11, 26, 17, 0, 0, tzinfo=timezone.utc)
FRESH = "2026-11-26T16:00:00Z"       # 1h old
DEGRADED = "2026-11-24T12:00:00Z"    # 53h old (> 48h, < 168h)
STALE_PRICE = "2026-11-18T17:00:00Z" # 192h old (> 168h)
ROOT = Path(__file__).resolve().parents[1]


def _row(vendor, price, per=1, min_gpus=1, tier_class="on-demand", interruptible=False,
         gpu="H100", verified=FRESH, deal_id=None, availability=None, **kw):
    r = {
        "advertiser": vendor, "gpu": gpu, "vram_gb": 80, "price_usd": price,
        "gpu_count": per, "min_gpus": min_gpus, "unit": "hour", "tier": "On-demand",
        "tier_class": tier_class, "interruptible": interruptible, "billing_unit": "hourly",
        "price_status": "listed", "verified_at": verified, "checked_at": verified,
        "source_url": f"https://{vendor.lower().replace(' ', '-')}.example/pricing",
        "deal_id": deal_id,
    }
    if availability is not None:
        r["availability"] = availability
    r.update(kw)
    return r


def _feed(rates, held=None):
    return {"rates": rates, "held_stale": held or []}


def test_job_days_converts_to_hours_and_prices_multi_gpu():
    # 8 GPUs × 3 days × $2/hr = $1,152
    data = _feed([_row("Acme", 2.0, per=8, min_gpus=8)])
    out = estimate_job_cost(data, "H100", 8, job_days=3, now=NOW)
    assert out["job_days"] == 3 and out["job_hours"] == 72
    r = out["results"][0]
    assert r["allocated_gpus"] == 8 and r["instances"] == 1
    assert r["job_days"] == 3 and r["job_hours"] == 72
    assert r["compute_subtotal_usd"] == pytest.approx(1152.0, abs=0.01)
    assert "3 day" in out["assumptions"][0] and "72 h" in out["assumptions"][0]
    assert "3 days" in out["summary"]


def test_whole_instance_9_gpus_for_3_days_bills_16():
    # 9 requested on an 8-GPU-only offer bills 16 GPUs × 72 h × $6.155
    data = _feed([_row("CoreWeave", 6.155, per=8, min_gpus=8)])
    r = estimate_job_cost(data, "H100", 9, job_days=3, now=NOW)["results"][0]
    assert (r["allocated_gpus"], r["instances"]) == (16, 2)
    assert r["compute_subtotal_usd"] == pytest.approx(6.155 * 72 * 16, abs=0.01)


def test_job_hours_still_works_and_reports_job_days():
    data = _feed([_row("Solo", 3.0)])
    out = estimate_job_cost(data, "H100", 1, job_hours=10, now=NOW)
    assert out["job_hours"] == 10 and out["job_days"] == pytest.approx(10 / 24, abs=1e-4)
    assert out["results"][0]["compute_subtotal_usd"] == pytest.approx(30.0, abs=0.01)
    assert "10 h" in out["summary"] and "days" not in out["summary"].split(";")[0]


def test_job_days_and_job_hours_mutex():
    with pytest.raises(JobCostError, match="job_days OR job_hours") as e:
        estimate_job_cost(_feed([_row("A", 1.0)]), "H100", 1, job_hours=24, job_days=1, now=NOW)
    assert e.value.code == "invalid_argument"


def test_job_days_and_work_units_mutex():
    with pytest.raises(JobCostError, match="job_days OR") as e:
        estimate_job_cost(_feed([_row("A", 1.0)]), "H100", 1, job_days=1,
                          work_units=10, throughput_units_per_gpu_hour=1, now=NOW)
    assert e.value.code == "invalid_argument"


def test_job_days_over_hours_cap_rejected():
    # 834 days × 24 = 20,016 h > 20,000 cap
    with pytest.raises(JobCostError, match="20000") as e:
        estimate_job_cost(_feed([_row("A", 1.0)]), "H100", 8, job_days=834, now=NOW)
    assert e.value.code == "invalid_argument"


def test_vendors_ranked_with_tracked_go_links():
    data = _feed([
        _row("Expensive Cloud", 5.0, deal_id="deal-abc-001"),
        _row("Cheap Cloud", 1.5),
    ])
    out = estimate_job_cost(data, "H100", 2, job_days=2, now=NOW, top_n=5)
    assert [r["vendor"] for r in out["results"]] == ["Cheap Cloud", "Expensive Cloud"]
    cheap, dear = out["results"]
    assert cheap["tracked_url"] == golinks.GO_BASE + "v/cheap-cloud?src=mcp"
    assert dear["tracked_url"] == golinks.GO_BASE + "deal-abc-001?src=mcp"
    # 2 GPUs × 48 h × $1.5
    assert cheap["compute_subtotal_usd"] == pytest.approx(144.0, abs=0.01)
    # ranking must not depend on the booking link (cheaper vendor first even without a deal_id)
    assert "tracked_url" in cheap and "tracked_url" in dear


def test_reserved_and_held_serverless_never_ranked():
    data = _feed([
        _row("ReservedCo", 0.10, tier_class="reserved"),
        _row("SpotCo", 0.20, tier_class="interruptible", interruptible=True),
        _row("ServerlessCo", 0.30, billing_unit="per_second", price_per_second_usd=0.0001,
             **{"unit": "hour"}),  # still hourly unit; reason comes from serverless.rate_reason
        _row("OnDemandCo", 2.00),
    ])
    # If the serverless helper does not hold this row, OnDemandCo still must beat reserved/spot by default.
    out = estimate_job_cost(data, "H100", 1, job_days=3, now=NOW, top_n=25)
    vendors = [r["vendor"] for r in out["results"]]
    assert "ReservedCo" not in vendors
    assert "SpotCo" not in vendors
    assert vendors[0] == "OnDemandCo"
    # held_stale is a sidecar list, never a ranked rate
    held = _feed([_row("OnDemandCo", 2.00)], held=[_row("HeldVendor", 0.01)])
    out2 = estimate_job_cost(held, "H100", 1, job_days=3, now=NOW)
    assert [r["vendor"] for r in out2["results"]] == ["OnDemandCo"]


def test_stale_price_excluded_degraded_flagged_frozen_clock():
    data = _feed([
        _row("FreshCo", 3.0, verified=FRESH),
        _row("DegradedCo", 1.0, verified=DEGRADED),  # cheaper but degraded: must not lead
        _row("StaleCo", 0.5, verified=STALE_PRICE),  # older than 168h: not ranked
    ])
    out = estimate_job_cost(data, "H100", 1, job_days=3, now=NOW, top_n=25)
    vendors = [r["vendor"] for r in out["results"]]
    assert "StaleCo" not in vendors
    assert out["excluded_stale"] == 1 and out["stale_prices"]
    assert vendors[0] == "FreshCo"
    assert "DegradedCo" in vendors
    deg = next(r for r in out["results"] if r["vendor"] == "DegradedCo")
    assert deg["degraded"] is True and deg["stale"] is False
    fresh = out["results"][0]
    assert fresh["degraded"] is False and fresh["data_age_hours"] == pytest.approx(1.0, abs=0.01)


def test_availability_passthrough_is_not_a_reservation():
    # A stale stock claim is request-time guarded (same stale_guard as find_available_gpus).
    # The quote is still not a reservation; in_stock is unknown, last_known stays visible.
    av = {"in_stock": True, "origin": "scout",
          "checked_at": "2026-11-26T08:00:00Z",  # 9h before NOW, past P64 8h
          "last_known_in_stock": True, "last_known_at": "2026-11-26T08:00:00Z"}
    data = _feed([_row("Acme", 2.0, availability=av)])
    out = estimate_job_cost(data, "H100", 8, job_days=3, now=NOW)
    r = out["results"][0]
    assert r["in_stock"] is None and r["availability"]["in_stock"] is None
    assert r["availability"].get("availability_stale") is True
    assert r["availability"]["last_known_in_stock"] is True
    assert r["availability"]["last_known_at"].endswith("Z")
    assert "reservation" not in out["summary"].lower()
    assert "3 days" in out["summary"]


def test_timestamps_are_utc_z():
    data = _feed([_row("Acme", 2.0, verified=FRESH)])
    r = estimate_job_cost(data, "H100", 1, job_days=1, now=NOW)["results"][0]
    for key in ("verified_at", "checked_at"):
        assert r[key].endswith("Z") and "T" in r[key]


def test_mcp_tool_job_days_and_brief_contract(monkeypatch, tmp_path):
    """Wire job_days through the stdio tool against a fixture feed and a frozen clock."""
    feed = _feed([
        _row("Cheap Cloud", 1.5),
        _row("Expensive Cloud", 5.0, deal_id="deal-abc-001"),
    ])
    path = tmp_path / "gpu-prices.json"
    path.write_text(json.dumps(feed))
    monkeypatch.setenv("LW_AVAIL_NOW", "2026-11-26T17:00:00Z")
    from core.deals import GpuPricesLoader
    from mcp_server import server
    monkeypatch.setattr(server, "gpu_loader", GpuPricesLoader(file=str(path)))
    ok = server.estimate_job_cost("H100", 8, job_days=3)
    assert ok["ok"] is True and ok["job_days"] == 3 and ok["job_hours"] == 72
    assert ok["results"] and ok["results"][0]["vendor"] == "Cheap Cloud"
    assert ok["results"][0]["tracked_url"].startswith(golinks.GO_BASE) and "src=mcp" in ok["results"][0]["tracked_url"]
    assert ok["referral_disclosure"] == golinks.REFERRAL_DISCLOSURE
    assert all("tracked_url" not in line for line in ok["receipt"]["lines"])
    brief = server.estimate_job_cost("H100", 8, job_days=3, mode="brief")
    assert brief["mode"] == "brief" and brief["job_days"] == 3
    assert set(brief["results"][0]) <= set(contract.SPEC["estimate_job_cost"][4])
    assert "job_days" in brief["results"][0]
    import jsonschema
    jsonschema.validate(ok, contract.output_schema("estimate_job_cost"))
    both = server.estimate_job_cost("H100", 1, job_hours=24, job_days=1)
    assert both["ok"] is False and both["error"]["code"] == "invalid_argument"
    jsonschema.validate(both, contract.output_schema("estimate_job_cost"))
