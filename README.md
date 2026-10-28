# Lantern Works — agent deals directory

**Lantern Works** publishes a curated directory of affiliate and public offers for AI agents (and humans directing them): compute and GPU rental, unblock/scrapers, email, search, hosting, and related work-stack tools. Results are ranked by customer value (price, free tier, fit), never by affiliate status.

- **Browse:** [thelanternworks.com](https://thelanternworks.com/) · [About](https://thelanternworks.com/lanternworks/)
- **Agent feed (JSON, no auth):** [thelanternworks.com/api/v1/deals.json](https://thelanternworks.com/api/v1/deals.json) (same bytes as `/deals.json`) · mirror: [gist](https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json)
- **GPU prices:** [api/v1/gpu-prices.json](https://thelanternworks.com/api/v1/gpu-prices.json) · **Stack pricing:** [api/v1/stack-pricing.json](https://thelanternworks.com/api/v1/stack-pricing.json)
- **Query CLI:** `python3 query_deals.py --category unblock --max-price 20` (filter contract: [USAGE.md](USAGE.md))

Contact: [lanternworks@agentmail.to](mailto:lanternworks@agentmail.to)

## MCP server (v0.3.4, read-only, stdio)

Free, read-only, no API key. Package [`lantern-works-deals-mcp`](https://pypi.org/project/lantern-works-deals-mcp/) on PyPI; MCP Registry name `io.github.connormatthewdouglas/lantern-works-deals`. Built on the official Python MCP SDK.

### Tools

| Tool | What it does |
|---|---|
| `search_deals` | Search the deals feed by text, `category`, `offer_type`, `max_price` and `tags`; paginated summaries (`limit` 1-25, `cursor`). |
| `compare_deals` | Compare 2-5 deals by id side by side, best customer value first. |
| `get_deal` | Return the full public record for one deal id. |
| `compare_gpu_prices` | Hourly rental prices for a GPU model (e.g. `H100`, `A100 SXM`, `RTX 4090`) across tracked providers, cheapest first, each with `source_url` and `checked_at`. "Cheapest" means cheapest among tracked providers, not the whole market. `include_history=true` adds each rate's price history and recent price changes (daily snapshots). |
| `optimize_stack` | Given monthly usage (pages scraped, proxy GB, emails, search queries, GPU hours/model), pick the cheapest tracked plan per line and total the monthly cost, with the calculation, sources and alternatives; unpublished prices are reported as `unknown`. |

### Install

```bash
uvx lantern-works-deals-mcp
```

Claude Code:

```bash
claude mcp add lantern-works-deals -- uvx lantern-works-deals-mcp
```

Cursor (`.cursor/mcp.json`) and Cline (`cline_mcp_settings.json`, via MCP Servers → Configure) use the same entry:

```json
{ "mcpServers": { "lantern-works-deals": { "command": "uvx", "args": ["lantern-works-deals-mcp"] } } }
```

Docker: `docker build -t lantern-works-deals-mcp . && docker run -i --rm lantern-works-deals-mcp` (the root [`Dockerfile`](Dockerfile) installs the pinned PyPI release and runs the stdio server). Without uv: `pip install lantern-works-deals-mcp`, then use `"command": "lantern-works-deals-mcp"`. Other clients: https://thelanternworks.com/install/ · Skill: `npx skills add connormatthewdouglas/agent-work-stack-deals`.

Telemetry is **off by default**. `LANTERN_TELEMETRY=1` opts in to an anonymous daily count of tool calls: tool name, version, day and count only. No arguments, IDs or IPs are sent or stored. See [PRIVACY.md](PRIVACY.md).

![Terminal demo: cheapest H100 for 100 hours via compare_gpu_prices](docs/demo/cheapest-h100-100h.gif)

Demo (live data, 2026-10-28): the MCP server answers "cheapest H100 for 100 hours?". It shows 100-hour totals for the cheapest, next and most expensive tracked rates, each with its source and check time, and labels referral links. Recording: [docs/demo/cheapest-h100-100h.cast](docs/demo/cheapest-h100-100h.cast) · script: [docs/demo/demo.py](docs/demo/demo.py).

Framework examples: [LangGraph](examples/langgraph-cheapest-h100/) (cheapest H100), [CrewAI](examples/crewai-cheapest-gpu/) and [OpenAI Agents SDK](examples/openai-agents-cheapest-gpu/) (cheapest GPU for a described job), [GPU price monitor](examples/gpu-price-monitor/) (price-drop alerts from the history API). All examples: [examples/](examples/). Some tool results include referral links (`affiliate: true`).

Arguments, errors, data sources and tests: [mcp_server/README.md](mcp_server/README.md).

## Feed contract, validation and deploy gate

- **Schema:** [`schema.json`](https://thelanternworks.com/schema.json) (JSON Schema 2020-12). `deals.json` carries `schema_version`; prices are nullable (`null` = unknown, `0` = free tier), with explicit `currency`, `unit`, `billing_period`, `verified_at`, `updated_at`.
- **Stable feed:** `https://thelanternworks.com/api/v1/deals.json` is byte-identical to `/deals.json` (both written by `scripts/generate_seo_pages.py`). The gist is a byte-identical mirror.
- **Private data:** commission, payout and compliance data live only in a private file outside this repo (path set by `LANTERN_PRIVATE_FIELDS`). The generator reads it only for local sanity checks and leak detection and fails the build if any private key or commission-like text reaches public output.
- **Validation:** `pip install jsonschema && python3 scripts/validate_feed.py --gist --links` checks schema, private-leak scan, api/v1 parity, sitemap host, old-host hardcodes, gist parity and redeem URLs (403/429/timeouts warn; 404/410/DNS/persistent 5xx fail, exit 1).
- **Deploy gate:** GitHub Actions runs schema validation, the test suite, a clean PyPI install check and a Docker build/stdio check; Pages deploys only after they pass, then live checks run.
- **Migration test:** `python3 scripts/test_url_migration.py` checks old GitHub Pages project URLs 301 to the new domain, key pages return 200, and the feeds match.
- **Compliance gate:** when the private registry (path set by `LANTERN_COMPLIANCE_REGISTRY`) is present, the generator publishes only deals whose status is `approved`; others move to a private held file and come back automatically once approved. Absent registry (CI) = feed published as-is.
- **For agents:** https://thelanternworks.com/for-agents/ documents endpoints, schema and offer types.
