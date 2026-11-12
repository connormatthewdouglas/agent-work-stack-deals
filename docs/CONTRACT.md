# Feed contract, MCP tools and API detail

This page is the contract and API detail that previously lived in the [README](../README.md). The README keeps the quick start.

### Tools

Tool counts: **9** in the local package (stdio, below); **13** on the hosted endpoint (the same 9 plus `create_watch_key`, `watch_price`, `list_watches`, `delete_watch`).

| Tool | What it does |
|---|---|
| `compare_gpu_prices` | Hourly rental prices for a GPU model (e.g. `H100`, `A100 SXM`, `RTX 4090`) across tracked providers, cheapest first, each with `source_url` and `checked_at`. "Cheapest" means cheapest among tracked providers, not the whole market. `include_history=true` adds each rate's price history and recent price changes (daily snapshots since 2026-10-27). Each rate has `tier_class` (on-demand, community, marketplace, interruptible, reserved, dedicated-monthly; also in the public JSON feed); `on_demand_only=true` keeps on-demand rates only. `reserved` = reservation/commitment "starting from" prices (e.g. Hyperstack reservations): they need a term contract, so they are left out of results and never called "cheapest" unless you pass `include_reserved=true` (even then they sort after pay-as-you-go rates). Marketplace median rows (`price_status=marketplace`) also carry `marketplace_query` (the literal filter used for the median, plus structured filters; null when unknown) and `composition_flag` (`composition`, `price`, `mixed`, `unknown`, or null) from successive median, minimum and listing count; a composition, mixed or unknown flag is not a price move. Each result carries `report_issue_url`, a prefilled "wrong price" issue link. Returns `mode="brief"` by default since 0.5.0; pass `mode="full"` for every field. |
| `get_price_changes` | GPU price moves among tracked providers, newest first: old and new hourly price, `change_pct`, direction and the vendor `source_url`. `since` (`YYYY-MM-DD`) returns every move on or after that date; without it, the latest day's moves. Optional `gpu` and `kinds` filters. Each change has a stable `event_id` (dedupe key) and `rate_id`; pass `cursor=next_cursor` to page every change after it, oldest first, until `has_more` is false. Marketplace median moves also have `composition_flag` (`composition`, `price`, `mixed`, `unknown`, or null) from successive median, minimum and listing count; composition, mixed and unknown are not counted as price drops or rises and are not titled as such. |
| `optimize_stack` | Given monthly usage (pages scraped, proxy GB, emails, search queries, GPU hours/model), pick the cheapest tracked plan per line and total the monthly cost, with the calculation, sources and alternatives; unpublished prices are reported as `unknown`. |
| `optimize_agent_stack` | Describe the agent in plain text (e.g. "scrapes 20k JS pages via 5 GB proxies, 3k searches, summarizes with an LLM, budget $300/mo"); a deterministic keyword parse (no LLM) maps it to components and returns the cheapest cited option per component with the math, `source_url`, `verified_at` and a referral disclosure where applicable. Components with no cited price say "no sourced price tracked". |
| `estimate_job_cost` | Cost of one GPU job (not per hour) among tracked providers, cheapest first. You give `job_hours`, or `work_units` plus your own `throughput_units_per_gpu_hour`; for inference `workload`s with no throughput given, a cited closed-division MLPerf Inference figure for the exact GPU is used (`throughput_basis="published_benchmark"`, with source and caveats), and training returns "missing: throughput". Whole-instance billing; reserved and held rates never ranked; spot only with `allow_interruptible`. Returns per-rate `rate_id`, `source_url`, `verified_at`, assumptions, `missing_costs` and a `quote_id`. |
| `rebuild_quote` | Reopen a past quote: pass the `receipt` from `optimize_stack`, `optimize_agent_stack` or `estimate_job_cost`. Returns `receipt_intact`, `reproduced` (`true` only when each line's arithmetic recomputes AND its `rate_id` and price match the pinned feed revision or that date's published daily snapshot; `"arithmetic_only"` with `provenance_verified: false` when that can't be confirmed), per-line `provenance`, and revalidation against today's feed (`unchanged`, `price_changed`, `evidence_changed`, `held_today`, `not_in_feed_today`). Nothing is re-ranked; no server key. |
| `search_deals` | Search the deals feed by text, `category`, `offer_type`, `max_price` and `tags`; paginated summaries (`limit` 1-25, `cursor`). |
| `compare_deals` | Compare 2-5 deals by id side by side, best customer value first. |
| `get_deal` | Return the full public record for one deal id. |

Note on `rebuild_quote`: a receipt issued from an earlier feed generation on a day whose daily snapshot was later re-cut can come back `reproduced: "arithmetic_only"` (`price_mismatch`) even though its price was genuine at the time. That is a safe false negative; it never verifies a forged price.

### Hosted endpoint (no install)

Streamable HTTP, same read-only tools: `https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=readme`
(`claude mcp add --transport http lantern-works-deals https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=readme`). Free Cloudflare Worker; it stores anonymous daily call counts per tool (no arguments) and, for distinct-caller counts, a daily-salted SHA-256 hash of IP + user agent (raw IP and user agent are never stored; the day's salt is deleted when the UTC day ends; hashes are kept 120 days). Counts are public at https://lantern-works-mcp.lantern-works.workers.dev/stats. See [PRIVACY.md](../PRIVACY.md) and [/privacy/](https://thelanternworks.com/privacy/). `?ref=` only tags which link was used.

## Alert delivery (hosted watches)

- At-least-once. An alert counts as delivered on any 2xx. Dedupe on `x-lantern-event-id` + `x-lantern-watch-id`.
- 408, 425, 429, 5xx and network errors retry with backoff: 15 min, then x4 each time, capped at 24 h. `Retry-After` is honoured up to 24 h. At most 6 attempts, and none after 72 h from the first; then the alert is `expired`.
- Any other status (3xx are not followed, 4xx) is `rejected` and not retried.
- Fair continuation: never-tried alerts go first, then the least recently tried; at most 10 POSTs per receiver host per run, and a host that fails is skipped for the rest of that run. Work left over is `backlog`, sent on the next push.
- `stats.delivery` shows `last_push_at`, `last_success_at`, `pending_retries` and the last outcome counts. The push job fails when any delivery fails or D1 cannot record results.
- Local alternative: `examples/gpu-price-watcher/watch_prices.py --state FILE` pages every event after a saved cursor and saves it atomically after each page, so a crash or missed day re-reads and never skips.

## Eligibility (region, memory, tier, stock)

`compare_gpu_prices`, `estimate_job_cost`, hosted price watches and the calculator share one contract (`core/eligibility.py`). Each result carries `eligibility {eligible, applied, unmet, unknown}`.

- `gpu="A100 80GB"` (or `vram_gb=80`) never matches a 40GB row; `tiers=["on-demand"]` never matches spot.
- `region="US"` (country/area: US, CA, EU, APAC, ...) matches every zone in it: 'US-MD-1 (United States)', 'us-east-1'. A zone (`region="us-ne-1"`) matches exactly, any case, ignoring the '(...)' suffix. Published rows carry `available_regions_normalized` ({label, zone, country, group}) beside the original labels. The summary starts with what the region filter found, and names a cheapest "regardless of region" when no confirmed row leads.
- GPU names fold form-factor generations: 'A100 SXM4' = 'A100 SXM', 'H100 PCIe5' = 'H100 PCIe'. A form no tracked rate has is not_found in compare, estimate and watches.
- `region="US"` drops rows whose unexpired published regions exclude it. Rows with no region evidence are kept, marked unresolved and ranked last; a watch never alerts on them.
- Unknown stock is not confirmed availability. A row confirmed sold out never alerts.

## Stale prices

By default no tool or page ranks a GPU price older than 168 hours (7 days) or names it cheapest. Such rows are listed separately as "stale price (N days old)" in `stale_prices`. If every matching price is stale, no current cheapest is named and the summary says so. Pass `max_data_age_hours` to set a different limit (for example 1000 to rank older quotes anyway; confirm them on the vendor page).

## Published GPU throughput data (T20 Phase B, data only)

`data/gpu_throughput.json` (schema `lantern-works-gpu-throughput/1`) holds **published** throughput and peak-spec figures for H100 (SXM, PCIe 80GB, NVL), A100 (40/80GB, SXM vs PCIe), L40S and RTX 4090, from NVIDIA spec sheets and MLPerf Inference results (closed division, Offline). Each figure carries `gpu`, `variant`, `workload`, `metric`, `unit`, `value`, `conditions` (precision, sparsity, scenario, batch, `gpu_count`, `per_gpu`), `source_url`, `source_title`, `publication_date`, `retrieved_at` (UTC) and a verbatim `quote`.

Rules: values are copied from the quote, never estimated or derived. Multi-GPU MLPerf results are whole-system numbers (`per_gpu: false`) and are not divided per GPU. Vendor TFLOPS are theoretical peaks, not job throughput. Missing combinations are listed in `gaps` with `gap: true` and a reason. `tests/test_gpu_throughput.py` enforces this. `estimate_job_cost` reads it (since 0.3.21): for inference workloads with no user throughput it uses a directly applicable cited figure and reports `throughput_basis="published_benchmark"` with the source; training and uncovered GPU/model pairs still need a user-supplied throughput.

## Feed contract, validation and deploy gate

- **Schema:** [`schema.json`](https://thelanternworks.com/schema.json) (JSON Schema 2020-12). `deals.json` carries `schema_version`; prices are nullable (`null` = unknown, `0` = free tier), with explicit `currency`, `unit`, `billing_period`, `verified_at`, `updated_at`.
- **Stable feed:** `https://thelanternworks.com/api/v1/deals.json` is byte-identical to `/deals.json` (both written by `scripts/generate_seo_pages.py`). The gist is a byte-identical mirror.
- **Private data:** commission, payout and compliance data live only in a private file outside this repo (path set by `LANTERN_PRIVATE_FIELDS`). The generator reads it only for local sanity checks and leak detection and fails the build if any private key or commission-like text reaches public output.
- **Validation:** `pip install jsonschema && python3 scripts/validate_feed.py --gist --links` checks schema, private-leak scan, api/v1 parity, sitemap host, old-host hardcodes, gist parity and redeem URLs (403/429/timeouts warn; 404/410/DNS/persistent 5xx fail, exit 1).
- **Deploy gate:** GitHub Actions runs schema validation, the test suite, a clean PyPI install check and a Docker build/stdio check; Pages deploys only after they pass, then live checks run.
- **Migration test:** `python3 scripts/test_url_migration.py` checks old GitHub Pages project URLs 301 to the new domain, key pages return 200, and the feeds match.
- **Compliance gate:** when the private registry (path set by `LANTERN_COMPLIANCE_REGISTRY`) is present, the generator publishes only deals whose status is `approved`; others move to a private held file and come back automatically once approved. Absent registry (CI) = feed published as-is.
- **For agents:** https://thelanternworks.com/for-agents/?ref=readme documents endpoints, schema and offer types.

