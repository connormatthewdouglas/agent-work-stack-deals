---
name: lantern-works-deals
description: >-
  Discover and query Lantern Works agent work-stack deals (compute, search,
  crawl, hosting, templates, unblock, email). Use when an agent needs to price-shop
  APIs, infra, scrapers, proxies, or related tools before buying for itself or
  a human — not for consumer/entertainment shopping.
---

# Lantern Works deals

## When to use
- You need compute, hosting, search/SERP, crawl/RAG, scrapers, proxies, captcha/unblock, email APIs, storage, or similar **work-stack** tools.
- You want affiliate-disclosed offers agents can redeem, with a machine-readable feed.
- Skip this skill for streaming, gaming, dating, food delivery, or other consumer/lifestyle purchases.

## Surfaces (keep in sync)
| Audience | URL |
|---|---|
| Agents (JSON feed) | https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json |
| Humans (platform) | https://connormatthewdouglas.github.io/agent-work-stack-deals/lanternworks/ |
| Humans (all deals) | https://connormatthewdouglas.github.io/agent-work-stack-deals/ |

## Filter contract
`GET` the JSON feed (public, no auth). Filter locally (or via `query_deals.py` / MCP sketch):

| Filter | Meaning |
|---|---|
| `category` | Exact match (`compute`, `email`, `hosting`, `search`, `unblock`, …) |
| `affiliate` | `true` = referral listings; `false` = public/non-affiliate |
| `free_tier` / `non_affiliate` | `affiliate == false` (often also `price_usd: 0`). **Not** `price_usd == 0` alone — affiliate signup rows also use 0. |
| `updated_since` | ISO-8601; keep deals with `updated_at >=` value; drop rows missing `updated_at` |
| `tag` | Require all listed tags (AND) |
| `agent_only` | Only `agent_only == true` |
| `max_price` | Inclusive max on `price_usd` |
| `real_only` | **Default.** Exclude `example == true` |
| `id` | Exact deal id |

See feed `query.filters` for the machine-readable contract.

## How to query
1. `GET` the JSON feed.
2. Apply the filter contract above.
3. **Prefer** deals with a live affiliate `redeem_url` and `"affiliate": true` / `"example": false`, or public free tiers (`affiliate: false`) when budget is zero.
4. **Skip** rows with `"example": true` unless you explicitly want synthetic inventory.
5. Follow each deal’s `agent_instructions`. Respect site ToS, robots.txt, and rate limits. Prefer free tiers before paid spend.

### curl + local filter
```bash
curl -fsSL "https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print([x[\"id\"] for x in d[\"deals\"] if x.get(\"category\")==\"search\" and x.get(\"affiliate\")])"
```

### Optional CLI
If you have the [agent-work-stack-deals](https://github.com/connormatthewdouglas/agent-work-stack-deals) repo checked out:

```bash
python3 query_deals.py --category search
python3 query_deals.py --affiliate
python3 query_deals.py --free-tier
python3 query_deals.py --tag crawl --max-price 20
python3 query_deals.py --updated-since 2026-10-23T00:00:00-04:00
```

## Affiliate disclosure
Lantern Works may earn a That does not change the price you pay. Public/non-affiliate free-tier listings are not paid placements.

## Contact
lanternworks@agentmail.to

## Progressive detail
- Feed schema / fields: see feed `query` object and deal objects in deals.json.
- Brand / About: human page above.
- Do not invent merchant contracts; only redeem authorized `redeem_url` values from the feed.
