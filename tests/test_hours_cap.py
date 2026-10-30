"""Gauge re27: one cap on hours (wall-clock duration per GPU, not GPU-hours) across the engine and both tools."""
import json
from pathlib import Path

import pytest

from core import agent_stack, cost_per_job, stack
from core.stack import MAX_GPU_HOURS_MONTH

ROOT = Path(__file__).resolve().parents[1]
GPU = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())


def test_cap_value():
    assert MAX_GPU_HOURS_MONTH == 20000


def test_job_cost_rejects_1e9_hours():
    with pytest.raises(cost_per_job.JobCostError, match="hours, not GPU-hours"):
        cost_per_job.estimate_job_cost(GPU, "H100", 8, job_hours=1e9)


def test_job_cost_rejects_computed_duration_over_cap():
    with pytest.raises(cost_per_job.JobCostError, match="exceeds 20000"):
        cost_per_job.estimate_job_cost(GPU, "H100", 1, work_units=1e12, throughput_units_per_gpu_hour=1)


def test_job_cost_2501h_on_8_gpus_is_valid():
    out = cost_per_job.estimate_job_cost(GPU, "H100", 8, job_hours=2501)
    assert out["job_hours"] == 2501


def test_agent_stack_rejects_1e9_hours():
    with pytest.raises(stack.StackError, match="hours, not GPU-hours"):
        agent_stack.plan("", [], {}, GPU, gpu_hours=1e9, gpu_model="H100")
