"""Bjorn 1110 readiness fixes: estimate_job_cost accepts gpu as an alias for gpu_family (gpus_per_job defaults to 1),
and a degraded / stale marketplace row never ranks first while a fresh row exists (shared core.data_age.lead_key,
same rule in compare_gpu_prices); with nothing fresh the result says stale_fallback."""
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import cost_per_job as C
from core.deals import compare_gpu_prices

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def _row(vendor, hours_old, price, tier="On-demand", status=None):
    ts = (NOW - timedelta(hours=hours_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = {"advertiser": vendor, "gpu": "H100 SXM", "vram_gb": 80, "price_usd": price, "hourly_equiv_usd": price, "unit": "hour",
         "tier": tier, "interruptible": False, "billing_unit": "hourly", "verified_at": ts, "checked_at": ts,
         "source_url": f"https://example.com/{vendor.lower()}", "deal_id": None, "gpu_count": 1}
    if status:
        r.update(price_status=status, lowest_offer_usd=round(price * 0.9, 2), offer_count=4)
    return r


LIUM = _row("Lium", 136, 1.10, tier="Marketplace", status="marketplace")  # 136 h old: degraded, not yet > 168 h stale
DATA = {"rates": [LIUM, _row("FreshOD", 3, 2.40), _row("FreshCommunity", 2, 1.90, tier="On-demand (Community Cloud)")]}


def test_gpu_alias_and_default_gpus_per_job():
    a = C.estimate_job_cost(DATA, gpu="H100", job_hours=100, now=NOW)
    b = C.estimate_job_cost(DATA, "H100", 1, job_hours=100, now=NOW)
    assert a["gpu_family"] == "H100" and a["requested_gpus"] == 1
    assert [r["rate_id"] for r in a["results"]] == [r["rate_id"] for r in b["results"]]
    # same value under both names is fine (case/space-insensitive)
    assert C.estimate_job_cost(DATA, gpu_family="H100", gpu=" h100 ", job_hours=1, now=NOW)["count"] == 3


def test_gpu_and_gpu_family_conflict_is_clear_error():
    with pytest.raises(C.JobCostError) as e:
        C.estimate_job_cost(DATA, gpu_family="A100", gpu="H100", job_hours=1, now=NOW)
    assert e.value.code == "invalid_argument" and "conflict" in e.value.message and "alias" in e.value.message
    with pytest.raises(C.JobCostError) as e:
        C.estimate_job_cost(DATA, job_hours=1, now=NOW)
    assert e.value.code == "invalid_argument" and "gpu (or gpu_family) is required" in e.value.message


def test_degraded_lium_like_row_not_ranked_first():
    out = C.estimate_job_cost(DATA, gpu="H100", job_hours=100, now=NOW)
    vendors = [r["vendor"] for r in out["results"]]
    assert vendors[0] == "FreshOD" and vendors[-1] == "Lium"  # fresh on-demand leads; degraded marketplace shown last
    lium = out["results"][-1]
    assert lium["degraded"] is True and lium["data_age_hours"] == 136.0
    assert out["stale_fallback"] is False
    assert "never ranked first" in out["summary"] and "FreshCommunity" in out["summary"]  # cheaper fresh row named
    # compare_gpu_prices applies the same shared rule: the degraded row never heads the results
    cmp = compare_gpu_prices(DATA, "H100", now=NOW)
    assert cmp["results"][0]["advertiser"] == "FreshCommunity" and cmp["results"][-1]["advertiser"] == "Lium"
    assert cmp["stale_fallback"] is False
    od = compare_gpu_prices(DATA, "H100", on_demand_only=True, now=NOW)
    assert od["results"][0]["advertiser"] == out["results"][0]["vendor"]  # cheapest H100 agrees with compare's MCP default
    # opting into every tier ranks by cost among fresh rows; the degraded row still never leads
    allt = C.estimate_job_cost(DATA, gpu="H100", job_hours=100, allow_interruptible=True, now=NOW)
    assert [r["vendor"] for r in allt["results"]] == ["FreshCommunity", "FreshOD", "Lium"]


def test_explicit_max_age_override_still_ranks_by_cost():
    out = C.estimate_job_cost(DATA, gpu="H100", job_hours=1, max_data_age_hours=500, allow_interruptible=True, now=NOW)
    assert out["results"][0]["vendor"] == "Lium" and out["results"][0]["degraded"] is True


def test_all_degraded_falls_back_with_stale_flag():
    data = {"rates": [_row("OldA", 100, 2.0), LIUM]}
    out = C.estimate_job_cost(data, gpu="H100", job_hours=10, now=NOW)
    assert out["stale_fallback"] is True and "STALE FALLBACK" in out["summary"]
    assert all(r["degraded"] for r in out["results"]) and out["results"][0]["vendor"] == "OldA"  # on-demand first
    cmp = compare_gpu_prices(data, "H100", now=NOW)
    assert cmp["stale_fallback"] is True and "STALE FALLBACK" in cmp["summary"]
    # nothing current at all (> 168 h): no cheapest is named, rows only in stale_prices (existing re28 rule)
    ancient = {"rates": [_row("Ancient", 24 * 9, 1.0)]}
    allx = C.estimate_job_cost(ancient, gpu="H100", job_hours=10, now=NOW)
    assert allx["results"] == [] and allx["ok_current"] is False and allx["stale_prices"][0]["vendor"] == "Ancient"


def _srv():
    from mcp_server import server
    server.gpu_loader.file = str(ROOT / "api" / "v1" / "gpu-prices.json")
    server.gpu_loader._cache = None
    return server


def test_stdio_tool_schema_and_call():
    s = _srv()
    tool = {t.name: t for t in asyncio.run(s.mcp.list_tools())}["estimate_job_cost"]
    sch = tool.inputSchema
    assert "gpu" in sch["properties"] and sch["properties"]["gpus_per_job"].get("default") == 1
    assert "gpu_family" not in sch.get("required", []) and "gpus_per_job" not in sch.get("required", [])
    assert "alias" in tool.description
    out = s.estimate_job_cost(gpu="H100", job_hours=10)
    assert out["ok"] is True and out["requested_gpus"] == 1 and out["receipt"]
    err = s.estimate_job_cost(gpu="H100", gpu_family="A100", job_hours=10)
    assert err["ok"] is False and err["error"]["code"] == "invalid_argument"


def test_hosted_worker_schema_has_alias_and_default():
    code = """
import sys, types, json, importlib.util
sys.path.insert(0, %r); sys.path.insert(0, %r)
w = types.ModuleType("workers"); w.Response = w.WorkerEntrypoint = object; w.fetch = None; sys.modules["workers"] = w
spec = importlib.util.spec_from_file_location("hosted_entry", %r); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(json.dumps(m._tool_list()))
""" % (str(ROOT), str(ROOT / "hosted" / "src"), str(ROOT / "hosted" / "src" / "entry.py"))
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-2000:]
    t = {x["name"]: x for x in json.loads(res.stdout.strip().splitlines()[-1])}["estimate_job_cost"]
    sch = t["inputSchema"]
    assert sch["properties"]["gpu"]["type"] == "string" and sch["properties"]["gpus_per_job"]["default"] == 1
    assert not {"gpu_family", "gpus_per_job"} & set(sch.get("required", []))
