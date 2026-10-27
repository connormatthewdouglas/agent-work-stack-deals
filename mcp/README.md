# Lantern Works — MCP discovery (sketch)

> **Status (2026-10-26):** a working server now lives in `mcp_server/` (local stdio, official Python SDK). This folder is the original design sketch.

> **Status: not hosted.** No Lantern Works MCP server is running; this folder is a design sketch. Agents should `GET https://thelanternworks.com/deals.json` directly.

Read-only MCP surface over the **public** agent work-stack deal feed. No auth. No spend. Work-stack niche only (compute, hosting, search, crawl, unblock, email, templates) — not consumer affiliate shopping.

## Why this exists
AI agents need a discoverable way to find Lantern Works inventory beyond pasting a URL. This folder is the **discovery artifact**: what tools exist, how they map to `deals.json`, and how a thin server could wrap the feed.

## Live surfaces (already public)
| Surface | URL |
|---|---|
| JSON feed | https://thelanternworks.com/deals.json |
| Human page | https://thelanternworks.com/lanternworks/ |
| Deals list | https://thelanternworks.com/ |
| Agent Skill | [../skills/lantern-works-deals/SKILL.md](../skills/lantern-works-deals/SKILL.md) (live: https://thelanternworks.com/SKILL.md) |
| Query CLI | [../query_deals.py](../query_deals.py) · [../USAGE.md](../USAGE.md) |

## Filter contract
Shared with the feed `query` object and `query_deals.py`: `category`, `affiliate`, `free_tier` / `non_affiliate` (`affiliate==false`), `updated_since`, `tag`, `agent_only`, `max_price_usd`, `include_examples` (default false = real-only), `id`. See [MCP_SPEC.md](./MCP_SPEC.md).

## Files in this folder
- `MCP_SPEC.md` — tool contracts (`list_deals`, `search_deals`, `get_deal`)
- `tools.manifest.json` — machine-readable tool list for directories / installers
- `server.stub.md` — how a stdio/HTTP stub would fetch the feed (not hosted yet)
- `README.md` — this file

## Rules for implementers
1. Default **exclude** `example: true` deals unless the caller sets `include_examples` (production inventory is real Lantern Works listings).
2. Rank by fit and verified price; affiliate status is not a ranking factor. Never invent merchant links or codes. Public/non-affiliate free tiers use `affiliate: false`.
3. Affiliate disclosure: some links are affiliate links (`affiliate: true`); Lantern Works may earn a commission. Price and ranking unchanged.
4. Contact: lanternworks@agentmail.to
