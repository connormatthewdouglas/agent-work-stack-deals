#!/usr/bin/env python3
"""Clean-environment install test for the published PyPI package.

Creates a fresh venv (no repo on sys.path), pip-installs lantern-works-deals-mcp==VERSION
from PyPI, starts the console script over stdio, and calls every tool (3 in 0.1.0; 4 incl. compare_gpu_prices from 0.2.0) and
checks serverInfo.version equals the package version.
Optional --uvx also runs the same calls via `uvx lantern-works-deals-mcp==VERSION`.
Exit 0 only if every tool call returns a non-error result.
"""
import argparse, asyncio, json, os, shutil, subprocess, sys, tempfile, venv

PKG = "lantern-works-deals-mcp"

CLIENT = r'''
import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main(ver, cmd):
    v = tuple(int(x) for x in ver.split(".")[:3])
    want = {"search_deals", "compare_deals", "get_deal"} | ({"compare_gpu_prices"} if ver != "0.1.0" else set()) \
        | ({"optimize_stack"} if v >= (0, 3, 0) else set()) \
        | ({"optimize_agent_stack"} if v >= (0, 3, 6) else set())
    params = StdioServerParameters(command=cmd[0], args=cmd[1:])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            s_init = await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            def body(res):
                assert not res.isError, res
                return json.loads(res.content[0].text)
            sr = body(await s.call_tool("search_deals", {"query": "proxy", "limit": 3}))
            deals = sr.get("deals") or sr.get("results") or []
            assert deals, sr
            ids = [d["id"] for d in deals[:2]]
            g = body(await s.call_tool("get_deal", {"id": ids[0]}))
            assert ids[0] in json.dumps(g), g
            c = body(await s.call_tool("compare_deals", {"ids": ids}))
            assert c, c
            msg = ""
            if "compare_gpu_prices" in names:
                gp = body(await s.call_tool("compare_gpu_prices", {"gpu": "H100", "limit": 5}))
                rs = gp["results"]
                assert rs and [x["hourly_usd"] for x in rs] == sorted(x["hourly_usd"] for x in rs), gp
                assert all(x["source_url"] and x["checked_at"] for x in rs), gp
                assert "cheapest among tracked providers" in gp["summary"].lower(), gp
                msg = f" gpu=H100:{rs[0]['advertiser']}@{rs[0]['hourly_usd']}"
            if "optimize_stack" in names:
                st = body(await s.call_tool("optimize_stack", {"scrape_pages": 50000, "emails_sent": 10000, "gpu_hours": 100, "gpu_model": "H100"}))
                assert len(st["lines"]) == 3 and all(l["status"] == "unknown" or (l["choice"]["source_url"] and l["choice"]["checked_at"]) for l in st["lines"]), st
                msg += f" stack=${st['total_monthly_usd']}"
            if "optimize_agent_stack" in names:
                ag = body(await s.call_tool("optimize_agent_stack", {"description": "scrapes 20k pages via 5 GB residential proxies, 3,000 search queries, 100 GPU hours on an H100"}))
                assert ag["lines"] and all(l["status"] == "no_data" or (l["choice"]["source_url"] and l["choice"]["verified_at"]) for l in ag["lines"]), ag
                msg += f" agent_stack=${ag['monthly_estimate_usd']}"
            assert want <= set(names), (want, names)
            info = s_init.serverInfo
            if ver != "0.1.0":  # 0.1.0 reported the mcp SDK version (fixed in 0.2.0)
                assert info.version == ver, (info.version, ver)
            print(f"ok server={info.name}/{info.version} tools={names} search={len(deals)} get={ids[0]} compare={ids}{msg}")

asyncio.run(main(sys.argv[1], sys.argv[2:]))
'''

def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="latest", help="'latest' = newest release on PyPI (so CI covers each new release as soon as it is published)")
    ap.add_argument("--uvx", action="store_true", help="also test via uvx")
    ap.add_argument("--docker", help="test a built Docker image (docker run -i --rm IMAGE) instead of a pip/uvx install")
    ap.add_argument("--wheel", help="pre-upload check: install this local wheel instead of PyPI (skips uvx)")
    a = ap.parse_args()
    if a.version == "latest":
        import urllib.request
        with urllib.request.urlopen(f"https://pypi.org/pypi/{PKG}/json", timeout=20) as r:
            a.version = json.load(r)["info"]["version"]
        print(f"latest on PyPI: {a.version}", flush=True)
    spec = f"{PKG}=={a.version}"
    target = os.path.abspath(a.wheel) if a.wheel else spec
    tmp = tempfile.mkdtemp(prefix="lw-pypi-")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LANTERN_", "PYTHON", "VIRTUAL_ENV"))}
    try:
        vd = os.path.join(tmp, "venv")
        venv.create(vd, with_pip=True)
        py = os.path.join(vd, "bin", "python")
        cl = os.path.join(tmp, "client.py"); open(cl, "w").write(CLIENT)
        if a.docker:
            run([py, "-m", "pip", "install", "-q", "--no-cache-dir", "--isolated", "mcp>=1.10,<2"], env=env, cwd=tmp)
            run([py, cl, a.version, "docker", "run", "-i", "--rm", a.docker], env=env, cwd=tmp)
            print("RESULT: ok"); return
        run([py, "-m", "pip", "install", "-q", "--no-cache-dir", "--isolated", target], env=env, cwd=tmp)
        run([py, cl, a.version, os.path.join(vd, "bin", PKG)], env=env, cwd=tmp)
        if a.uvx and not a.wheel:
            uvx = shutil.which("uvx") or sys.exit("uvx not found")
            run([py, cl, a.version, uvx, "--no-cache", spec], env=env, cwd=tmp)
        print("RESULT: ok")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
