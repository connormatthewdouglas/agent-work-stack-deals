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

## Stock-claim audit fields

`compare_gpu_prices` rows (full: inside `availability`; brief: on the row) carry these when a stock claim exists:

| Field | Meaning |
|---|---|
| `first_read_at`, `second_read_at` | UTC times of the two stock reads behind the claim |
| `second_read_gap_s` | Seconds between the two reads (the field is `second_read_gap_s`, not `gap_s`) |
| `second_read_basis` | What the second read was |
| `two_read_gap_ok` | `true` when `second_read_gap_s` >= 60; claims under 60 s are not counted |
| `stock_read_at`, `price_read_at`, `price_at_claim_usd` | When stock and price were read, and the per-GPU price the claim was read against |
| `price_join_failed` | The claim's price no longer matches the row, so the claim is not shown as live |

Brief rows also carry `gpu_count` (GPUs per server; per-GPU price is `price_usd`).
