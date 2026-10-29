# Lantern Works GPU prices — MCP server (v0.3.9, read-only, stdio)

mcp-name: io.github.connormatthewdouglas/lantern-works-deals

Free, read-only, no API key. **GPU price comparison for agents, checked daily:** `compare_gpu_prices` returns hourly rental prices for H100, A100, RTX 4090 and more across tracked providers, cheapest first, each with the vendor's source page and check date; `include_history=true` adds daily price history and recent changes. Also prices the cheapest stack for your monthly usage (`optimize_stack`) and, last, searches and compares AI-infra deals and free tiers, ranked by customer value (never by affiliate status). Some result links are referral links.

## Quick start

```bash
uvx lantern-works-deals-mcp
```

Claude Code:

```bash
claude mcp add lantern-works-deals -- uvx lantern-works-deals-mcp
```

Cursor (`.cursor/mcp.json`), Cline (`cline_mcp_settings.json`) and Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "lantern-works-deals": {
      "command": "uvx",
      "args": ["lantern-works-deals-mcp"]
    }
  }
}
```

Without uv: `pip install lantern-works-deals-mcp`, then use `"command": "lantern-works-deals-mcp"`. Docker (from the repo root; installs the pinned PyPI release): `docker build -t lantern-works-deals-mcp . && docker run -i --rm lantern-works-deals-mcp`. More clients: https://thelanternworks.com/install/

## Tools

| Tool | Args | Returns |
|---|---|---|
| `compare_gpu_prices` | `gpu` (e.g. `H100`, `A100 SXM`, `RTX 4090`), `limit` (1-25, default 10), `include_history` (default false), `on_demand_only` (bool, default false) | `{summary, scope, total, results[], data_source, feed_updated_at, ...}` sorted by `hourly_usd`; each result has `source_url` and `checked_at`. With `include_history=true`, each result adds `price_history` (daily-snapshot change points) and the response adds `history.recent_changes` (last 30 days) |
| `get_price_changes` | `since` (`YYYY-MM-DD`, optional), `gpu` (substring filter, optional), `limit` (1-200, default 50) | GPU price moves among tracked providers, newest first (drops, rises, removals, then newly tracked rates): `from_hourly_usd`, `to_hourly_usd`, `change_pct`, `direction`, `source_url`; `window`, counts, `data_checked_at`, `next_refresh_utc`. Without `since`, the latest day (/api/v1/gpu-price-changes.json); with it, /api/v1/gpu-prices/history.json. Bad date → `invalid_argument` |
| `optimize_stack` | `scrape_pages`, `scrape_pages_js`, `proxy_gb`, `emails_sent`, `search_queries`, `gpu_hours`, `gpu_model`, `exclude_manual_signup` | per-line chosen plan, `monthly_cost_usd`, calc, vendor quote, `source_url`, `checked_at`, assumptions, alternatives; unpublished prices are `unknown` |
| `optimize_agent_stack` | `description` (free text) plus optional `workload`, `gpu_hours`, `gpu_model`, `model_size_b`, `scrape_pages`, `js_rendering`, `proxy_gb`, `search_queries`, `emails_sent`, `llm_api`, `monthly_budget_usd`, `exclude_manual_signup` | `parsed` (what the deterministic parse found), per-component cheapest cited option with calc, `source_url`, `verified_at`, `referral_disclosure`, manual-signup notes; `monthly_estimate_usd` with `estimate_math` and `estimate_is_complete`; "no sourced price tracked" where there is no data |
| `search_deals` | `query`, `category`, `offer_type`, `max_price`, `tags[]`, `limit` (1-25, default 10), `cursor` | `{total, count, results[], next_cursor}` (summary fields only) |
| `compare_deals` | `ids` (2-5) | `{order, deals[], note}` best value first |
| `get_deal` | `id` | the deal's public record |

`compare_gpu_prices` uses exactly the data published at https://thelanternworks.com/api/v1/gpu-prices.json (history: https://thelanternworks.com/api/v1/gpu-prices/history.json). Prices are re-read daily from each vendor's own page or API and change only where a price was parsed; a rate not re-verified for 7 days is held out of rankings. Model matching is by whole tokens (`H100` matches `H100 SXM`; `L40` does not match `L40S`). "Cheapest" means cheapest among tracked providers, not the whole market.

Errors: `{"error": {"code": "invalid_argument|invalid_cursor|not_found|feed_unavailable|feed_invalid", "message": ...}}`.

## Data and privacy

Deals: `https://thelanternworks.com/api/v1/deals.json`; stack pricing: `https://thelanternworks.com/api/v1/stack-pricing.json`; GPU prices: `https://thelanternworks.com/api/v1/gpu-prices.json`. Each is cached 5 min (a stale copy is served if a refetch fails). Requests send only `User-Agent: lantern-works-deals-mcp/<version>` (no user, host or install identifiers). Overrides: `LANTERN_DEALS_FILE` / `LANTERN_DEALS_URL`, `LANTERN_GPU_PRICES_FILE` / `LANTERN_GPU_PRICES_URL`, `LANTERN_STACK_PRICING_FILE` / `LANTERN_STACK_PRICING_URL`. Only an allow-list of public fields is returned.

**Telemetry: off by default.** Opt in with `LANTERN_TELEMETRY=1` to send an anonymous daily count of tool calls. Each count is only the tool name, package version, UTC day and number of calls. No arguments, IDs or IPs are sent or stored. It is batched to at most one request per day and never blocks or breaks a tool call. Details: [PRIVACY.md](https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/PRIVACY.md).

## From git (fallback)

```bash
git clone https://github.com/connormatthewdouglas/agent-work-stack-deals.git
cd agent-work-stack-deals
python3 -m venv .venv && .venv/bin/pip install -r mcp_server/requirements.txt
.venv/bin/python mcp_server/server.py
```

## Test

```bash
.venv/bin/pip install pytest && .venv/bin/python -m pytest -q tests
python3 scripts/test_pypi_install.py --uvx   # clean venv + uvx install from PyPI, calls every tool over stdio
```

## Package

`pyproject.toml` at the repo root builds `lantern-works-deals-mcp` (MIT) with a `lantern-works-deals-mcp` console command. Published on [PyPI](https://pypi.org/project/lantern-works-deals-mcp/) and in the MCP Registry as `io.github.connormatthewdouglas/lantern-works-deals`.
