"""Terminal demo: "cheapest H100 for 100 hours?" answered by the Lantern Works MCP server.

Starts `uvx lantern-works-deals-mcp` over stdio, calls compare_gpu_prices(gpu="H100"),
and prints 100-hour totals with each rate's source and check time. Live data.
Requires: pip install mcp ; uv on PATH.
"""
import asyncio, json, sys, time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HOURS = 100
B, D, G, Y, C, R = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"


def say(s="", pause=0.35):
    print(s, flush=True); time.sleep(pause * 2.4)


async def main():
    say(f"{B}Q: cheapest H100 for {HOURS} hours?{R}", 1.0)
    say(f"{D}$ uvx lantern-works-deals-mcp   # MCP server over stdio{R}", 0.6)
    params = StdioServerParameters(command="uvx", args=["lantern-works-deals-mcp"])
    async with stdio_client(params, errlog=open("/dev/null", "w")) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            say(f'{D}-> tools/call compare_gpu_prices {{"gpu": "H100", "limit": 20}}{R}', 0.8)
            res = await s.call_tool("compare_gpu_prices", {"gpu": "H100", "limit": 20})
    data = json.loads(res.content[0].text)
    rows = data["results"]
    say(f"{D}{len(rows)} tracked H100 rates (cheapest among tracked providers only, not the whole market){R}", 0.8)
    say()
    say(f"{B}{'#':>2}  {'provider / GPU / tier':<52} {'$/hr':>7} {'100h':>9}{R}", 0.2)
    for x in rows[:5] + ([None] if len(rows) > 6 else []) + ([rows[-1]] if len(rows) > 5 else []):
        if x is None:
            say(f"{D}    ...{R}", 0.2); continue
        name = f"{x['advertiser']} {x['gpu']} ({x.get('tier')})"[:52]
        ref = f" {Y}[referral link]{R}" if x.get("affiliate") else ""
        say(f"{x['rank']:>2}  {name:<52} {x['hourly_usd']:>7.2f} {x['hourly_usd']*HOURS:>9.2f}{ref}", 0.3)
    lo, nxt, hi = rows[0], rows[1], rows[-1]
    t = lambda x: x["hourly_usd"] * HOURS
    say()
    say(f"{G}{B}Cheapest: {lo['advertiser']} {lo['gpu']} = ${t(lo):,.2f} for {HOURS}h{R}", 0.6)
    say(f"  vs next  ({nxt['advertiser']} {nxt['gpu']}): ${t(nxt):,.2f}  -> difference ${t(nxt)-t(lo):,.2f}", 0.6)
    say(f"  vs most expensive tracked ({hi['advertiser']} {hi['gpu']}): ${t(hi):,.2f}  -> difference ${t(hi)-t(lo):,.2f}", 0.8)
    ts = lo.get("verified_at") or lo.get("checked_at")
    say(f"  source: {C}{lo['source_url']}{R}", 0.3)
    say(f"  price checked at: {ts} (UTC)", 0.3)
    if lo.get("affiliate"):
        say(f"  {Y}note: this provider's redeem_url is a referral link; source_url is the vendor's own pricing page{R}", 0.3)
    say(f"{D}Excludes storage, egress and taxes. Confirm on the vendor page before renting.{R}", 2.5)


if __name__ == "__main__":
    asyncio.run(main())
