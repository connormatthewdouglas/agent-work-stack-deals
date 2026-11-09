"""estimate_job_cost applies the same serverless/per-second rule as compare_gpu_prices (core/serverless.py): real
Modal and Koyeb rows are held out of cost ranking, listed in held_serverless with the reason and counted in
excluded_serverless (brief mode too); a model with only serverless prices is a clear not_found."""
import asyncio
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import deals  # noqa: E402
from core.cost_per_job import JobCostError, estimate_job_cost  # noqa: E402
from core.serverless import rate_reason  # noqa: E402

FEED = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
NOW = datetime.fromisoformat("2026-11-06T08:00:00+00:00")  # inside the feed's freshness window, so rows rank


def _real(vendor):
    rows = [r for r in FEED["rates"] if r["advertiser"] == vendor and rate_reason(r)]
    assert rows, f"real {vendor} serverless rows expected in the feed"
    return rows


def test_real_modal_and_koyeb_rows_are_serverless():
    assert {r["gpu"] for r in _real("Modal")} >= {"H100 SXM", "L40S"} and [r["gpu"] for r in _real("Koyeb")] == ["L40S"]


def test_koyeb_and_modal_held_out_of_l40s_job_cost_in_every_mode():
    for interruptible in (False, True):
        out = estimate_job_cost(FEED, "L40S", 1, job_hours=10, now=NOW, allow_interruptible=interruptible, top_n=25)
        vendors = {r["vendor"] for r in out["results"]}
        assert not vendors & {"Koyeb", "Modal"}, vendors
        held = {h["vendor"]: h for h in out["held_serverless"]}
        assert set(held) == {"Koyeb", "Modal"} and out["excluded_serverless"] == 2
        assert held["Koyeb"]["reason"].startswith("serverless/per-second") and held["Modal"]["price_per_second_usd"]
        assert "held, not ranked" in out["summary"]


def test_held_rows_match_compare_gpu_prices():
    job = estimate_job_cost(FEED, "H100", 1, job_hours=5, now=NOW, allow_interruptible=True)
    cmp = deals.compare_gpu_prices(FEED, "H100", now=NOW, limit=25)
    key = lambda h: (h["vendor"], h["gpu"], h["tier"], h["reason"])
    assert sorted(map(key, job["held_serverless"])) == sorted(map(key, cmp["held_serverless"]))
    assert job["excluded_serverless"] == cmp["excluded_serverless"] >= 1


def test_only_serverless_prices_is_a_clear_not_found():
    data = {**FEED, "rates": copy.deepcopy(_real("Koyeb") + [r for r in _real("Modal") if r["gpu"] == "L40S"])}
    with pytest.raises(JobCostError) as e:
        estimate_job_cost(data, "L40S", 1, job_hours=10, now=NOW, allow_interruptible=True)
    assert e.value.code == "not_found" and "Only serverless/per-second prices" in e.value.message
    assert "Koyeb L40S" in e.value.message and "Modal L40S" in e.value.message


def test_mcp_brief_keeps_count_and_reasons():
    from mcp_server import server
    res = asyncio.run(server.mcp.call_tool("estimate_job_cost", {"gpu_family": "L40S", "gpus_per_job": 1, "job_hours": 10,
                                                                 "max_data_age_hours": 100000, "mode": "brief"}))
    out = json.loads((res[0] if isinstance(res, tuple) else res)[0].text)
    assert out["mode"] == "brief" and "receipt" not in out  # brief contract applied
    assert out["excluded_serverless"] == 2 and {h["vendor"] for h in out["held_serverless"]} == {"Koyeb", "Modal"}
    assert all(h["reason"] for h in out["held_serverless"])
    assert not {r["vendor"] for r in out["results"]} & {"Koyeb", "Modal"}
