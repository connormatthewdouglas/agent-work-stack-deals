"""T44 (Brain #130): stdio isError matches the hosted contract, checked over the wire with the MCP SDK client.

Cases: invalid input, upstream failure, unsupported workload -> isError=true + ok=false envelope;
success and no-match -> isError=false + ok=true (no-match is an empty list, not an error).
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "api" / "v1"

CASES = [
    # (name, tool, args, env overrides, expect isError, expect error code)
    ("invalid_input", "compare_gpu_prices", {"gpu": "H100", "limit": 0}, {}, True, "invalid_argument"),
    ("wrong_type", "compare_gpu_prices", {"gpu": "H100", "limit": "abc"}, {}, True, "invalid_argument"),
    ("missing_required", "compare_gpu_prices", {"limit": 3}, {}, True, "invalid_argument"),
    ("extra_argument", "compare_gpu_prices", {"gpu": "H100", "bogus": 1}, {}, True, "invalid_argument"),
    ("upstream_failure", "compare_gpu_prices", {"gpu": "H100"},
     {"LANTERN_GPU_PRICES_URL": "http://127.0.0.1:9/none.json", "LANTERN_GPU_PRICES_FILE": ""}, True, None),
    ("unsupported_workload", "estimate_job_cost",
     {"gpu_family": "H100", "gpus_per_job": 1, "work_units": 1e6, "workload": "llama2-70b-training"}, {}, True, "not_found"),
    ("success", "compare_gpu_prices", {"gpu": "H100"}, {}, False, None),
    ("no_match", "search_deals", {"query": "zzqx-no-such-deal-zzqx"}, {}, False, None),
]


def _env(extra):
    env = dict(os.environ)
    env.update({"LANTERN_GPU_PRICES_FILE": str(DATA / "gpu-prices.json"), "LANTERN_DEALS_FILE": str(DATA / "deals.json")})
    for k, v in extra.items():
        if v == "":
            env.pop(k, None)
        else:
            env[k] = v
    return env


async def _call(tool, args, env):
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server" / "server.py")], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await s.call_tool(tool, args)


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_stdio_is_error_wire(case):
    _, tool, args, extra, want_err, code = case
    res = asyncio.run(_call(tool, args, _env(extra)))
    sc = res.structuredContent
    assert sc is not None and sc == json.loads(res.content[0].text)
    assert res.isError is want_err
    assert sc["ok"] is (not want_err)
    if want_err:
        assert set(sc["error"]) == {"code", "message"}
        if code:
            assert sc["error"]["code"] == code
    if case[0] == "no_match":
        assert sc["count"] == 0 and sc.get("results", sc.get("deals")) == []
