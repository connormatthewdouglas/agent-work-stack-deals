# Lantern Works GPU prices — MCP server (v0.6.6, read-only, stdio)

mcp-name: io.github.connormatthewdouglas/lantern-works-deals

Free, read-only, no API key. **GPU price comparison for agents, refreshed regularly, with each price's age shown:** `compare_gpu_prices` returns hourly rental prices for H100, A100, RTX 4090 and more across tracked providers, cheapest first, each with the vendor's source page and check date; `include_history=true` adds daily price history (since 2026-10-27) and recent changes. Also prices the cheapest stack for your monthly usage (`optimize_stack`) and, last, searches and compares AI-infra deals and free tiers, ranked by customer value (never by affiliate status). Some result links are referral links.

## Quick start

```bash
uvx lantern-works-deals-mcp
```

Hosted URL: `https://lantern-works-mcp.lantern-works.workers.dev/mcp` (`?ref=` only tags which snippet was used). Local command: `uvx lantern-works-deals-mcp` (or `pip install lantern-works-deals-mcp`, then `lantern-works-deals-mcp`).

Hosted, nothing to install:

```bash
claude mcp add --transport http lantern-works-gpu-prices "https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme"
```

### First call

After you connect, copy and paste this tool call:

```
find_available_gpus(gpu="H100")
```

It returns H100 rates with a current in-stock check among tracked providers, with the hourly price, the vendor source page, and when stock was checked. Prices and stock change; the call always uses the current feed. Confirmed in-stock rows are ranked by stock freshness, then price.

**Claude Code**
```bash
claude mcp add --transport http lantern-works-gpu-prices "https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme-claude-code"
# or local stdio:
claude mcp add lantern-works-deals -- uvx lantern-works-deals-mcp
```

**Claude Desktop**: `claude_desktop_config.json` (Settings → Developer → Edit Config). Or add the hosted URL under Settings → Connectors → Add custom connector: `https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme-claude-desktop`
```json
{ "mcpServers": { "lantern-works-deals": { "command": "uvx", "args": ["lantern-works-deals-mcp"] } } }
```

**Cursor**: `~/.cursor/mcp.json` or `.cursor/mcp.json`
```json
{ "mcpServers": { "lantern-works-gpu-prices": { "url": "https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme-cursor" } } }
```

**VS Code (GitHub Copilot agent mode)**: `.vscode/mcp.json`
```json
{ "servers": { "lantern-works-gpu-prices": { "type": "http", "url": "https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme-vscode" } } }
```

**Windsurf (now Devin Desktop)**: `~/.config/devin/mcp_config.json` (older Windsurf builds: `~/.codeium/windsurf/mcp_config.json`)
```json
{ "mcpServers": { "lantern-works-gpu-prices": { "serverUrl": "https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme-windsurf" } } }
```

**Cline**: `cline_mcp_settings.json` (MCP Servers → Configure)
```json
{ "mcpServers": { "lantern-works-gpu-prices": { "type": "streamableHttp", "url": "https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme-cline" } } }
```

**OpenAI Codex CLI**
```bash
codex mcp add lantern-works-deals -- uvx lantern-works-deals-mcp
```

**Any other MCP client**: stdio `uvx lantern-works-deals-mcp`, or Streamable HTTP `https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme-other`. Without uv: `pip install lantern-works-deals-mcp`, then use `"command": "lantern-works-deals-mcp"`. Docker (from the repo root; installs the pinned PyPI release): `docker build -t lantern-works-deals-mcp . && docker run -i --rm lantern-works-deals-mcp`. More clients: https://thelanternworks.com/install/

### Hosted endpoint (no install)

Streamable HTTP, same read-only tools: `https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme`
(`claude mcp add --transport http lantern-works-deals https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=pypi-readme`). Free Cloudflare Worker; it stores anonymous daily call counts per tool (no arguments) and, for distinct-caller counts, a daily-salted SHA-256 hash of IP + user agent (raw IP and user agent are never stored; the day's salt is deleted when the UTC day ends; hashes are kept 120 days). Counts are public at https://lantern-works-mcp.lantern-works.workers.dev/stats. See [PRIVACY.md](https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/PRIVACY.md). `?ref=` only tags which link was used.

## Tools

| Tool | Args | Returns |
|---|---|---|
| `compare_gpu_prices` | `gpu` (e.g. `H100`, `A100 SXM`, `RTX 4090`), `limit` (1-25, default 10), `include_history` (default false), `on_demand_only` (bool, default **true** since 0.6.0; pass false for spot/community/marketplace rows, labelled by `tier_class`) | `{summary, scope, total, results[], data_source, feed_updated_at, ...}` sorted by `hourly_usd`; each result has `source_url`, `checked_at` and `report_issue_url`; the top 3 in-stock rows also have a short `rent_here` label (`Rent here`) and `rent_url` (the counted `/go/?src=mcp` booking link; same target as `tracked_url`). With `include_history=true`, each result adds `price_history` (daily-snapshot change points) and the response adds `history.recent_changes` (last 30 days) Returns `mode="brief"` by default since 0.5.0; pass `mode="full"` for every field. |
| `get_price_changes` | `since` (`YYYY-MM-DD`, optional), `gpu` (substring filter, optional), `limit` (1-200, default 50) | GPU price moves among tracked providers, newest first (drops, rises, removals, then newly tracked rates): `from_hourly_usd`, `to_hourly_usd`, `change_pct`, `direction`, `source_url`; `window`, counts, `data_checked_at`, `next_refresh_utc`. Without `since`, the latest day (/api/v1/gpu-price-changes.json); with it, /api/v1/gpu-prices/history.json. Bad date → `invalid_argument` |
| `get_price_trend` | `rate_id` (required), `windows` (optional, default `[7, 30]`) | 7d/30d trend from existing snapshots: `pct`, `direction`, `ranked_days`; `trend` is null with `trend_reason` for held_stale, no_source, or stale (>48h / undated) current rows; current sold_out does not blank windows (same history math as compare_gpu_prices). |
| `get_price_moves` | `period` (`daily` default or `weekly`), `limit` (1-25, default 10), optional `gpu`, `vendor`, `direction` | Biggest |pct| tracked price moves (2% deadband; held/stale days excluded). Same history math as get_price_trend; current sold_out does not blank windows. Live stock is stale-guarded at request time. |
| `find_available_gpus` | `gpu` (required), `gpus` (default 1), `region`, `vendor`, `on_demand_only` (default true), `limit` (1-25, default 10) | Confirmed live in-stock rows (`available`), confirmed `sold_out`, and `unknown` with a reason. Call-time stale guard (8h or shorter claim lifetime); never from static labels, `no_source`, or 7-day rates. Ranked by stock freshness then price. The top 3 in-stock `available[]` rows also have a short `rent_here` label (`Rent here`) and `rent_url` (the counted `/go/?src=mcp` booking link; same target as `tracked_url`). |
| `optimize_stack` | `scrape_pages`, `scrape_pages_js`, `proxy_gb`, `emails_sent`, `search_queries`, `gpu_hours`, `gpu_model`, `exclude_manual_signup` | per-line chosen plan, `monthly_cost_usd`, calc, vendor quote, `source_url`, `checked_at`, assumptions, alternatives; unpublished prices are `unknown` |
| `optimize_agent_stack` | `description` (free text) plus optional `workload`, `gpu_hours`, `gpu_model`, `model_size_b`, `scrape_pages`, `js_rendering`, `proxy_gb`, `search_queries`, `emails_sent`, `llm_api`, `monthly_budget_usd`, `exclude_manual_signup` | `parsed` (what the deterministic parse found), per-component cheapest cited option with calc, `source_url`, `verified_at`, `referral_disclosure`, manual-signup notes; `monthly_estimate_usd` with `estimate_math` and `estimate_is_complete`; "no sourced price tracked" where there is no data |
| `estimate_job_cost` | `gpu_family` (or its alias `gpu`; both must match), `gpus_per_job` (default 1), `job_hours` or `job_days` (wall-clock days; `job_hours = job_days × 24`) or (`work_units` + `throughput_units_per_gpu_hour`), optional `workload`, `allow_interruptible` (default false), `min_vram_gb`, `runs_per_month`, `top_n` (default 5), `max_data_age_hours` | cost of one job (compute subtotal), including multi-day multi-GPU jobs, cheapest current first (fresh on-demand rows lead; a degraded > 48 h price never ranks first while a fresh one exists, else `stale_fallback: true`): `results[]` with `rate_id`, `allocated_gpus`, `job_hours`, `job_days`, `source_url`, `verified_at`, data age, `tracked_url` (counted `/go/` booking link); the top 3 in-stock rows also have a short `rent_here` label (`Rent here`) and `rent_url` (the counted `/go/?src=mcp` booking link; same target as `tracked_url`); `assumptions`, `citations`, `missing_costs`, `budget_verdict`, `quote_id`. A multi-day quote is not a reservation. Inference workloads without your throughput use a cited MLPerf figure (`throughput_basis`, `throughput_source`); otherwise `not_found` "missing: throughput" |
| `rebuild_quote` | `receipt` (the `receipt` object returned by `optimize_stack`, `optimize_agent_stack` or `estimate_job_cost`; also accepts that object as a JSON string) | `receipt_intact` (unkeyed sha256 matches), `reproduced` (`true` only if each line recomputes and its `rate_id` and price match the pinned feed revision or that date's published daily snapshot; otherwise `"arithmetic_only"` with `provenance_verified: false`), per-line provenance, and revalidation against today's feed (`unchanged`, `price_changed`, `evidence_changed`, `held_today`, `not_in_feed_today`; flat plans `not_revalidated`). Nothing is re-ranked |
| `search_deals` | `query`, `category`, `offer_type`, `max_price`, `tags[]`, `limit` (1-25, default 10), `cursor` | `{total, count, results[], next_cursor}` (summary fields only) |
| `compare_deals` | `ids` (2-5) | `{order, deals[], note}` best value first |
| `get_deal` | `id` | the deal's public record |

`compare_gpu_prices` uses exactly the data published at https://thelanternworks.com/api/v1/gpu-prices.json (history: https://thelanternworks.com/api/v1/gpu-prices/history.json). Each price is read from the vendor's own page or API and carries its own check time; it changes only where a price was parsed; a rate not re-verified for 7 days is held out of rankings. Model matching is by whole tokens (`H100` matches `H100 SXM`; `L40` does not match `L40S`). "Cheapest" means cheapest among tracked providers, not the whole market.

Errors: `{"error": {"code": "invalid_argument|invalid_cursor|not_found|feed_unavailable|feed_invalid", "message": ...}}`.

## Uncited prices

A deal without a `source_url` plus a `verified_at` or `checked_at` date has no cited price: `search_deals`, `compare_deals` and `get_deal` return `price_usd` and `list_price_usd` as `null` with `price_null_reason: "no cited price"` (brief and full modes; brief rows always carry `list_price_usd` and `source_url` when the deal has one). Deals with a cited price have no `price_null_reason`. The public feeds (`/deals.json`, `/api/v1/deals.json`) apply the same rule.

## Hours cap

`optimize_stack`/`optimize_agent_stack` `gpu_hours`, `estimate_job_cost` `job_hours` (given, computed, or `job_days × 24`) and the browser calculator all accept at most 20,000 **hours, not GPU-hours** (wall-clock duration per GPU). 2,501 h on 8 GPUs is valid; 834 days is not (20,016 h). The GPU count has its own limit. Larger values return `invalid_argument`.

## Errors and isError

stdio and hosted use one rule (`core/contract.is_error`): `isError` is true exactly when the result is the error
envelope `{"ok": false, "error": {"code", "message"}}`. Invalid input (`invalid_argument`), an unknown or unsupported
GPU, vendor or workload (`not_found`) and upstream failures (`feed_unavailable`, `upstream_unavailable`, ...) are errors.
A valid query that matches nothing is **not** an error: `ok: true`, `count: 0`, an empty list, `isError: false`.
`structuredContent` is the same object in both cases. Arguments are checked the same way in both before the tool
runs: a missing required argument, a wrong JSON type or an unknown extra argument (schemas set
`additionalProperties: false`) returns `invalid_argument`. Unknown tool name is a protocol error, not a tool
result: hosted answers JSON-RPC error -32602, stdio returns the MCP SDK's `isError` text "Unknown tool".

## Retrieval status (cached data)

Every successful tool result carries `retrieval`: `{"status": "ok"|"degraded", "feeds": [...]}`. Each feed entry
has `last_successful_retrieval_at`, `last_refresh_attempt_at`, `last_refresh_outcome` (`ok`, `failed: <error>`,
`invalid: <error>`), `stale_cache` and `cache_age_s`. When a refresh fails (outage) or returns an unusable feed
(partial refresh), the last good copy is served and marked `degraded`. Policy: cached data answers current-price
questions for at most 60 minutes after the last successful retrieval; after that the tool returns
`feed_unavailable`. Price history and change logs stay readable from cache. A successful refresh clears the
degraded state. Price verification times (`checked_at`, `verified_at`) are separate and unchanged.

## Data and privacy

Deals: `https://thelanternworks.com/api/v1/deals.json`; stack pricing: `https://thelanternworks.com/api/v1/stack-pricing.json`; GPU prices: `https://thelanternworks.com/api/v1/gpu-prices.json`. Each is cached 5 min (a stale copy is served if a refetch fails). Requests send only `User-Agent: lantern-works-deals-mcp/<version>` (no user, host or install identifiers). Overrides: `LANTERN_DEALS_FILE` / `LANTERN_DEALS_URL`, `LANTERN_GPU_PRICES_FILE` / `LANTERN_GPU_PRICES_URL`, `LANTERN_STACK_PRICING_FILE` / `LANTERN_STACK_PRICING_URL`. Only an allow-list of public fields is returned.

**Telemetry: off by default.** Opt in with `LANTERN_TELEMETRY=1` to send an anonymous daily count of tool calls. What is sent: tool name (`t`), package version (`v`), UTC day (`d`), call count (`n`), a random install id (`install_id`) stored locally at `~/.config/lantern-works/install_id` (or `$XDG_CONFIG_HOME/lantern-works/install_id`; deletable), and `ref` from `LANTERN_REF` (or `none`). No arguments, IPs, names or hostnames. It is batched to at most one request per day and never blocks or breaks a tool call. Details: [PRIVACY.md](https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/PRIVACY.md).

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

## License

The package code is MIT. The price and deal data it reads (the Lantern Works feeds) is CC BY 4.0: credit "Lantern Works" and link to https://thelanternworks.com. See https://thelanternworks.com/methodology/#license.

## Hosted-only price alerts

The hosted endpoint (not this stdio package) also offers poll-only `create_alert`, `check_alerts` (with `renew`) and `delete_alert`: a secret `alert_token`, a `rate_id` or gpu filter with a threshold and direction, a 30-day TTL, no webhook, email or account, and never a fire on `held_stale` or rows whose last price verification is older than 48 hours (reported as `skipped_stale` with `would_have_crossed`). `would_have_crossed` is computed for that poll only and is not stored; the next `check_alerts` re-evaluates the current feed, and a now-fresh row can fire then if the current price still crosses (that is not a delayed fire of the stale crossing). `data_age_hours` is measured from the row's own `verified_at` (or `checked_at` if `verified_at` is missing), not from `feed_updated_at`. Full contract: [docs/CONTRACT.md](../docs/CONTRACT.md#price-alerts-hosted-poll-only-f1-brain-1028).
