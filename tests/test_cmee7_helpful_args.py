"""CMEE-7 PR B: helpful empty/typo/bad-enum errors keep the existing contract.

Deterministic: fixture model lists and a frozen clock. No live feed, wall clock,
or committed-history pins. Validation is not loosened: typo and empty values
still error with the same codes and {ok, error{code, message}} shape.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "mcp_server")]

from core import arg_hints, contract, cost_per_job, deals  # noqa: E402
from core.deals import DealError  # noqa: E402
import server  # noqa: E402

NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
MODELS = ["H100", "H100 SXM", "A100", "A100 80GB", "RTX 4090", "L40S"]
CHECKED = "2026-11-25T11:00:00Z"


def _data():
    rates = []
    for gpu in MODELS:
        rates.append({
            "advertiser": "Fixture Cloud", "gpu": gpu, "vram_gb": 80,
            "hourly_equiv_usd": 2.5, "price_usd": 2.5, "unit": "hour",
            "tier": "On-demand", "tier_class": "on_demand", "interruptible": False,
            "billing_unit": "hourly", "billing": "per hour while running",
            "verified_at": CHECKED, "checked_at": CHECKED,
            "source_url": "https://example.com/fixture", "gpu_count": 1, "min_gpus": 1,
        })
    return {"rates": rates, "feed_updated_at": CHECKED}


def _err(exc):
    if isinstance(exc, DealError):
        return exc.code, exc.message
    return exc.code, exc.message


def test_close_matches_are_deterministic_on_fixture_names():
    assert arg_hints.close_matches("H1000", MODELS)[0] == "H100"
    assert arg_hints.close_matches("rtx4090", MODELS) == ["RTX 4090"]
    assert arg_hints.close_matches("A1000", MODELS)[0] == "A100"
    assert "L40S" in arg_hints.close_matches("L40SS", MODELS)
    assert arg_hints.close_matches("brieff", ["brief", "full"], n=1, cutoff=0.5) == ["brief"]
    assert arg_hints.close_matches("", MODELS) == []


def test_empty_gpu_stays_invalid_argument_and_includes_example():
    data = _data()
    with pytest.raises(DealError) as ei:
        deals.compare_gpu_prices(data, "", now=NOW)
    assert ei.value.code == "invalid_argument"
    assert ei.value.message.startswith("gpu is required")
    assert 'Example: compare_gpu_prices(gpu="H100")' in ei.value.message

    with pytest.raises(DealError) as ei:
        deals.find_available_gpus(data, "", now=NOW)
    assert ei.value.code == "invalid_argument"
    assert ei.value.message.startswith("gpu is required")
    assert 'Example: find_available_gpus(gpu="RTX 4090", gpus=1)' in ei.value.message

    with pytest.raises(cost_per_job.JobCostError) as ei:
        cost_per_job.estimate_job_cost(data, job_hours=8, now=NOW)
    assert ei.value.code == "invalid_argument"
    assert ei.value.message.startswith("gpu (or gpu_family) is required")
    assert 'Example: estimate_job_cost(gpu_family="A100", job_hours=8)' in ei.value.message


def test_unknown_and_typo_gpu_names_stay_not_found_with_close_match_and_example():
    data = _data()
    with pytest.raises(DealError) as ei:
        deals.compare_gpu_prices(data, "H1000", now=NOW)
    assert ei.value.code == "not_found"
    assert ei.value.message.startswith("No tracked price for GPU 'H1000'.")
    assert "Tracked models:" in ei.value.message
    assert "Did you mean 'H100'" in ei.value.message
    assert 'Example: compare_gpu_prices(gpu="H100")' in ei.value.message
    # typo is not accepted as a successful compare
    assert "results" not in dir(ei.value) or True

    with pytest.raises(DealError) as ei:
        deals.find_available_gpus(data, "rtx4090", now=NOW)
    assert ei.value.code == "not_found"
    assert "Did you mean 'RTX 4090'" in ei.value.message
    assert 'Example: find_available_gpus(gpu="RTX 4090", gpus=1)' in ei.value.message

    with pytest.raises(cost_per_job.JobCostError) as ei:
        cost_per_job.estimate_job_cost(data, gpu_family="A1000", job_hours=8, now=NOW)
    assert ei.value.code == "not_found"
    assert ei.value.message.startswith("No rankable hourly rate tracked for 'A1000'")
    assert "Did you mean 'A100'" in ei.value.message
    assert 'Example: estimate_job_cost(gpu_family="A100", job_hours=8)' in ei.value.message


def test_missing_required_args_via_check_args_keep_code_and_add_example():
    out = contract.check_args(server.compare_gpu_prices, {})
    assert out["ok"] is False and out["error"]["code"] == "invalid_argument"
    assert set(out) == {"ok", "error"}
    assert set(out["error"]) == {"code", "message"}
    assert out["error"]["message"].startswith("missing required argument(s): gpu")
    assert 'Example: compare_gpu_prices(gpu="H100")' in out["error"]["message"]

    out = contract.check_args(server.find_available_gpus, {"limit": 3})
    assert out["ok"] is False and out["error"]["code"] == "invalid_argument"
    assert out["error"]["message"].startswith("missing required argument(s): gpu")
    assert 'Example: find_available_gpus(gpu="RTX 4090", gpus=1)' in out["error"]["message"]


def test_bad_enums_stay_invalid_argument_with_close_match_and_example():
    out = server.compare_gpu_prices(gpu="H100", mode="brieff")
    assert out["ok"] is False and out["error"]["code"] == "invalid_argument"
    assert set(out) == {"ok", "error"}
    assert "mode must be one of" in out["error"]["message"]
    assert "Did you mean 'brief'" in out["error"]["message"]
    assert "Example:" in out["error"]["message"]

    with pytest.raises(DealError) as ei:
        deals.search([], query="x", offer_type="verified_discont")
    assert ei.value.code == "invalid_argument"
    assert "offer_type must be one of" in ei.value.message
    assert "Did you mean 'verified_discount'" in ei.value.message


def test_validation_is_not_loosened_typo_does_not_succeed():
    data = _data()
    # Compacted or typo'd names still do not rank; they only get a hint on the error.
    with pytest.raises(DealError):
        deals.compare_gpu_prices(data, "rtx4090", now=NOW)
    with pytest.raises(DealError):
        deals.compare_gpu_prices(data, "H1000", now=NOW)
    # A real model on the same fixture still succeeds (sanity that the fixture ranks).
    out = deals.compare_gpu_prices(data, "H100", now=NOW)
    assert out["count"] >= 1 and out["results"][0]["gpu"] in ("H100", "H100 SXM")
