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
    want = {"search_deals", "compare_deals", "get_deal"} | ({"compare_gpu_prices"} if ver != "0.1.0" else set())
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
    ap.add_argument("--version", default="0.2.0")
    ap.add_argument("--uvx", action="store_true", help="also test via uvx")
    ap.add_argument("--wheel", help="pre-upload check: install this local wheel instead of PyPI (skips uvx)")
    a = ap.parse_args()
    spec = f"{PKG}=={a.version}"
    target = os.path.abspath(a.wheel) if a.wheel else spec
    tmp = tempfile.mkdtemp(prefix="lw-pypi-")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LANTERN_", "PYTHON", "VIRTUAL_ENV"))}
    try:
        vd = os.path.join(tmp, "venv")
        venv.create(vd, with_pip=True)
        py = os.path.join(vd, "bin", "python")
        run([py, "-m", "pip", "install", "-q", "--no-cache-dir", "--isolated", target], env=env, cwd=tmp)
        cl = os.path.join(tmp, "client.py"); open(cl, "w").write(CLIENT)
        run([py, cl, a.version, os.path.join(vd, "bin", PKG)], env=env, cwd=tmp)
        if a.uvx and not a.wheel:
            uvx = shutil.which("uvx") or sys.exit("uvx not found")
            run([py, cl, a.version, uvx, "--no-cache", spec], env=env, cwd=tmp)
        print("RESULT: ok")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
