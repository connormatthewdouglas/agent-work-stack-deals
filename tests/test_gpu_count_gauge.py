"""Gauge PR #61 review regressions (B1-B5, N1-N3): GPU-hours vs counts, no double multiplication, end-to-end
recognition, stated assumptions, bad counts rejected, gpu_count in quote_id and the 0.4.0 receipt."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_stack import parse  # noqa: E402
from mcp_server import server as s  # noqa: E402


def _gpu(text):
    o = s.optimize_agent_stack(text)
    assert "error" not in o, o
    return o, next(l for l in o["lines"] if l["component"] == "gpu")


@pytest.mark.parametrize("text", ["10 gpu-hours H100", "10 GPU·h H100", "10 gpu-hrs H100", "10 gpu-h H100",
                                  "10 gpuh H100", "10 H100 gpu hours", "10x A100 hours"])
def test_b1_gpu_hours_variants_are_not_counts(text):
    p = parse(text)
    assert p["gpu_count"] is None and p["quantities"]["gpu_hours"] == 10
    _, l = _gpu(text)
    assert l["gpu_count"] == 1 and l["gpu_hours_total"] == 10


@pytest.mark.parametrize("text,count,per_gpu,total", [
    ("2x A100, 100 gpu hours", 2, 50, 100),
    ("16 H100 gpu hours on 2x H100", 2, 8, 16),
    ("4x A100 for 10 hours", 4, 10, 40),          # wall-clock hours are multiplied by count
    ("10 hours on 2 H100", 2, 10, 20),
])
def test_b2_no_double_multiplication(text, count, per_gpu, total):
    _, l = _gpu(text)
    assert l["status"] == "priced" and l["gpu_count"] == count
    assert l["hours_per_gpu"] == per_gpu and l["gpu_hours_total"] == total
    assert f"x {per_gpu:g} h x" in l["choice"]["calc"]


@pytest.mark.parametrize("text,count,model", [
    ("8xH100", 8, "H100"), ("two H100s", 2, "H100"), ("8 H100s", 8, "H100"), ("a pair of H100s", 2, "H100"),
    ("4090 2x", 2, "RTX 4090"), ("H100 x2", 2, "H100"), ("A100 80GB 2x", 2, "A100"), ("RTX 4090 x 2", 2, "RTX 4090"),
    ("2x A100", 2, "A100"), ("2 x H100", 2, "H100"), ("4 A100s", 4, "A100"),
])
def test_b3_goal_phrases_end_to_end(text, count, model):
    o, l = _gpu(text)
    assert l["gpu_count"] == count and o["parsed"]["gpu_model"] == model
    assert l["status"] in ("needs_quantity", "priced", "no_data")
    if l.get("choice"):
        assert f"x {count} GPU" in l["choice"]["calc"] or f"{count} requested" in l["choice"]["calc"]


@pytest.mark.parametrize("text", ["80GB A100", "rtx 4090 24 hours", "H100 NVL 94GB", "5090", "two hours on H100"])
def test_model_numbers_and_memory_never_counts(text):
    assert parse(text)["gpu_count"] is None


def test_b4_assumptions_state_requested_and_billed():
    o, l = _gpu("4x A100 for 10 hours")
    assert any("4 GPU(s) requested, 4 billed" in a for a in l["choice"]["assumptions"])
    assert not any(a.startswith("1 GPU") for a in l["choice"]["assumptions"])
    assert any("parsed from '4x a100'" in a for a in o["assumptions"])
    _, nq = _gpu("2x A100")
    assert nq["status"] == "needs_quantity" and nq["gpu_count"] == 2 and "gpu_count_note" in nq


def test_b4_gpu_count_in_output_schema():
    from core import contract
    for tool in ("optimize_agent_stack", "optimize_stack"):
        assert "gpu_count" in contract.EXTRA_PROPS[tool]["lines"]["items"]["properties"]
    o = s.optimize_stack(gpu_hours=10)
    assert all(l.get("gpu_count") == 1 for l in o["lines"] if l["need"] == "gpu_hours")


@pytest.mark.parametrize("text", ["-2x H100", "0x H100", "2000x H100", "H100 x0", "1025 H100s"])
def test_n1_n2_bad_counts_rejected(text):
    o = s.optimize_agent_stack(text)
    assert o["error"]["code"] == "invalid_argument" and "GPU count must be" in o["error"]["message"]


def test_b5_quote_id_and_receipt_carry_count():
    four = s.optimize_agent_stack("4x A100 for 10 hours")
    one = s.optimize_agent_stack("A100 for 10 hours")
    assert four["quote_id"] != one["quote_id"]
    assert s.optimize_agent_stack("4x A100 for 10 hours")["quote_id"] == four["quote_id"]
    gl = four["receipt"]["lines"][0]
    assert gl["gpu_count"] == 4 and gl["gpus_billed"] >= 4
    assert any(i["gpus"] == 4 for i in four["quote_basis"]["items"])
    r = s.rebuild_quote(four["receipt"])
    assert r["reproduced"] is True and r["receipt_intact"] is True and r["quote_id"] == four["quote_id"]


@pytest.mark.parametrize("text,hours,count", [("1024x H100 for 1 hour", 1, 1024), ("H100 for 1 hr", 1, None),
                                              ("2 H100 for 2 days", 48, 2), ("A100 for 3 days", 72, None)])
def test_singular_hours_and_days(text, hours, count):
    p = parse(text)
    assert p["quantities"]["gpu_hours"] == hours and p["gpu_count"] == count
    _, l = _gpu(text)
    assert l["status"] == "priced" and l["hours_per_gpu"] == hours


def test_days_ignored_without_gpu():
    assert "gpu_hours" not in parse("scrape 1000 pages over 3 days")["quantities"]
