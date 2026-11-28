"""CMEE-7 PR A: get-started MCP instructions and clear first-call tool descriptions.

Deterministic: inspects the local stdio server, FastMCP list_tools, hosted
_tool_list, and lhm.plugin.json. No live feed, wall clock, or history pins.
Tool counts stay 12 local / 19 hosted.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "mcp_server")]

from mcp_server import server  # noqa: E402

FIRST_CALLS = (
    "compare_gpu_prices",
    "find_available_gpus",
    "estimate_job_cost",
)
EXAMPLES = {
    "compare_gpu_prices": 'compare_gpu_prices(gpu="H100")',
    "find_available_gpus": 'find_available_gpus(gpu="RTX 4090", gpus=1)',
    "estimate_job_cost": 'estimate_job_cost(gpu_family="A100", job_hours=8)',
}


def _hosted_tool_list():
    code = """
import sys, types, json, importlib.util
sys.path.insert(0, %r); sys.path.insert(0, %r)
w = types.ModuleType("workers"); w.Response = w.WorkerEntrypoint = object; w.fetch = None; sys.modules["workers"] = w
spec = importlib.util.spec_from_file_location("hosted_entry", %r); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(json.dumps({"instructions": m.server.INSTRUCTIONS, "tools": m._tool_list()}))
""" % (str(ROOT), str(ROOT / "hosted" / "src"), str(ROOT / "hosted" / "src" / "entry.py"))
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-2000:]
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_instructions_have_short_get_started_with_first_calls_and_examples():
    text = server.INSTRUCTIONS
    assert text.startswith("Get started:")
    assert "GPU rental prices" in text
    assert "in stock" in text
    assert "job will cost" in text
    for name in FIRST_CALLS:
        assert name in text, name
    for example in EXAMPLES.values():
        assert example in text, example
    assert "Compare H100 rental prices." in text
    assert "What would 8 hours on an A100 cost?" in text
    # Existing contract text is still present and follows the short get-started.
    assert "invalid_argument" in text and "mode='brief'" in text
    assert "never by affiliate" in text
    assert text.index("Get started:") < text.index("Read-only GPU rental price comparison")


def test_first_call_docstrings_include_example_calls():
    fns = {
        "compare_gpu_prices": server.compare_gpu_prices,
        "find_available_gpus": server.find_available_gpus,
        "estimate_job_cost": server.estimate_job_cost,
    }
    for name, fn in fns.items():
        doc = inspect.getdoc(fn) or ""
        assert EXAMPLES[name] in doc, name


def test_descriptions_match_across_stdio_hosted_and_lhm_manifest():
    stdio = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    hosted = _hosted_tool_list()
    hosted_tools = {t["name"]: t for t in hosted["tools"]}
    assert hosted["instructions"] == server.INSTRUCTIONS

    for name, example in EXAMPLES.items():
        stdio_desc = (stdio[name].description or "").strip()
        hosted_desc = (hosted_tools[name]["description"] or "").strip()
        doc = (inspect.getdoc(getattr(server, name)) or "").strip()
        assert stdio_desc == doc, name
        assert hosted_desc == doc, name
        assert example in stdio_desc and example in hosted_desc

    plugin = json.loads((ROOT / "lhm.plugin.json").read_text())
    lhm = next(t for t in plugin["tools"] if t["name"] == "compare_gpu_prices")
    assert inspect.cleandoc(lhm["description"] or "").strip() == (inspect.getdoc(server.compare_gpu_prices) or "").strip()


def test_tool_counts_stay_12_local_and_19_hosted():
    stdio = asyncio.run(server.mcp.list_tools())
    assert len(stdio) == 12
    hosted = _hosted_tool_list()["tools"]
    assert len(hosted) == 19
