# lantern-works-deals plugin

A Claude Code and Cursor plugin that bundles the Lantern Works deals skill (`skills/lantern-works-deals/SKILL.md`) with the
read-only Lantern Works MCP server (`uvx lantern-works-deals-mcp`, stdio, no API key, MIT). Agents use it to compare tracked
GPU rental prices and AI-infrastructure plans, deals and free tiers.

## Tools
- `search_deals`: search tracked deals by query, category or offer type
- `compare_deals`: compare 2 to 5 deals side by side
- `get_deal`: one deal's public record by id
- `compare_gpu_prices`: cheapest tracked rates for a GPU model (`include_history` adds price change points)
- `optimize_stack`: cheapest suitable stack among tracked providers for stated monthly usage

## Install
- Claude Code: `claude plugin marketplace add connormatthewdouglas/agent-work-stack-deals`, then `claude plugin install lantern-works-deals@lantern-works`
- Cursor: install from the Cursor Marketplace once listed, or copy this folder to `~/.cursor/plugins/local/lantern-works-deals`
- Any MCP client: command `uvx`, args `["lantern-works-deals-mcp"]`. See https://thelanternworks.com/install/

## Disclosure
Some result links are referral links (results marked `affiliate: true` have a referral `redeem_url`). Results are ranked by
customer value, never by affiliate status. Each result's `source_url` is the vendor's own pricing page. Prices cover tracked
providers only. Confirm on the vendor page before spending.
