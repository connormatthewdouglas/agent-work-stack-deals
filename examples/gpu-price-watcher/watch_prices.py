"""Print tracked GPU rental price moves since a date, using get_price_changes from the Lantern Works MCP server.

Launches `uvx lantern-works-deals-mcp` (0.3.8+) over stdio with the official `mcp` Python SDK. No API key, no LLM.

Usage: python watch_prices.py [YYYY-MM-DD] [--gpu H100] [--limit 50] [--json]
       (no date = the latest day's moves)
       python watch_prices.py --state watcher-state.json [--gpu H100]
       (durable catch-up: pages every history event after the saved cursor, oldest first, and saves the cursor only
        after a page is handled, so a crash or a missed day re-reads, never skips; handle events idempotently by
        event_id)
"""
import argparse
import asyncio
import base64
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


START_CURSOR = base64.urlsafe_b64encode(b'{"v":1,"seq":0,"eid":null}').decode().rstrip("=")  # before the first event


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"cursor": START_CURSOR, "seen": 0}


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic: a crash leaves the old cursor, so events are re-read, never lost


async def catch_up(call, state_path, handle, gpu=None, limit=200):
    """call(name, args) -> tool result dict. Pages get_price_changes by cursor until has_more is false."""
    st = load_state(state_path)
    n = 0
    while True:
        args = {"cursor": st["cursor"], "limit": limit}
        if gpu:
            args["gpu"] = gpu
        page = await call("get_price_changes", args)
        if "error" in page:
            raise RuntimeError(f"get_price_changes failed: {page['error']}")
        for c in page.get("changes", []):
            handle(c)
            n += 1
        if page.get("next_cursor"):
            st = {"cursor": page["next_cursor"], "seen": st.get("seen", 0) + len(page.get("changes", []))}
            save_state(state_path, st)
        if not page.get("has_more"):
            return n


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("since", nargs="?", help="YYYY-MM-DD; omit for the latest day's moves")
    ap.add_argument("--gpu", help="model filter, e.g. H100")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--json", action="store_true", help="print the full tool result")
    ap.add_argument("--state", help="checkpoint file for durable catch-up (cursor mode)")
    a = ap.parse_args()
    if a.state:
        params = StdioServerParameters(command="uvx", args=["lantern-works-deals-mcp"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args):
                res = await session.call_tool(name, args)
                return json.loads(res.content[0].text)
            n = await catch_up(call, a.state, lambda c: print(f"  {c['date']} {c['vendor']} {c['gpu']} [{c.get('tier')}] "
                                                            f"{c.get('from_hourly_usd')} -> {c.get('to_hourly_usd')} ({c['event_id']})"), a.gpu)
        print(f"{n} new event(s); cursor saved to {a.state}")
        return
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
