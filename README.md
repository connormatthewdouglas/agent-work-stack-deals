# Lantern Works — agent deals directory

**Lantern Works** publishes a curated directory of affiliate and public offers for AI agents (and humans directing them): compute, unblock/scrapers, templates, search, hosting, and related work-stack tools.

- **Browse:** [GitHub Pages](https://thelanternworks.com/)
- **About Lantern Works:** [lanternworks/](https://thelanternworks.com/lanternworks/)
- **Agent feed (JSON):** [thelanternworks.com/deals.json](https://thelanternworks.com/deals.json) (primary) · mirror: [raw deals.json on gist](https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json)
- **Query CLI:** `python3 query_deals.py --category unblock --max-price 20` (see [USAGE.md](USAGE.md) for the full filter contract)

Listings are live affiliate links (authorized Lantern Works referrals) or verified public/non-affiliate free tiers and vendor-published coupons. Agents `GET` the JSON feed with no auth and filter locally by `category`, `affiliate` / `free_tier`, `updated_since`, `agent_only`, `max_price`, `tags`, or `id` (default real-only). Contract: feed `query` object.

Contact: [lanternworks@agentmail.to](mailto:lanternworks@agentmail.to)

## Feed contract, validation and deploy gate

- **Schema:** [`schema.json`](https://thelanternworks.com/schema.json) (JSON Schema 2020-12). `deals.json` carries `schema_version`; prices are nullable (`null` = unknown, `0` = verified free tier), with explicit `currency`, `unit`, `billing_period`, `verified_at`, `updated_at`.
- **Stable feed:** `https://thelanternworks.com/api/v1/deals.json` is byte-identical to `/deals.json` (both written by `scripts/generate_seo_pages.py`). The gist is a byte-identical mirror.
- **Private data:** commission, payout and compliance data live only in a private file outside this repo (`LANTERN_PRIVATE_FIELDS`, default `../../lanternworks/private/deals_private_fields.json`). The generator reads it only for local sanity checks and leak detection and fails the build if any private key or commission-like text reaches public output.
- **Validation:** `pip install jsonschema && python3 scripts/validate_feed.py --gist --links` checks schema, private-leak scan, api/v1 parity, sitemap host, old-host hardcodes, gist parity and redeem URLs (403/429/timeouts warn; 404/410/DNS/persistent 5xx fail, exit 1).
- **Deploy gate:** Pages currently deploys from the `main` branch, so the gate is: **run the validator and get exit 0 before every push to main** (and update the gist first so parity holds). A GitHub Actions workflow (`validate` job, then Jekyll build + `deploy-pages` gated on it, with Pages source switched to "GitHub Actions"; CNAME keeps `thelanternworks.com`) is prepared but needs a token with `workflow` scope to push.
- **Migration test:** `python3 scripts/test_url_migration.py` checks old GitHub Pages project URLs 301 to the new domain, key pages return 200, and the feeds match.
- **Compliance gate:** when the private registry (`LANTERN_COMPLIANCE_REGISTRY`, default `../../lanternworks/private/compliance_registry.json`, owned by Wick) is present, the generator publishes only deals whose status is `approved`; others move to a private held file and come back automatically once approved. Absent registry (CI) = feed published as-is.
- **For agents:** https://thelanternworks.com/for-agents/ documents endpoints, schema and offer types.

## MCP server (read-only, local stdio)

`mcp_server/` is a working MCP server on the official Python SDK with tools `search_deals`, `compare_deals` and `get_deal`. Filter and rank logic lives in `core/` (reusable by the site and CLI) and ranks by customer value, never by affiliate status. No hosted transport.

```bash
python3 -m venv .venv && .venv/bin/pip install -r mcp_server/requirements.txt
```

```json
{ "mcpServers": { "lantern-works-deals": {
    "command": "/ABS/PATH/agent-work-stack-deals/.venv/bin/python",
    "args": ["/ABS/PATH/agent-work-stack-deals/mcp_server/server.py"] } } }
```

Details, errors, and tests: [mcp_server/README.md](mcp_server/README.md). Install guide: https://thelanternworks.com/for-agents/
