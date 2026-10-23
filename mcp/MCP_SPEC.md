# Lantern Works deals — MCP server sketch

Read-only wrapper around the public JSON feed. **No auth. No paid server required for this sketch.**

See also: [README.md](./README.md) · [tools.manifest.json](./tools.manifest.json) · [server.stub.md](./server.stub.md)

## Feed
https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json

## Tools

### `list_deals`
List deals from the feed.
- Args (all optional): `category`, `tag`, `agent_only`, `include_examples` (default false), `max_price_usd`
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
