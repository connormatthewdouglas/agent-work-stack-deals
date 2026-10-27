# MCP server stub notes (not hosted)

Thin read-only server. **Do not** add auth, checkout, or paid hosting in v0.

## Behavior
On each tool call (or with ≤5 min cache):
1. `GET` `feed_url` from `tools.manifest.json` (add cache-buster query if CDN lags).
2. Parse `deals` array.
3. Apply the shared filter contract (`category`, `affiliate`, `free_tier`/`non_affiliate`, `updated_since`, `tag`, `agent_only`, `max_price_usd`, `id`). Unless `include_examples`, drop objects with `"example": true` (real-only default).
4. Return compact JSON (id, title, category, tags, price_usd, unit, redeem_url, affiliate, example, agent_instructions, expires_at, updated_at).

### free_tier / non_affiliate
Map to `affiliate == false` (public free tiers). `price_usd: null` means unknown, not free.

### updated_since
ISO-8601 compare against `deal.updated_at`. Rows missing `updated_at` are excluded when this filter is set.

## Stdio sketch
- Package name suggestion: `lantern-works-deals-mcp`
- Entry: read MCP requests on stdin, write responses on stdout
- Config: optional `LANTERN_WORKS_FEED_URL` override (default = public gist)
- Reference CLI filters: repo `query_deals.py`

## HTTP sketch
- `POST /mcp` or streamable HTTP per MCP HTTP transport
- Health: `GET /health` → `{ ok: true, feed_url }`

## Discovery
Point directories / install docs at:
- this repo’s `mcp/tools.manifest.json`
- Agent Skill: `skills/lantern-works-deals/SKILL.md` (live: https://thelanternworks.com/SKILL.md)

## Non-goals
Payout rails, vendor outreach, consumer affiliate networks, mutating the feed.
