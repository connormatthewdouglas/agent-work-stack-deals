"""Regression: GPU counts ('2x A100', 'two H100s') are parsed and priced, not read as one GPU or a model number."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_stack import parse  # noqa: E402
from core import stack  # noqa: E402

COUNT_CASES = [
    ("2x A100 for 50 hours", 2, "A100", 50),
    ("2 x H100 for 100 hours", 2, "H100", 100),
    ("8xH100 for 10 hours", 8, "H100", 10),
    ("4 A100s for 20 hours", 4, "A100", 20),
    ("two H100s for 30 hours", 2, "H100", 30),
    ("3 RTX 4090s, 5 hours", 3, "RTX 4090", 5),
    ("8 GPUs (H100) for 40 hours", 8, "H100", 40),
]


@pytest.mark.parametrize("text,count,model,hours", COUNT_CASES)
def test_gpu_count_parsed(text, count, model, hours):
    p = parse(text)
    assert p["gpu_count"] == count and p["gpu_model"] == model
    assert p["quantities"].get("gpu_hours") == hours


@pytest.mark.parametrize("text", ["10 H100 gpu hours", "10 gpu hours on H100", "100 h100 hours", "B200 for 12 hrs",
                                  "L40S 8 gpu hours", "rtx 4090 24 hours", "4090 for 3 hours", "10x A100 hours",
                                  "fine-tune a 70b model on h200 for 20 hours"])
def test_pr33_cases_have_no_count(text):
    assert parse(text)["gpu_count"] is None


def test_count_passed_to_pricing(monkeypatch):
    seen = {}
    real = stack._gpu_options

    def spy(*a, **k):
        seen["gpus"] = k.get("gpus", 1)
        return real(*a, **k)
    monkeypatch.setattr(stack, "_gpu_options", spy)
    from core import agent_stack
    gdata = {"hours_per_month": 730, "rates": [{"gpu": "H100", "unit": "hour", "price_usd": 2.0, "vendor": "v",
                                                "source_url": "https://x", "checked_at": "2026-11-01T00:00:00Z"}]}
    try:
        agent_stack.plan("8xH100 for 10 hours", [], {"offers": []}, gdata)
    except Exception:
        pass
    assert seen.get("gpus") == 8
    opts = real(gdata, 10, "H100", set(), gpus=8)
    assert opts[0]["monthly_cost_usd"] == pytest.approx(160)
