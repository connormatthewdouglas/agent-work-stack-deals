# Agent query client

Production Lantern Works feed (public, no auth). Default excludes `example: true` rows (`--real-only`).
Default **array order** in the feed: **customer value** (`query.sort.default` = `customer_value`): real discounts, then verified free tiers, then standard signups, A–Z by vendor. Affiliate status is not a ranking factor. Homepage and category hubs use the same rule.

```bash
python3 query_deals.py
python3 query_deals.py --category unblock --max-price 20
python3 query_deals.py --tag proxy --json
python3 query_deals.py --id deal-firecrawl-001
python3 query_deals.py --affiliate
python3 query_deals.py --free-tier            # affiliate=false (public/non-affiliate)
python3 query_deals.py --no-affiliate         # same as --free-tier
python3 query_deals.py --updated-since 2026-10-23T00:00:00-04:00
python3 query_deals.py --include-examples     # keep synthetic example=true rows
```

## Filter contract

| Filter | CLI | Meaning |
|---|---|---|
| `category` | `--category` | Exact `deal.category` |
| `affiliate` | `--affiliate` / `--no-affiliate` | `affiliate` true/false |
| `free_tier` / `non_affiliate` | `--free-tier` / `--non-affiliate` | `affiliate == false` (public free tiers). `price_usd: null` means unknown, not free. |
| `updated_since` | `--updated-since ISO8601` | Keep deals with `updated_at >=` timestamp; rows missing `updated_at` are dropped |
| `tag` | `--tag` (repeatable, AND) | Require tags |
| `agent_only` | `--agent-only` | `agent_only == true` |
| `max_price` | `--max-price` | Inclusive max `price_usd` |
| `real_only` | default / `--real-only` | Exclude `example == true` |
| `id` | `--id` | Exact deal id |

Machine-readable copy: `deals.json` → `query` object.

Default feed: `https://thelanternworks.com/deals.json` (mirror: `https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json`)
