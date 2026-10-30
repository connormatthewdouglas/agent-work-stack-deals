"""T44: wire-level isError contract check against the installed wheel (stdio) or the hosted worker (HTTP).

  python scripts/check_error_contract.py --installed   # runs the `lantern-works-deals-mcp` entry point
  python scripts/check_error_contract.py --hosted [URL]
Rule (core/contract.is_error): isError == (structuredContent.ok is False). No match = ok:true, empty list.
"""
import asyncio
import json
import os
import shutil
import sys
import urllib.request

HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=qa"
UA = "lantern-works-qa/1 (T44 error contract; ref=qa)"
CASES = [
    ("invalid_input", "compare_gpu_prices", {"gpu": "H100", "limit": 0}, True, "invalid_argument"),
    ("wrong_type", "compare_gpu_prices", {"gpu": "H100", "limit": "abc"}, True, "invalid_argument"),
    ("missing_required", "compare_gpu_prices", {"limit": 3}, True, "invalid_argument"),
    ("extra_argument", "compare_gpu_prices", {"gpu": "H100", "bogus": 1}, True, "invalid_argument"),
    ("unsupported_workload", "estimate_job_cost",
     {"gpu_family": "H100", "gpus_per_job": 1, "work_units": 1e6, "workload": "llama2-70b-training"}, True, "not_found"),
    ("success", "compare_gpu_prices", {"gpu": "H100"}, False, None),
    ("no_match", "search_deals", {"query": "zzqx-no-such-deal-zzqx"}, False, None),
]
UPSTREAM = ("upstream_failure", "compare_gpu_prices", {"gpu": "H100"}, True, None)


def judge(name, sc, is_err, want_err, code):
    errs = []
    if is_err is not want_err:
        errs.append(f"isError={is_err} want {want_err}")
    if not isinstance(sc, dict) or sc.get("ok") is not (not want_err):
        errs.append(f"ok={sc.get('ok') if isinstance(sc, dict) else sc}")
    elif want_err and code and sc["error"]["code"] != code:
        errs.append(f"code={sc['error']['code']} want {code}")
    if name == "no_match" and isinstance(sc, dict) and sc.get("count") != 0:
        errs.append(f"count={sc.get('count')}")
    detail = sc.get("error", {}).get("code") if isinstance(sc, dict) and sc.get("ok") is False else f"count={sc.get('count')}"
    print(f"{'PASS' if not errs else 'FAIL'} {name}: isError={is_err} ok={sc.get('ok')} {detail} {'; '.join(errs)}")
    return not errs


def hosted(url):
    ok = True
    for i, (name, tool, args, want, code) in enumerate(CASES, 1):
        body = json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": tool, "arguments": args}}).encode()
        req = urllib.request.Request(url, body, {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                                                 "User-Agent": UA})
        res = json.load(urllib.request.urlopen(req, timeout=60))["result"]
        ok &= judge(name, res["structuredContent"], res.get("isError"), want, code)
    return ok


async def installed():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    exe = shutil.which("lantern-works-deals-mcp")
    assert exe, "lantern-works-deals-mcp not on PATH"
    ok = True
    for name, tool, args, want, code in CASES + [UPSTREAM]:
        env = dict(os.environ)
        if name == "upstream_failure":
            env["LANTERN_GPU_PRICES_URL"] = "http://127.0.0.1:9/none.json"
            env.pop("LANTERN_GPU_PRICES_FILE", None)
        async with stdio_client(StdioServerParameters(command=exe, env=env)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool(tool, args)
        ok &= judge(name, res.structuredContent, res.isError, want, code)
    return ok


if __name__ == "__main__":
    good = asyncio.run(installed()) if "--installed" in sys.argv else hosted(sys.argv[2] if len(sys.argv) > 2 else HOSTED)
    print("ERROR_CONTRACT_OK" if good else "ERROR_CONTRACT_FAIL")
    sys.exit(0 if good else 1)
