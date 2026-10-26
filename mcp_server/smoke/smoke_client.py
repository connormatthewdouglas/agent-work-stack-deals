"""Smoke test: spawn the server over stdio with the official MCP client and call each tool."""
import asyncio, json, sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server" / "server.py")])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        print("server:", init.serverInfo.name, init.serverInfo.version)
        print("tools:", [t.name for t in (await s.list_tools()).tools])
        async def call(name, args):
            res = await s.call_tool(name, args)
            data = json.loads(res.content[0].text)
            print(f"\n== {name} {json.dumps(args)}\n{json.dumps(data, indent=1)[:1500]}")
            return data
        r1 = await call("search_deals", {"query": "proxy", "limit": 3})
        await call("search_deals", {"category": "search", "offer_type": "free_tier", "limit": 2})
        ids = [x["id"] for x in r1["results"][:2]]
        await call("compare_deals", {"ids": ids})
        await call("get_deal", {"id": ids[0]})
        await call("get_deal", {"id": "does-not-exist"})

asyncio.run(main())
