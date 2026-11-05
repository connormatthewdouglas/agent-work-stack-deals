"""Gauge #61 follow-ups (N1-N3): cap parsed hours, per-day rates x days, always state the day conversion."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_stack import parse  # noqa: E402
from mcp_server import server as s  # noqa: E402


def _gpu(o):
    return next(l for l in o["lines"] if l["component"] == "gpu")


@pytest.mark.parametrize("text", ["H100 for 1000 days", "1024x H100 for 1000 days", "H100 for 25000 hours"])
def test_n1_parsed_hours_capped(text):
    o = s.optimize_agent_stack(text)
    assert "error" in o and "20,000" in str(o)


def test_n1_over_730_note():
    o = s.optimize_agent_stack("H100 for 31 days")
    assert "error" not in o, o
    assert _gpu(o)["gpu_hours_total"] == 744
    assert any("730" in a for a in o["assumptions"])


def test_n1_under_730_no_note():
    o = s.optimize_agent_stack("H100 for 30 days")
    assert not any("more than one month" in a for a in o["assumptions"])


@pytest.mark.parametrize("text,hours", [("H100 10 hours/day for 30 days", 300), ("H100 8 hours per day for 5 days", 40),
                                        ("2 H100 4 hrs a day for 10 days", 40)])
def test_n2_per_day_times_days(text, hours):
    assert parse(text)["quantities"]["gpu_hours"] == hours
    o = s.optimize_agent_stack(text)
    assert "error" not in o, o
    assert any("hours/day x" in a for a in o["assumptions"])


def test_n2_per_day_without_days_is_not_silently_priced():
    p = parse("H100 10 hours per day")
    assert "gpu_hours" not in p["quantities"] and "per-day rate" in p["hours_conversion"]


@pytest.mark.parametrize("text,conv", [("H100 for 30 days", "30 days = 720 wall-clock hours"),
                                       ("2 H100 for 3 days", "3 days = 72 wall-clock hours")])
def test_n3_day_conversion_always_stated(text, conv):
    o = s.optimize_agent_stack(text)
    assert conv in o["assumptions"]


def test_explicit_hours_unchanged():
    assert parse("30-day trial, H100 for 10 hours")["quantities"]["gpu_hours"] == 10
    assert parse("H100 for 10 hours")["hours_conversion"] is None
