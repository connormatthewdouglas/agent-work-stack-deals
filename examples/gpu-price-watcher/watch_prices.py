"""Print tracked GPU rental price moves since a date, using get_price_changes from the Lantern Works MCP server.

Launches `uvx lantern-works-deals-mcp` (0.3.8+) over stdio with the official `mcp` Python SDK. No API key, no LLM.

Usage: python watch_prices.py [YYYY-MM-DD] [--gpu H100] [--limit 50] [--json]
       (no date = the latest day's moves)
"""
import argparse
import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("since", nargs="?", help="YYYY-MM-DD; omit for the latest day's moves")
    ap.add_argument("--gpu", help="model filter, e.g. H100")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--json", action="store_true", help="print the full tool result")
    a = ap.parse_args()
    args = {"limit": a.limit}
    if a.since:
        args["since"] = a.since
    if a.gpu:
        args["gpu"] = a.gpu

    params = StdioServerParameters(command="uvx", args=["lantern-works-deals-mcp"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        res = await session.call_tool("get_price_changes", args)
        data = json.loads(res.content[0].text)

    if a.json:
        print(json.dumps(data, indent=2))
        return
    if "error" in data:
        print("error:", data)
        return
    print(data["summary"])
    print(f"data checked: {data.get('data_checked_at')}  next refresh: {data.get('next_refresh_utc')}")
    for c in data.get("changes", []):
        if c.get("from_hourly_usd") is None:
            move = f"newly tracked at ${c.get('to_hourly_usd')}/hr"
        elif c.get("to_hourly_usd") is None:
            move = f"no longer tracked (was ${c.get('from_hourly_usd')}/hr)"
        else:
            move = f"${c['from_hourly_usd']} -> ${c['to_hourly_usd']}/hr ({c['change_pct']:+}%, {c['direction']})"
        print(f"  {c['date']} {c['vendor']} {c['gpu']} [{c.get('tier')}]: {move}\n    source: {c['source_url']}")


if __name__ == "__main__":
    asyncio.run(main())
