# Lantern Works deals — MCP server sketch

Read-only wrapper around the public JSON feed. **No auth. No paid server required for this sketch.**

See also: [README.md](./README.md) · [tools.manifest.json](./tools.manifest.json) · [server.stub.md](./server.stub.md)

## Feed
https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json

Machine-readable filter contract: feed `query.filters` (keep in sync with `query_deals.py` and this spec).

## Filter contract (shared)
| Arg | Type | Meaning |
|---|---|---|
| `category` | string | Exact `deal.category` |
| `affiliate` | boolean | `true` / `false` referral vs public |
| `free_tier` | boolean | If true, same as `affiliate=false` (public/non-affiliate free tiers; often `price_usd: 0`). Not `price_usd==0` alone. |
| `non_affiliate` | boolean | Alias of `free_tier` |
| `updated_since` | string (ISO-8601) | Keep deals with `updated_at >=` value; drop rows missing `updated_at` |
| `tag` | string | Require tag (servers may accept repeated / array) |
| `agent_only` | boolean | Only `agent_only == true` |
| `max_price_usd` | number | Inclusive max on `price_usd` |
| `include_examples` | boolean | Default **false** (real-only). Synthetic `example: true` rows excluded unless set. |
| `id` | string | Exact deal id (`get_deal`) |

## Tools

### `list_deals`
List deals from the feed.
- Args (all optional): `category`, `tag`, `agent_only`, `affiliate`, `free_tier`, `non_affiliate`, `updated_since`, `include_examples` (default false), `max_price_usd`
- Default: exclude `example: true`
- Returns: deal summaries with `redeem_url`

### `search_deals`
Free-text search over title, tags, advertiser, agent_instructions.
- Args: `q` (required) + same filters as `list_deals`

### `get_deal`
- Args: `id` (required)

## Resources (optional)
- `lanternworks://deals` — raw feed JSON
- `lanternworks://human` — https://connormatthewdouglas.github.io/agent-work-stack-deals/lanternworks/

## Niche vs peers
Consumer MCP affiliate tools (Cuelinks, Feedico, etc.) are out of scope. This is **agent work-stack** only.
