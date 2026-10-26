#!/usr/bin/env python3
"""Agent query client for the Lantern Works work-stack deal feed. No auth. Read-only."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any

DEFAULT_FEED = "https://thelanternworks.com/deals.json"


def fetch(url: str) -> dict:
    # Gist CDN can lag; bust cache on every query for freshness.
    join = "&" if ("?" in url) else "?"
    bust = f"{url}{join}_={int(__import__('time').time())}"
    req = urllib.request.Request(
        bust,
        headers={
            "User-Agent": "agent-deal-query/0.2",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def parse_when(value: str) -> datetime:
    """Parse ISO-8601; accept trailing Z."""
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"invalid ISO-8601 datetime for --updated-since: {value!r}"
        ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def deal_updated_at(deal: dict[str, Any]) -> datetime | None:
    raw = deal.get("updated_at")
    if not raw:
        return None
    try:
        return parse_when(str(raw))
    except argparse.ArgumentTypeError:
        return None


def apply_filters(deals: list[dict], args: argparse.Namespace) -> list[dict]:
    out = list(deals)

    if args.id:
        out = [d for d in out if d.get("id") == args.id]
    if args.category:
        out = [d for d in out if d.get("category") == args.category]
    if args.max_price is not None:
        out = [d for d in out if d.get("price_usd") is not None and float(d["price_usd"]) <= args.max_price]  # null = unknown, excluded
    if args.tag:
        out = [d for d in out if set(args.tag).issubset(set(d.get("tags") or []))]
    if args.agent_only:
        out = [d for d in out if d.get("agent_only") is True]

    # affiliate true/false (explicit). --free-tier / --non-affiliate => affiliate=false.
    affiliate_wanted: bool | None = args.affiliate
    if args.free_tier or args.non_affiliate:
        if affiliate_wanted is True:
            raise ValueError(
                "--free-tier/--non-affiliate conflicts with --affiliate"
            )
        affiliate_wanted = False
    if affiliate_wanted is not None:
        out = [d for d in out if bool(d.get("affiliate")) is affiliate_wanted]

    if args.updated_since is not None:
        since = args.updated_since
        out = [
            d
            for d in out
            if (ts := deal_updated_at(d)) is not None and ts >= since
        ]

    # Default: real-only (exclude example=true). --include-examples keeps them.
    if args.real_only:
        out = [d for d in out if not d.get("example")]

    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Query the Lantern Works agent work-stack deal feed "
            "(production inventory; public, no auth)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Filter contract (also in deals.json → query.filters):
  category       Exact category (compute, email, hosting, search, unblock, …)
  affiliate      --affiliate / --no-affiliate
  free_tier      --free-tier or --non-affiliate  (= affiliate=false; public free tiers)
  updated_since  --updated-since ISO8601         (requires deal.updated_at)
  tag            --tag (repeatable, AND)
  agent_only     --agent-only
  max_price      --max-price N
  real_only      default on; --include-examples to keep example=true
  id             --id deal-…
""",
    )
    p.add_argument(
        "--feed",
        default=DEFAULT_FEED,
        help="Feed URL (default: https://thelanternworks.com/deals.json)",
    )
    p.add_argument(
        "--category",
        help="Filter by category (compute, email, hosting, search, unblock, …)",
    )
    p.add_argument("--max-price", type=float, help="Max price_usd inclusive")
    p.add_argument("--tag", action="append", default=[], help="Require tag (repeatable)")
    p.add_argument("--agent-only", action="store_true", help="Only agent_only=true deals")
    p.add_argument(
        "--affiliate",
        dest="affiliate",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="Filter affiliate=true (--affiliate) or affiliate=false (--no-affiliate)",
    )
    p.add_argument(
        "--free-tier",
        action="store_true",
        help="Non-affiliate free/public offers (affiliate=false; price_usd null = unknown)",
    )
    p.add_argument(
        "--non-affiliate",
        action="store_true",
        help="Alias of --free-tier (affiliate=false)",
    )
    p.add_argument(
        "--updated-since",
        type=parse_when,
        help="Keep deals with updated_at >= this ISO-8601 timestamp",
    )
    # Default real-only=True. --include-examples turns it off; --real-only is explicit.
    p.add_argument(
        "--real-only",
        dest="real_only",
        action="store_true",
        default=True,
        help="Exclude example=true deals (default)",
    )
    p.add_argument(
        "--include-examples",
        dest="real_only",
        action="store_false",
        help="Include example=true (synthetic) deals",
    )
    p.add_argument("--id", help="Fetch one deal by id")
    p.add_argument("--json", action="store_true", help="Print raw JSON array of matches")
    args = p.parse_args()

    try:
        data = fetch(args.feed)
    except Exception as e:
        print(f"error: failed to fetch feed: {e}", file=sys.stderr)
        return 1

    try:
        deals = apply_filters(list(data.get("deals") or []), args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        json.dump(deals, sys.stdout, indent=2)
        print()
        return 0

    print(f"feed: {data.get('title', 'unknown')} | matches: {len(deals)}")
    for d in deals:
        print(
            f"- {d.get('id')}: {d.get('title')} | "
            f"${d.get('price_usd')} / {d.get('unit')} | "
            f"cat={d.get('category')} | affiliate={d.get('affiliate')} | "
            f"code={d.get('promo_code')} | "
            f"{d.get('redeem_url')}"
        )
        if d.get("agent_instructions"):
            print(f"  instructions: {d['agent_instructions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
