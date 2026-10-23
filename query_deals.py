#!/usr/bin/env python3
"""Agent query client for the work-stack deal feed (smoke test). No auth. Read-only."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

DEFAULT_FEED = (
    "https://gist.githubusercontent.com/connormatthewdouglas/"
    "ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json"
)


def fetch(url: str) -> dict:
    # Gist CDN can lag; bust cache on every query for smoke-test freshness.
    join = "&" if ("?" in url) else "?"
    bust = f"{url}{join}_={int(__import__('time').time())}"
    req = urllib.request.Request(
        bust,
        headers={
            "User-Agent": "agent-deal-query/0.1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main() -> int:
    p = argparse.ArgumentParser(description="Query the agent work-stack deal feed")
    p.add_argument("--feed", default=DEFAULT_FEED, help="Feed URL (default: live smoke-test gist)")
    p.add_argument("--category", help="Filter by category (compute, unblock, templates, search, hosting)")
    p.add_argument("--max-price", type=float, help="Max price_usd inclusive")
    p.add_argument("--tag", action="append", default=[], help="Require tag (repeatable)")
    p.add_argument("--agent-only", action="store_true", help="Only agent_only=true deals")
    p.add_argument("--include-examples/--real-only", dest="examples", default=True,
                   action=argparse.BooleanOptionalAction,
                   help="Include example=true deals (default: include; use --real-only to skip)")
    p.add_argument("--id", help="Fetch one deal by id")
    p.add_argument("--json", action="store_true", help="Print raw JSON array of matches")
    args = p.parse_args()

    try:
        data = fetch(args.feed)
    except Exception as e:
        print(f"error: failed to fetch feed: {e}", file=sys.stderr)
        return 1

    deals = list(data.get("deals") or [])

    if args.id:
        deals = [d for d in deals if d.get("id") == args.id]
    if args.category:
        deals = [d for d in deals if d.get("category") == args.category]
    if args.max_price is not None:
        deals = [d for d in deals if float(d.get("price_usd", 1e18)) <= args.max_price]
    if args.tag:
        deals = [d for d in deals if set(args.tag).issubset(set(d.get("tags") or []))]
    if args.agent_only:
        deals = [d for d in deals if d.get("agent_only") is True]
    if not args.examples:
        deals = [d for d in deals if not d.get("example")]

    if args.json:
        json.dump(deals, sys.stdout, indent=2)
        print()
        return 0

    print(f"feed: {data.get('title', 'unknown')} | matches: {len(deals)}")
    for d in deals:
        print(
            f"- {d.get('id')}: {d.get('title')} | "
            f"${d.get('price_usd')} / {d.get('unit')} | "
            f"cat={d.get('category')} | code={d.get('promo_code')} | "
            f"{d.get('redeem_url')}"
        )
        if d.get("agent_instructions"):
            print(f"  instructions: {d['agent_instructions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
