"""Regression: optimize_agent_stack's parser must not take quantities out of GPU model names
('10 H100 gpu hours' was parsed as 100 GPU-hours)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_stack import parse  # noqa: E402
from mcp_server import server as s  # noqa: E402

CASES = [
    ("10 H100 gpu hours", 10, "H100"),
    ("10 gpu hours on H100", 10, "H100"),
    ("2x A100 for 50 hours", 50, "A100"),
    ("4090 for 3 hours", 3, "RTX 4090"),
    ("100 h100 hours", 100, "H100"),
    ("B200 for 12 hrs", 12, "B200"),
    ("L40S 8 gpu hours", 8, "L40S"),
    ("rtx 4090 24 hours", 24, "RTX 4090"),
    ("fine-tune a 70b model on h200 for 20 hours", 20, "H200"),
]


@pytest.mark.parametrize("text,hours,model", CASES)
def test_gpu_hours_never_come_from_model_names(text, hours, model):
    p = parse(text)
    assert p["quantities"].get("gpu_hours") == hours, p["quantities"]
    assert p["gpu_model"] == model
    assert "gpu" in p["components"]


def test_mixed_description_keeps_other_numbers():
    p = parse("scraping 1000 pages and 10 H100 gpu hours, budget $500/mo")
    assert p["quantities"] == {"gpu_hours": 10, "scrape_pages": 1000}
    assert p["monthly_budget_usd"] == 500 and p["gpu_model"] == "H100"


def test_model_name_alone_gives_no_hours():
    for t in ("an agent on an H100", "A100 80GB inference", "needs an RTX 4090"):
        assert "gpu_hours" not in parse(t)["quantities"], t


def test_tool_prices_the_right_hours():
    out = s.optimize_agent_stack(description="10 H100 gpu hours")
    line = next(l for l in out["lines"] if l["component"] == "gpu")
    assert line["quantity"] == 10 and line["status"] == "priced"
    assert "x 10 h" in line["choice"]["calc"]
