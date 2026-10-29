"""T20 Phase A regression tests: whole-instance billing, no guessed throughput, contract envelope."""
import json
from pathlib import Path

import pytest

from core import contract
from core.cost_per_job import JobCostError, estimate_job_cost

ROOT = Path(__file__).resolve().parents[1]
NOW_ROW = "2026-10-29T00:00:00+00:00"


def _row(vendor, price, per=1, min_gpus=1, tier_class="on-demand", interruptible=False, gpu="H100"):
    return {"advertiser": vendor, "gpu": gpu, "vram_gb": 80, "price_usd": price, "gpu_count": per, "min_gpus": min_gpus,
            "unit": "hour", "tier": "On-demand", "tier_class": tier_class, "interruptible": interruptible,
            "billing_unit": "hourly", "price_status": "listed", "verified_at": NOW_ROW, "checked_at": NOW_ROW,
            "source_url": f"https://{vendor.lower()}.example/pricing", "deal_id": None}


CW = {"rates": [_row("CoreWeave", 6.155, per=8, min_gpus=8)]}


@pytest.mark.parametrize("req,billed,inst", [(1, 8, 1), (8, 8, 1), (9, 16, 2)])
def test_whole_instance_billing(req, billed, inst):
    r = estimate_job_cost(CW, "H100", req, job_hours=10)["results"][0]
    assert (r["allocated_gpus"], r["instances"]) == (billed, inst)


def test_t35_repro_9xh100_10h_coreweave():
    r = estimate_job_cost(CW, "H100", 9, job_hours=10)["results"][0]
    assert r["compute_subtotal_usd"] == pytest.approx(984.80, abs=0.01)


def test_missing_throughput_returns_error_not_number():
    with pytest.raises(JobCostError) as e:
        estimate_job_cost(CW, "H100", 8, workload="fine-tune Llama 3.1 70B LoRA")
    assert e.value.code == "not_found" and "missing: throughput for H100" in e.value.message


def test_user_throughput_derives_hours_and_echoes_assumption():
    out = estimate_job_cost(CW, "H100", 8, work_units=8000, throughput_units_per_gpu_hour=100)
    assert out["job_hours"] == 10 and "your input" in out["assumptions"][0] and out["citations"] == []
    assert out["budget_verdict"] == "unresolved" and out["missing_costs"]


def test_reserved_and_spot_excluded_unless_allowed():
    d = {"rates": [_row("A", 1.0, tier_class="reserved"), _row("B", 1.5, tier_class="interruptible", interruptible=True),
                   _row("C", 2.0)]}
    assert [r["vendor"] for r in estimate_job_cost(d, "H100", 1, job_hours=1)["results"]] == ["C"]
    assert estimate_job_cost(d, "H100", 1, job_hours=1, allow_interruptible=True)["results"][0]["vendor"] == "B"


def test_sorted_by_subtotal_and_flags():
    d = {"rates": [CW["rates"][0], _row("Solo", 3.0)]}
    res = estimate_job_cost(d, "H100", 1, job_hours=10)["results"]
    assert res[0]["vendor"] == "Solo" and res[0]["compute_subtotal_usd"] == 30.0
    assert res[0]["rate_id"].startswith("r_") and "stale" in res[0] and "data_age_hours" in res[0]


@pytest.mark.parametrize("kw", [{"job_hours": -1}, {"job_hours": 1, "work_units": 5, "throughput_units_per_gpu_hour": 1}, {}])
def test_bad_inputs(kw):
    with pytest.raises(JobCostError):
        estimate_job_cost(CW, "H100", 1, **kw)


def test_published_feed_held_stale_never_ranked():
    data = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    held = {(h.get("advertiser") or h.get("vendor")) for h in data.get("held_stale") or [] if isinstance(h, dict)}
    live = {r["advertiser"] for r in data["rates"]}
    for g in ("H100", "A100"):
        try:
            res = estimate_job_cost(data, g, 1, job_hours=1, top_n=25)["results"]
        except JobCostError:
            continue
        assert not ({r["vendor"] for r in res} & (held - live))


def test_mcp_tool_contract():
    from mcp_server import server
    ok = server.estimate_job_cost("H100", 9, job_hours=10)
    assert ok["ok"] and ok["quote_id"].startswith("q_") and ok["results"]
    brief = server.estimate_job_cost("H100", 9, job_hours=10, mode="brief")
    assert brief["mode"] == "brief" and set(brief["results"][0]) <= set(contract.SPEC["estimate_job_cost"][4])
    err = server.estimate_job_cost("H100", 8, workload="serve Qwen 32B")
    assert err["ok"] is False and err["error"]["code"] == "not_found" and "missing: throughput" in err["error"]["message"]
    import jsonschema
    jsonschema.validate(ok, contract.output_schema("estimate_job_cost"))
    jsonschema.validate(err, contract.output_schema("estimate_job_cost"))
