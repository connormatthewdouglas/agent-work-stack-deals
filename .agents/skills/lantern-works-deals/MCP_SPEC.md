# Lantern Works deals — MCP server sketch (optional)

Read-only wrapper around the public JSON feed. **No auth. No spend. Do not host a paid server as part of this draft.**

## Transport
- Suggested: stdio or HTTP MCP server that fetches  
  `https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json`  
  on each call (or short TTL cache ≤5 minutes).

## Tools

### `list_deals`
List deals from the feed.
- Args (all optional): `category` (string), `tag` (string), `agent_only` (bool), `include_examples` (bool, default false), `max_price_usd` (number)
- Behavior: return matching deals; **default exclude** `example: true`.
- Returns: array of `{ id, title, category, tags, price_usd, unit, redeem_url, affiliate, example, agent_instructions, expires_at }`

### `search_deals`
Free-text search over title, tags, advertiser, agent_instructions.
- Args: `q` (string, required), plus same filters as `list_deals`
- Returns: ranked matches (simple substring / token score is enough for v0)

### `get_deal`
- Args: `id` (string, required)
- Returns: one deal object or not_found

## Resources (optional)
- `lanternworks://deals` — raw feed JSON
- `lanternworks://human` — https://connormatthewdouglas.github.io/agent-work-stack-deals/lanternworks/

## Non-goals (v0)
- Checkout, payments, payout rails, vendor outreach
- Consumer affiliate networks (Cuelinks-style shopping)
- Mutating the feed

## Niche vs peers
Peers (Cuelinks, Feedico, Godalo, Cuanto) mostly target consumer affiliate shopping. This MCP is **agent work-stack** only: compute, hosting, search, crawl, unblock, templates, related APIs.
