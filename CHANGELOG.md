# Site changelog

Reverse-chronological ships for [Agent work-stack deals](https://thelanternworks.com/) (Lantern Works). Append new entries at the top. The generator renders this file to [`changelog/`](https://thelanternworks.com/changelog/).



## 0.3.46 (2026-10-30)

- F1: /install/ pairs the test date with the version actually tested ("tested 2026-10-30 (v0.3.45); current v0.3.46"), never with a later build version. Client config checks keep their own date.
- F2: Scout stock rows read "automated check, time shown" in `availability.refresh` and the page headers; "manual snapshot" stays only for Clore.ai.
- F3: one shared price formatter keeps significant digits ($3.125, not $3.12); "What moved" adds decimals until old and new differ ($0.7965 → $0.8045).
- F4: expired stock text comes from `availability_expires_at` ("last stock check 20:52Z expired at 21:07Z (this stock claim was valid 15 min)"); `max_age_hours` is each claim's real lifetime (0.25 for Verda spot).
- CI: the pypi-install uvx step retries for PyPI index lag; the worker build uses GITHUB_TOKEN for api.github.com/meta.

## 0.3.45 (2026-10-30)

- re28 stale prices: by default a GPU price older than 168 h (7 days) is never ranked and never named cheapest, in compare_gpu_prices, estimate_job_cost, optimize_agent_stack, optimize_stack, the GPU cost calculator, the stack optimizer and every generated page. Such rows are listed separately as "stale price (N days old)" (`stale_prices`, `excluded_stale`). If every candidate is stale, no current cheapest is named and the summary says so. `max_data_age_hours` replaces the 168 h default. At build time, a record not re-verified for 7 days is moved to `held_stale`.

## 0.3.44 (2026-10-30)

- T45 retrieval status: every successful tool result now carries `retrieval` (feed, `ok`/`degraded`, last_successful_retrieval_at, last_refresh_attempt_at, last_refresh_outcome, stale_cache, cache_age_s). A failed or invalid refresh serves the last good cache marked `degraded`; current-price feeds older than 1 h return `feed_unavailable` instead of stale prices. Error envelopes stay exactly `{ok, error}`.
- T46 benchmark configuration: a throughput figure is used only for jobs with the same GPU count it was measured on (`gpus_per_job`). A mismatch is reported as "configuration mismatch" with the fix; several matching configurations are listed instead of picked silently.
- re27: the same 20,000 cap applies to `optimize_agent_stack(gpu_hours)` and `estimate_job_cost(job_hours)` (also when job_hours is computed from work_units), on stdio and hosted. It caps hours (wall-clock duration per GPU), not GPU-hours: 2,501 h x 8 GPUs is valid; GPU count keeps its own limit.

## 0.3.43 (2026-10-30)

- re26: stdio and hosted check tool arguments the same way before running a tool. A missing required argument, a wrong JSON type (e.g. `limit: "abc"`) or an unknown extra argument returns the `invalid_argument` envelope with `isError: true` in both; input schemas now set `additionalProperties: false`. Unknown tool names stay protocol errors (hosted JSON-RPC -32602, stdio SDK text), documented in the README.
- re26: monthly GPU hours are capped at 20,000 in both the browser calculator and the MCP/engine (`gpu_hours must be a number 0-20000`); 1e9 is rejected.
- Benchmark data: each figure now has `quote_kind`: `table_cell` for the 45 NVIDIA spec-table rows (rebuilt from the table, not verbatim text), `literal` for the rest.

## 0.3.42 (2026-10-30)

- T44: the stdio server now sets `isError` exactly like the hosted MCP: true for the `ok:false` error envelope (invalid input, unsupported workload, upstream failure), false for success and for no-match (`ok:true`, empty list). `structuredContent` is unchanged. Requires `mcp>=1.19`. Wire-level checks: `tests/test_error_contract_wire.py` and `scripts/check_error_contract.py --installed|--hosted`.

## 0.3.41 (2026-10-30)

- T43: the benchmark data now ships inside the installed products. The wheel carries `core/assets/gpu_throughput.json` (71 cited figures, loaded package-relative), and the hosted bundle embeds the same bytes. With no throughput given, `estimate_job_cost` prices H100 SXM 80GB / resnet50 from the published MLPerf figure. A missing or corrupt asset now returns `internal_error` ("benchmark asset missing or corrupt"), not "unsupported workload". Training workloads still abstain with `not_found` "missing: throughput". CI checks the built wheel outside the checkout and the deployed MCP (`scripts/check_benchmark_asset.py`).
## 0.3.40 (2026-10-30)

- T51 measurement: the installed client's own feed fetches now send a distinct User-Agent, `lantern-works-deals-mcp/<version> (pypi-client)`. The hosted worker keeps anonymous daily counters (no IP or user agent stored, kept 90+ days) in /stats.json. See docs/MEASUREMENT.md.
## 0.3.39

- T42: the browser GPU calculator now bills whole instances using the same contract as core.gpu.estimate and the MCP. Bundled servers are rounded up to whole servers (hourly and monthly), and each row shows the requested and billed GPU counts and the number of instances. Example: CoreWeave 8x H100 for 9 GPUs x 10 h = $984.80 (16 GPUs, 2 instances). Lambda 8x H100 SXM = $638.40.
- core.gpu.estimate rows carry requested_gpus, billed_gpus and instances.
- The hosted MCP fetches the GPU feed with a 60 s cache and a per-minute CDN bypass, so new Scout data reaches it within minutes.
- A test runs the real calculator page script in node and compares the rendered rows with the Python engine for 1, 8 and 9 GPUs.

## 0.3.38

- Gauge re22 Q1: the expiry wording in llms.txt, /for-agents and docs/SCOUT-DATA.md, and the stale-claim note in the MCP and feeds, now give the actual limits: 1 h for Lambda, Verda, region and region-derived claims, and 8 h for marketplace overall claims (Vast, Clore). A claim is unknown after availability_expires_at.
- Q2: the live CI check also scans every served root JSON (deals.json, agent.json, glama.json, schema.json, site_config.json, lhm.plugin.json) for in_stock or availability fields.
- Q3: lhm.plugin.json now carries the current version and is bumped with each release. A test keeps it in sync.

## 0.3.37

- Gauge re20 fixes. P1: Scout's raw availability import (data/gpu_availability/latest.json) is no longer published on the site; the guarded data is in /api/v1.
- P3: Lambda and Verda vendor-API overall stock claims last at most 1 h, the same as a region list.
- P4: region-derived rows, out-of-stock ones included, carry regions_expires_at and turn unknown when it passes.
- P2: added a Cloudflare cron Worker (lantern-works-import-cron, every 10 min) that dispatches the gated scout-import. It is inactive until a repo-scoped Actions token is set as a Worker secret.
- T41-26 also checks the 1 h limit.

## 0.3.36

- Gauge re19 fixes. N1: derived_from_regions is carried through, and an overall claim derived from regions becomes unknown when its regions expire, both at build time and in the MCP at request time.
- N2: a RunPod overall in-stock claim needs a region confirmed in stock. RunPod's GPU-type-wide lowestPrice hint alone is now unknown.
- N3: at build time, any claim or region list that expires within 60 minutes (before the next rebuild) is written as unknown, so static HTML and JSON never hold an expired claim. A gated scout-import now also runs every 10 minutes as a backstop.
- N4: every Scout import must match a manifest sha256, whatever version the file claims; Scout's availability file is checked too. T41-26 added.

## 0.3.35

- Scout v3.2: feed_status (held_below_min_offers) and derived_from_regions carried through; a held row is never shown as available (status "unknown (held: below minimum offers)").
- A stock claim expires at the earlier of checked_at + 8 h and Scout's own availability_expires_at (Scout shortens some claims, e.g. Verda); expired claims render unknown at build time and at MCP request time, keeping availability_expires_at and feed_status for reference.
- Importer accepts Scout 3.0-3.2 and requires a matching manifest sha256 for 3.1+ (refuses otherwise).

## 0.3.34

- Scout v2.9 region lists: each availability claim can carry available_regions_detail (per region: checked_at, availability_expires_at, confirmed, confirmation), available_regions_label and regions_expires_at (the earliest region expiry, 1 h after the check).
- available_regions and available_regions_detail are blanked once regions_expires_at has passed: in the feeds at build time, in compare_gpu_prices (and hosted watch region matching) at request time, and on pages by the in-page expiry script. This is separate from the 8 h stock-claim expiry.
- Pages show "regions valid until HH:MM ET" and note that region lists refresh with each Scout cycle and may be blank between cycles.
- Release gate T41-25: fails if any JSON feed or raw-HTML page lists a region past its expiry.

## 0.3.33

- Fix: record-level stock claims (vendor-page stock counts captured with the price, e.g. Oblivus) now expire at build time after 8 h, like Scout claims. Before this fix they were only expired at MCP call time, so a static page or JSON feed could still show an old in-stock claim.
- Tests: the staleness tests no longer depend on the wall clock or on a fixed snapshot time. They pass with fresh, expired or missing stock data.

## 0.3.32

- Every stock claim (in_stock true or false) now carries availability_expires_at: checked_at + 8 h, in UTC. After that time, treat the claim as unknown. This applies to gpu-prices.json, /api/v1/gpu/<family>.json and compare_gpu_prices.
- Site: stock claims show "valid until HH:MM ET; after that treat as unknown" and carry data-av-expires. Documented in /for-agents/ and the new /llms.txt.
- /cost/ "Other variants" intro: "Listed but not ranked: no second vendor offers this exact variant in stock (form factor and memory); variants are never mixed; rows marked out of stock come last."
- Pipeline: the hourly-gated Scout import rebuilds pages and feeds even when a snapshot is refused, so expired claims flip to unknown. The daily refresh's 14:47 UTC fallback now rebuilds pages even when today's price snapshot exists.

## 0.3.31

- Fix in the 0.3.30 code: stale-availability times fall back to UTC where no time zone database is installed (for example, Windows without tzdata), instead of failing on import. Ships together with the 0.3.30 changes.

## 0.3.30

- Availability staleness guard (AVAIL_MAX_AGE_H = 8, the same limit as Scout). A stock check older than 8 h shows as "unknown (stale availability, last checked <ET time>)", with in_stock null and availability_stale true. compare_gpu_prices re-applies the check when called. Stale rows are neither ranked last nor excluded as out of stock.
- compare_gpu_prices summary lead names the exact variant (memory size), whether the rate is interruptible, and the stock check time (not the price date).
- Site: in-stock rows on /cost/ pages show "available when checked at <ET time>". The /gpu/cheapest headline shows the in-stock check time. Every stock claim expires in the reader's browser after 8 h.
- /cost/ "Other variants" intro adds "out-of-stock rows last".
- The Scout import script refuses snapshots older than 8 h.

## 0.3.29

- GPU availability now comes from Scout feed v2.5 (snapshot 2026-10-30T01:14:24Z). Only rows marked in_live_feed are imported (25 rows).
- Lambda availability is labelled "authenticated vendor API (not publicly reproducible)", the same as Verda.
- Clore availability shows "N unrented servers (one server may hold several GPUs)", never offers. Clore stays off /cost/ pages.
- Every checked availability row shows its checked_at time, including unknown (RunPod null) rows.
- compare_gpu_prices: the A100 "memory sizes differ" note names the cheapest 80GB on-demand row.
- /cost/ "Other variants" list puts out-of-stock rows last.

## 0.3.28

- Oblivus: price quote and "Available Stock" count now come from one page capture (same_capture_as_price); detail says the count changes often. H100 PCIe showed 0 at the capture, so it is out of stock when checked; A100 PCIe 80GB showed 10.
- E2E Networks region now cites the vendor's rate card (https://www.e2enetworks.com/pricing.md); the INR billing claim was dropped.
- /gpu/cheapest-<model>-rental/ names the memory size when sizes differ and adds the cheapest largest-size on-demand rate.
- GPU Price Index: series_vram_gb published; A100 series stays 80 GB only (40 GB never mixed).

## 0.3.27

- GPU coverage depth: new sourced on-demand 1x rates. H100: Jarvislabs (H100 SXM $3.49), Civo (H100 SXM $2.99), Oblivus (H100 PCIe $3.50), E2E Networks (H100 $3.99). A100: Jarvislabs (80GB $1.49, 40GB $0.89), Civo (80GB $1.79, 40GB $1.09), Oblivus (A100 PCIe 80GB $1.47), E2E Networks (80GB $2.10, 40GB $1.98), CloudRift (A100 SXM 80GB $1.05). Each row carries a region; availability is unknown unless the vendor publishes a real signal (Oblivus: "Available Stock" count, passed through as stock_level).
- Availability note: the core NOTE is now the single stock explainer used on the site.
- Ties: the "A and B (tie)" rule lives in core.deals.tie_label, shared by compare_gpu_prices and the /cost/ pages.

## 0.3.26

- RTX 4090 /cost/ pages: page-level lowest line computed from the feed, ties named ("Nova Cloud and RunC.AI (tie) RTX 4090 24GB"); stale "only 2 in stock" reason removed.
- Nova Cloud availability: static schema.org page label now reported as "vendor-labelled in stock (static page label, not a capacity check)", basis vendor_static_label, in_stock null (feed, MCP, pages).
- `region` added to compare_gpu_prices results and the outputSchema (optional).
- A100/H100/L40S /cost/ pages: "Lowest on-demand ... on this page (not marked out of stock)".
- compare_gpu_prices summary names tied cheapest vendors.

## 0.3.25 (2026-10-29)

- RTX 4090 coverage: Nova Cloud ($0.42/GPU-hr on-demand, Canada) and RunC.AI ($0.42/GPU-hr on-demand, multi-region) added from their public pricing pages, so the RTX 4090 /cost/ pages and compare_gpu_prices now have 4 in-stock on-demand vendors and a cheapest line.
- Held (not ranked): SimplePod (inconsistent "from" prices), Runcrate (aggregated lowest live rate), Beam ("from" machine price; task rate is serverless).
- Pricing records can carry their own `region` and `availability` (checked_at + source); Scout's availability snapshot still takes precedence, and unknown stays unknown, never out of stock.

## 0.3.24 (2026-10-29)
- `optimize_stack`, `optimize_agent_stack` and `estimate_job_cost` rank rows marked "out of stock when checked" after in-stock and unknown rows and say when a cheaper out-of-stock row was skipped (F1, #46). Options carry `availability` and `in_stock`.
- `get_deal("deal-cloreai-001")` returns the merged Clore.ai record (`deal-clore-ai`).
- Home page: each GPU's rate count now matches the rates behind the median, and names how many out-of-stock rows were excluded.
- /install/: the Cline, LlamaIndex, Open WebUI (hosted and mcpo), Roo Code and Continue checks were re-run on 0.3.23 (8 package tools).

## 0.3.23 (2026-10-29)
- `compare_gpu_prices` results carry `availability` and `in_stock` (E5, #45). Rows the feed marks "out of stock when checked" are kept and flagged but rank after in-stock and unknown-availability rows, so they are never called cheapest; the summary names a cheaper out-of-stock row with its check time. The home page spread follows the same rule. Unknown availability is never treated as out of stock.

## 0.3.22 (2026-10-29)
- Data QA fixes (Gauge EOD audit): Clore.ai's duplicate deal record (deal-cloreai-001) is retired, so Clore.ai is no longer listed as unpriced (its priced rows are under deal-clore-ai); the old URL redirects. CloudRift tier labels are normalized to ASCII "On-demand" (the vendor quote stays verbatim). The Vast.ai availability note no longer says "later". GPU Price Index rows record the real build commit sha. /install/ takes its version from the package. Both READMEs list all 8 tools.
- Massed Compute (L40S, announced in 0.3.14) was pulled on 2026-10-29: its pricing page no longer lists that offer (aa59c8d2).

## 0.3.21 (2026-10-29)
- `estimate_job_cost` (T20 Phase B, #44): inference jobs can now use cited published MLPerf throughput figures for H100, A100, L40S and RTX 4090 (data/gpu_throughput.json, #43: 71 cited figures, 8 documented gaps). Each figure carries its source; training jobs and uncited GPU/model pairs still return missing rather than a guess.
- Hosted endpoint: price-alert webhooks are delivered again after each daily price refresh, HMAC-signed, deduped by event_id, https-only with the private-IP check after DNS resolution.

## 0.3.20 (2026-10-29)
- New MCP tool `estimate_job_cost` (T20, #41): cost of a job from user-supplied hours or throughput, whole-instance billing, typed contract and quote_id.
- `compare_gpu_prices` results carry `report_issue_url`, a prefilled GitHub "wrong price" issue link built from public row fields only (T40). New /report-price/ page, a "Wrong price?" link on every rate row, and a `report_issue` block in gpu-prices.json and gpu-price-changes.json.
- Lantern Works GPU Price Index (T21): daily median on-demand price per GPU-hour for H100, A100 80GB, H200, L40S, RTX 4090 and RTX 5090 at /gpu/index/, with JSON and CSV under /api/v1/ (CC BY 4.0) and its methodology at /gpu/index/methodology/.
- Site: /gpu/free-credits/ (T33), /embed/ price badge (T22), integration examples (T28). The hosted endpoint has the opt-in price-watch tools from #34; alert delivery is paused.

## 0.3.19 (2026-10-29)
- Split license: code stays MIT (LICENSE); the price and deal data is CC BY 4.0, attributed to Lantern Works (new LICENSE-DATA). Every JSON feed (deals.json, gpu-prices.json, history, gpu-price-changes, api/v1/gpu/*, stack-pricing) carries a `license` field; /methodology/ and the README say the same.

## 0.3.18 (2026-10-29)
- `optimize_agent_stack` (#33): quantities start at a word boundary, so "10 H100 gpu hours" and "10x A100 hours" read 10 GPU-hours, not the digits inside the model name. A bare "5090"/"4090" is read as the RTX model.

## 0.3.17 (2026-10-29)
- T38 (#30): `get_price_changes` accepts `cursor` (oldest first, with `next_cursor`, `has_more`, `last_seq`) and `kinds`; every change carries `event_id`, `rate_id`, `seq` and `snapshot_id`. A cursor that no longer matches the published history returns `cursor_expired`. History schema is `lantern-works-gpu-price-history/2`.
- T39 (#32): every `compare_gpu_prices` row and every optimizer choice and alternative carries a stable `rate_id`. `optimize_stack` and `optimize_agent_stack` return a deterministic `quote_id` receipt with `issued_at` and `quote_basis`.
- Site: /methodology/ page and install snippets for LlamaIndex, Open WebUI, Roo Code and Continue (#31); mobile overflow fixes (#29); plain wording and canonical cleanup (#28).

## 0.3.16 (2026-10-29)
- Spheron RTX 5090: Spheron rotates this row's specs and "Last known" text between fetches, so no stable continuous span ties the GPU to $0.84/hr. The row is marked `price_check: "rotating snapshot"` (with `price_check_note`), and the quote is the single span seen at the check.
- Hyperstack Spot (H100 PCIe, A100 PCIe), Hyperstack H200 Reservation and SaladCloud RTX 4090 quotes are single continuous spans of page text (no "..." joins).
- Vendor quote column: marketplace rows (Vast.ai, Clore.ai) are labelled "API fields" rather than shown as verbatim page text.
- Release gate docs: `python3 tests/release_gate/run_t41.py --source live` tests the live site.

## 0.3.15 (2026-10-29)
- Clore.ai deal added (`deal-clore-ai`, registry-approved; referral link with inline disclosure and `plain_url`; referral terms in `docs_url`); Clore GPU rate rows link to it. Feed: 204 deals.
- Fix (regression in 0.3.14): the per-model summary on /gpu/price-comparison/ picked CloudRift reserved rows as the lowest rate (L40S $0.54, RTX 5090 $0.55). It now shows the cheapest pay-as-you-go rate, as compare_gpu_prices does (L40S $0.63, RTX 5090 $0.65). New release-gate case T41-21 checks that table.
- Rates carry `price_check` ("daily" or "manual snapshot"); manual-snapshot rows (Clore.ai) also carry `snapshot_at` and `hold_after`, and the page shows them instead of a daily verified date.
- Spheron is labelled a marketplace/aggregator listing (its page: "Live rates across 5+ providers"); its RTX 5090 quote is re-read from the current page ($0.84/hr). It is a single listed price, not a median of offers.
- Massed Compute and Koyeb evidence quotes are single continuous spans of page text.
- Methodology: `basis` is a summary of the vendor price line, not a verbatim quote; `evidence.quote` is the verbatim text. GPU tables now show the verbatim evidence quote.

## 0.3.14 (2026-10-29)
- Vast.ai `basis` now comes from the same API snapshot as offer_count / median / lowest_offer_usd (the refresh used to keep an older count and minimum in the quote); test checks they match.
- Methodology wording: `basis` is a summary of the vendor price line; `evidence.quote` is the verbatim page text.
- New L40S / RTX 5090 coverage (vetted page/API quotes, checked 2026-10-29): Massed Compute (L40S on-demand), OVHcloud (US, excl. VAT), Koyeb (serverless, whole GPU, per-second), CloudRift (on-demand plus 1- and 3-month reserved rows), Spheron (RTX 5090 row carries the page's "Last known Oct 28"). Tier labels are the vendors' own. Crusoe and Lightning AI rows were pulled pending re-verification (price could not be tied to one GPU/tier). Vultr and Scaleway are not added: their pricing pages return 403 to the source check. Shadeform resale rows are not added yet: its API quotes prices in cents ("hourly_price":552), so the published $/GPU-hr can't be matched to a verbatim dollar amount in the evidence quote (T41-01).
- Clore.ai marketplace (tier `marketplace`, like Vast.ai): RTX 4090 and RTX 5090 rows show the market at check time (lowest, range, median, listing count) from hosts' own USD listings, per day / 24 / GPU count; spot/bid excluded. Thin markets (A100 40 GB, 7 listings; H100 NVL, 1; L40S, 2) are listed as held and never ranked as cheapest. No H200 listings.

## 0.3.13 (2026-10-29)
- T36 (#24): every MCP tool now publishes a typed outputSchema and returns `ok`; failures return `error {code, message}` with a stable code (invalid_argument, invalid_cursor, not_found, feed_unavailable, feed_invalid, upstream_unavailable, internal_error). New `mode` argument: `full` (default, unchanged output) or `brief` (essential fields only). Same contract on the hosted worker.
- T4 (#21) fail-closed compliance gate: deals carry a public `publish_status: "approved"` (feed schema 1.6.0), set only from the private review registry; any build without the registry publishes only entries marked approved (possibly none). Private compliance fields are unchanged and stay out of the public feed. All 203 live deals are registry-approved, so the feed count is unchanged (203 deals, 88 GPU rates).
- GPU availability (Scout v2.3 snapshot): Verda rows labelled "authenticated vendor API (not publicly reproducible)"; a known zero is "out of stock when checked", while no signal stays "unknown"; regions shown where the API gives them.
- GPU availability: each rate in api/v1/gpu-prices.json and api/v1/gpu/<family>.json carries `availability` from a manual Lantern Scout snapshot, with its own `checked_at` separate from the daily price check. No signal shows "unknown" (with its own note, never "out of stock"); stock changes within minutes and is never a guarantee. Vast.ai offer counts come from a separate check (its own checked_at) from the price quote, so they can differ from the quote. The GPU price tables gained an Availability column.

## 0.3.12 (2026-10-29)

- `compare_gpu_prices` and `optimize_agent_stack`: every result has `data_age_hours`, `degraded` (> 48 h since verified) and `stale` (> 7 days); optional `max_data_age_hours` drops older rates and reports `excluded_too_old` (T37, #23).
- Whole-server billing: offers sold only as N-GPU servers bill whole servers, e.g. 9 GPUs on 8-GPU servers bill 16; flat-monthly multi-GPU servers bill the whole server (T35, #22).
- `optimize_agent_stack`: a quoted "$N/mo" price is no longer read as a budget, `exclude_manual_signup` also applies to the GPU line, and negated components ("no GPUs") are left out (T3, #20).
- Feed schema 1.5.0: neutral referral disclosure (`disclosure`, `plain_url`) replaces the old affiliate-link wording (T5, #19).
- New per-model JSON views at /api/v1/gpu/<model>.json with the cheapest price per tier (reserved excluded) and sources (T17).

## 0.3.11 (2026-10-29)

- New `tier_class` value `reserved`: reservation or commitment "starting from" prices, such as Hyperstack reservations. `compare_gpu_prices` leaves them out by default (`include_reserved=true` adds them back) and never calls them cheapest. Pages and the calculator sort them after pay-as-you-go rates, and the stack optimizers skip them.
- `verified_at` is now the time each vendor page was actually fetched, not the time the refresh run started.
- Lambda 8x rows now carry `gpu_count: 8` and `server_hourly_usd`: B200 $53.52, H100 SXM $31.92, A100 SXM $22.32 and V100 $6.32 per 8-GPU instance (8 × the per-GPU price on lambda.ai/pricing). The per-GPU rate is unchanged.
- Evidence quotes can elide page text with "...". The Hyperstack Spot and Reservation rows and the SaladCloud quote, which now names the priority tier ("Lowest"), are re-parsed daily.
- Hosted endpoint listed in the MCP Registry (`remotes`, streamable HTTP).
- README: price history is "daily snapshots since 2026-10-27".

## 2026-10-29: MCP server 0.3.10 (data-QA audit)

- `compare_gpu_prices` no longer treats different memory sizes as one product: when results mix sizes (A100 40GB and 80GB) the summary names the cheapest per size, and a size in the query (`A100 80GB`) filters to it.
- New `reserved` tier class for reservation and commitment prices. These are never counted as on-demand.
- Tier labels are clearer: RunPod "On-demand (Secure Cloud)" and "On-demand (Community Cloud)", consistent "On-demand" casing, and Modal "Serverless, preemptible (per second)", quoting Modal's own preemption text. Validation now fails if `interruptible` doesn't match the tier label. Price history follows the renamed labels.
- Ucartz A100: `min_gpus` is now 2, because it is sold only as a 2-GPU server.
- `tier_class` is now in the public JSON feed (api/v1/gpu-prices.json).
- New vendor Hyperstack (on-demand, spot and reservation per GPU-hour). Novita AI RTX 4090 is listed on-demand only ($0.67/hr).

## 2026-10-29: MCP server 0.3.9 (audit fixes)

- GPU comparison table: the "Full month" column now equals each row's own rate × 730 h (flat monthly plans as listed). Rows from vendors without a deal id were showing another row's monthly total.
- Every GPU rate now has a `tier_class`: on-demand, community, marketplace, interruptible (spot/preemptible) or dedicated-monthly. Pages label non-on-demand rows and have an "On-demand only" filter. `compare_gpu_prices` takes `on_demand_only=true`, and when the cheapest rate isn't on-demand the summary also names the cheapest on-demand rate.
- Removed the Ucartz Radeon 780M row (an integrated GPU, not a dedicated GPU rental). Integrated GPUs now fail validation. The Ucartz deal now starts at the cheapest dedicated-GPU plan (RTX 4090, $798.72/mo).
- `feed_updated_at` and the /stack/ "Data as of" date now come from the data: the newest price check or feed update. New `prices_verified_through` field.
- The "By GPU model" table counts every rate, so it adds up to the headline total.
- /install/ lists all 7 tools, read from the server code.
- Added SaladCloud RTX 4090 (Lowest/Batch priority, $0.16/hr, interruptible) from salad.com/pricing.
- Display name is now GPU-first ("Lantern Works GPU Prices"). The package name `lantern-works-deals-mcp` is unchanged.

## 2026-10-28 (evening): MCP server 0.3.8

- Fix: `get_price_changes(since=...)` no longer returns a blank `data_checked_at`. When the history source has no per-row check time, it falls back to the newest daily snapshot date and says so in the new `data_checked_at_basis` field.

## 2026-10-28 (evening): MCP server 0.3.7

- New read-only tool `get_price_changes(since=None, gpu=None, limit=50)`. It lists GPU price moves among tracked providers, newest first, each with old and new hourly price, change_pct, direction and the vendor source_url. Without `since` it returns the latest day's moves (/api/v1/gpu-price-changes.json); with `since='YYYY-MM-DD'` it returns every move on or after that date (/api/v1/gpu-prices/history.json).
- `compare_gpu_prices` and `optimize_agent_stack` now return `data_checked_at`, `next_refresh_utc` (the daily 10:23 UTC refresh) and a one-line hint to call `get_price_changes`.
- No new telemetry: `get_price_changes` is not counted.

## 2026-10-28 — Plan an agent stack from a description; MCP 0.3.6

- New MCP tool `optimize_agent_stack`: describe the agent you're building in plain text (plus optional fields: workload, GPU hours or model size, scraping/search/LLM needs, monthly budget). A deterministic keyword/regex parse (no LLM) maps it to components (GPU, scraping, proxies, search API, LLM API, email, hosting, database, monitoring) and returns the cheapest option with a cited price among tracked providers for each, with the math, source URL, check date and a referral disclosure where the link is a referral link. Components without a cited price say "no sourced price tracked"; nothing is estimated. Pulled listings are excluded and manual-only signups are flagged.
- New page: [/stack/](https://thelanternworks.com/stack/) (in the nav and sitemap). It uses the same parse and data, prices three example agents, and hands quantities to the [Stack Optimizer](https://thelanternworks.com/tools/stack-optimizer/) prefilled.
- lantern-works-deals-mcp 0.3.6 adds the tool; `optimize_stack` and the other tools are unchanged.

## 2026-10-28 — GPU-first homepage; GPU price changes feed; MCP 0.3.5

- The homepage now leads with GPU price comparison for agents, checked daily: the cheapest, median and highest H100, A100 and RTX 4090 rates among tracked providers, generated from the feed, plus the install command. The deals directory moved to [/deals/](https://thelanternworks.com/deals/) (nav and footer links); old `/?q=…` and `/#cat-…` links forward there, and deal pages keep their URLs.
- New: https://thelanternworks.com/api/v1/gpu-price-changes.json (what moved since yesterday's snapshot, each with the vendor source) and its RSS feed, https://thelanternworks.com/api/v1/gpu-price-changes.xml. /install/ leads with the price monitor.
- No price renders as "unknown" any more: deals without a single verified price show their plan prices, a cited GPU rate or an honest pricing-model label (`price_label` in the feed, schema 1.4.0). CI fails if any page or API output shows an unknown or blank price.
- The GPU rate count is generated from the feed everywhere (CI fails on a hardcoded count). The Stack optimizer shows GPU hours by default; scraping, proxies, email and search are behind "More needs".
- lantern-works-deals-mcp 0.3.5: `compare_gpu_prices` is registered first; docs and plugin manifests lead with GPU prices and price history.

## 2026-10-27 — Daily GPU price refresh with history; MCP 0.3.4

- GPU prices are now re-read daily from each tracked provider's public pricing page or API by a scheduled GitHub Action (robots.txt respected, polite rate). A rate changes only where its price was actually parsed, with a new `source_url`, quote and `checked_at`; unreadable rates keep their last value and are held out of rankings after 7 days without re-verification.
- Dated snapshots in `data/gpu_pricing/snapshots/`, a per-GPU/provider series at https://thelanternworks.com/api/v1/gpu-prices/history.json, and a "Recent price changes" list (among tracked providers) on [/gpu/](https://thelanternworks.com/gpu/) and each GPU page.
- lantern-works-deals-mcp 0.3.4: `compare_gpu_prices(..., include_history=true)` adds each rate's price history and recent changes.
- CI fails if any GPU rate changes without a source URL, quote and check time.

## 2026-10-27 — MCP 0.3.3: opt-in telemetry

- lantern-works-deals-mcp 0.3.3 adds an anonymous tool-call counter that is **off by default** and only runs with `LANTERN_TELEMETRY=1`. It sends the tool name, version, UTC day and count, at most once a day. No arguments, IDs or IPs. See [PRIVACY.md](https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/PRIVACY.md); aggregate counts are public at https://lantern-works-telemetry.lantern-works.workers.dev/v1/stats.

## 2026-10-27 — Check-date wording

- AlphaVPS, BounceBan, PingPing and Waalaxy: removed check dates from pricing notes that had no recorded verification. Enrich Labs: plan prices confirmed on the vendor page, so its verification date and $39 Starter price are restored; the 3-day trial remains unverified.

## 2026-10-27 — Claim batch 2, part 4

- Re-checked pricing claims on the remaining 28 deals (ShortPixel to Zapmail): verification dates set where figures were found on vendor pages; others marked "(unverified)", with unconfirmed prices set to unknown.

## 2026-10-27 — Claim batch 2, part 3

- Re-checked pricing claims on 31 deals (Moz to SEOWriting.ai): verification dates set where figures were found on vendor pages; others marked "(unverified)", with unconfirmed prices set to unknown. Basin and Uptimia free plans could not be confirmed, so both are relabelled listed_discount.

## 2026-10-27 — Claim batch 2, part 2

- Re-checked pricing claims on 31 deals (FullEnrich to Modal): verification dates set where figures were found on vendor pages; others marked "(unverified)", with unconfirmed prices set to unknown.

## 2026-10-27 — MCP 0.3.2

- lantern-works-deals-mcp 0.3.2: `optimize_stack` deal links now point at the real deal pages (`/deals/<slug>/`, e.g. `/deals/exa-001/`) instead of 404ing. The site's stack optimizer had the same bug and is fixed. Vast.ai A100 SXM 80 GB is held out of rankings until its marketplace has at least 5 verified offers again.

## 2026-10-27 — Claim batch 2, part 1

- Re-checked pricing claims on 31 deals (99stack to Folderly) against vendor pages: verification dates set where the figures were found; figures that could not be found are marked "(unverified)" and unconfirmed prices are set to unknown.

## 2026-10-27 — 9Proxy correction

- 9Proxy: removed the 5% invite-discount claim, which nothing on 9proxy.com supports. It is now a standard referral listing with the verified starting prices ($0.018/IP, $0.68/GB, checked 2026-10-27).

## 2026-10-27 — Claim batch 1

- 18 claims re-checked on vendor pages: verification dates set for Hyperbrowser (5,000 free credits, now free_tier), 9Proxy prices (source now 9proxy.com), IPGeolocation plan prices, Wonderchat, AgentMail startup eligibility and PDFCrowd API plans.
- 35 claims that could not be found on the vendor pages are now marked "(unverified)" in the feed and on the deal pages. Unconfirmed list prices (Appy.ai, Enrich Labs, meertrack, Moz, SearchApi) are set to unknown. Enrich Labs is relabelled listed_discount, and 9Proxy's 5% invite discount is marked unverified.

## 2026-10-27 — Claim audit fixes

- Re-checked flagged claims against the vendor pages. Bright Data residential: removed the unconfirmed first-deposit-match claim; the RESIGB50 50% off coupon is confirmed. Kyma API: corrected the GPT-OSS 120B example rates to $0.0473/M input and $0.2303/M output. BrowserAct: monthly and yearly plan prices confirmed (added Advanced $96/mo yearly).
- Verification labels: verified_at is now set only where a claim check is recorded. Unverified trial offers (AgentMail startup program, Fly.io, Hyperbrowser) are relabelled listed_discount. The validator now rejects verified_discount, free_tier and trial offers without verified_at.
- 9Proxy: docs link now points to 9proxy.com/pricing.

## 2026-10-27 — Clore.ai

- Added [Clore.ai](https://thelanternworks.com/deals/cloreai-001/) to the GPU hub. It is a decentralized GPU marketplace with per-hour rentals; hosts set the prices.

## 2026-10-27 — GEO Metrics

- Added [GEO Metrics](https://thelanternworks.com/deals/geo-metrics-001/) to the SEO hub. It tracks brand visibility in AI search (ChatGPT, Gemini, Perplexity and others) and offers a free trial. Plans start at €80/mo, checked today.

## 2026-10-27 — Four new deals

- Added [Hosting.com](https://thelanternworks.com/deals/hostingcom-001/), [DreamHost](https://thelanternworks.com/deals/dreamhost-001/) and [Plesk](https://thelanternworks.com/deals/plesk-001/) to the hosting hub, and [DataForSEO](https://thelanternworks.com/deals/dataforseo-001/) to the SEO hub. Prices are from the vendor pages, checked today. Hosting.com's price is not verified, and Plesk is priced in EUR.

## 2026-10-27 — MCP 0.3.1

- lantern-works-deals-mcp 0.3.1: package metadata and README list all five tools (incl. `optimize_stack`) with uvx and `claude mcp add` install steps; new `examples/` folder (three agent skills and a GPU price monitor).

## 2026-10-27 — Agent Stack Optimizer

- New [Agent Stack Optimizer](https://thelanternworks.com/tools/stack-optimizer/): enter monthly needs (pages to scrape, JS-rendered pages, residential proxy GB, transactional emails, search queries, GPU hours) and get the cheapest suitable plan per need among tracked providers. Every line shows the vendor quote, source page, check date and assumptions; unpublished prices say "unknown"; manual-signup-only vendors are flagged and can be skipped.
- New [`/api/v1/stack-pricing.json`](https://thelanternworks.com/api/v1/stack-pricing.json): cited plan prices (Firecrawl, ZenRows, ScrapingBee, Exa, SearchApi, 9Proxy, Proxyrack, SendPulse, Emailit), re-checked against the vendor pages daily.
- MCP tool `optimize_stack` shipped in [lantern-works-deals-mcp 0.3.0](https://pypi.org/project/lantern-works-deals-mcp/0.3.0/).

## 2026-10-27 — Compliance update

- Removed four listings whose affiliate terms do not allow listing on deal or coupon sites.
- ScraperAPI is now a plain referral link with no coupon wording.
- Firecrawl: removed an unverified first-purchase discount claim.
- Schema 1.3.0: new optional `signup` / `signup_note` fields. `signup: "manual_only"` marks vendors whose terms ban automated signup, so a human must sign up manually. It is set on SearchApi, IPGeolocation.io, Kyma API, Unreal Speech, RunPod and Runable, shown on their deal pages, and returned by the MCP server.

## 2026-10-26 — Trends MCP

- Added Trends MCP (live trend-data MCP server/API; free plan, paid from $16/mo billed annually) to the AI agents hub; pricing verified on trendsmcp.ai.

## 2026-10-26 — Palabra.ai

- Added Palabra.ai (real-time speech-to-speech translation API; $0.04/min, $50 free credits on sign-up) to the AI agents hub; pricing verified on palabra.ai.

## 2026-10-26 — Appy.ai

- Added Appy.ai (AI coworkers for Slack/Teams; AI Workforce $50/mo, free Starter with $100 credits) to the AI agents hub; pricing verified on appy.ai.

## 2026-10-26 — Emailit

- Added Emailit (email API/SMTP; Pro $20/mo billed yearly; +5,000 bonus monthly credits with code LANTERNWORKS) to the email APIs hub; pricing verified on emailit.com.

## 2026-10-26 — LLM Socket, Originality.ai

- Added LLM Socket (AI-search visibility for Shopify; 7-day free trial, from $9/mo) to the SEO hub; trial and pricing verified on llmsocket.co.
- Added Originality.ai (AI-content/plagiarism detection; free plan, Pro $12.95/mo billed yearly) to the SEO hub; pricing verified on originality.ai.

## 2026-10-26 — Helena by Enrich Labs

- Added Helena by Enrich Labs (AI marketing/SEO agent; 3-day free trial, Starter $39/mo) to the AI agents hub; trial and pricing verified on enrichlabs.ai.

## 2026-10-26 — meertrack

- Added meertrack (competitor monitoring API/MCP; $19 per competitor/mo) to the data API hub; pricing verified on meertrack.com.
- DocsBot AI: docs_url changed to the developer docs page.

## 2026-10-26 — DocsBot AI

- Added DocsBot AI (AI chatbot/RAG API; free plan, paid plans from $49/mo) to the AI agents hub; pricing verified on docsbot.ai.

## 2026-10-26 — Keywords Everywhere

- Added Keywords Everywhere (keyword volume, CPC and backlink data; Bronze $7/mo billed annually) to the SEO hub; pricing verified on keywordseverywhere.com.

## 2026-10-26 — EngageBay

- Added EngageBay (email marketing, CRM and helpdesk; free plan, paid from $14.99/user/mo) to the Email APIs hub; pricing verified on engagebay.com.

## 2026-10-26 — PingPing

- Added PingPing (website uptime and SSL monitoring; 14-day free trial) to the Hosting hub; USD price not yet verified (vendor lists EUR pricing).

## 2026-10-26 — KaijuVerifier

- Added KaijuVerifier (email verification API; free plan with 100 verifications/month, paid from $19/mo) to the Email APIs hub; pricing verified on kaijuverifier.com.

## 2026-10-26 — Uptimia

- Added Uptimia (uptime, SSL, API and server monitoring; free plan, paid from $9/mo) to the Hosting hub; pricing verified on uptimia.com.

## 2026-10-26 — CometAPI

- Added CometAPI (unified pay-as-you-go API for LLM, image, video and audio models, priced 20% below official rates) to the AI agents hub; pricing checked on cometapi.com.

## 2026-10-26 — Kyma API

- Added Kyma API (OpenAI-compatible, pay-per-use API for 119 models; $0.50 signup credit) to the AI agents hub; pricing checked on kymaapi.com.

## 2026-10-26 — IPGeolocation.io

- Added IPGeolocation.io (IP geolocation and threat-intel API; free tier with 1,000 credits/day, paid from $19/mo) to the Data APIs hub; pricing verified on ipgeolocation.io.

## 2026-10-26 — WebGee

- Added WebGee (NVMe cloud hosting, cloud VPS and dedicated servers; GeeSpark $4.95/mo, $1 first month) to the Hosting hub; price verified on webgee.com.

## 2026-10-26 — AlphaVPS

- Added AlphaVPS (EU VPS, dedicated and GPU servers) to the Compute and GPU compute hubs; USD price not yet verified (vendor lists EUR pricing).

## 2026-10-26 — PDF.co, BounceBan

- Added PDF.co (PDF data-extraction API, Basic $8.99/mo billed annually, verified) to the Data APIs hub and BounceBan (email verification API; price not yet verified) to the Email APIs hub.

## 2026-10-26 — Waalaxy

- Added Waalaxy (LinkedIn and email prospecting automation) to the Email APIs hub; USD price not yet verified (vendor lists EUR pricing).

## 2026-10-26 — SalesBlink

- Added SalesBlink (cold email outreach automation with MCP, Starter $29/mo) to the Email APIs hub; price verified on salesblink.io/pricing.

## 2026-10-26 — Findymail, Bento

- Added Findymail (verified B2B email finder API, Individual $99/mo) and Bento (email marketing with transactional API, $29/mo) to the Email APIs hub, with prices verified on each vendor's pricing page.

## 2026-10-26 — Marblism, Hyperping

- Added Marblism (AI employees, $44/mo billed monthly) to the AI Agents hub and Hyperping (uptime monitoring and status pages, verified free plan) to the Hosting hub, with prices verified on each vendor's pricing page.

## 2026-10-26 — Outseta

- Added Outseta (auth, billing, CRM and memberships for SaaS) to the Hosting hub at $47/mo for the Start plan billed monthly, verified on the vendor's pricing page.

## 2026-10-26 — Synthesia

- Added Synthesia (AI video with avatars) to the AI Agents hub as a verified free plan; Starter $19/mo.

## 2026-10-26 — Raycast

- Added Raycast (productivity launcher with AI and extensions) to the AI Agents hub as a verified free plan; Pro from $10/mo.

## 2026-10-26 — Woodpecker

- Added Woodpecker (cold email and LinkedIn outreach) to the Email APIs hub at $35/mo for the entry Email plan, verified on the vendor's pricing page.

## 2026-10-26 — AIclicks

- Added AIclicks (AI search visibility tracking) to the SEO hub at $59/mo for the Starter plan, verified on the vendor's pricing page.

## 2026-10-26 — Wonderchat

- Added Wonderchat (AI customer-support chatbot builder) to the AI Agents hub as a verified free plan; paid plans from $32.50/mo billed yearly.

## 2026-10-26 — Basin, Jet Admin

- Added Basin (form backend API) and Jet Admin (no-code internal tools) to the Hosting hub as verified free tiers; paid plans from $12.50/mo (Basin, billed yearly) and $16/mo (Jet Admin, billed yearly).

## 2026-10-26 — CyberPanel

- Added CyberPanel (free open-source web hosting control panel) to the Hosting hub as a verified free tier; premium add-ons from $7.99/mo.

## 2026-10-26 — Robofy, Icemail

- Added Robofy (AI chatbot and agent builder, Starter $40/mo) to the AI Agents hub and Icemail (cold-email mailboxes, $2.5/mailbox/mo) to the Email APIs hub, with prices verified on each vendor's pricing page.

## 2026-10-26 — InterServer

- Added InterServer (web hosting and VPS) to the Compute hub. Price not yet verified, so it is shown as unknown.

## 2026-10-26 — RackNerd, Hostwinds

- Added RackNerd (budget KVM VPS from $26.99/year) and Hostwinds (unmanaged Linux VPS from $4.99/mo) to the Compute hub, with prices verified on each vendor's VPS page.

## 2026-10-26 — Twin

- Added Twin (AI agent automation platform) to the AI Agents hub at $29/mo for the Plus plan, verified on the vendor's pricing page.

## 2026-10-26 — Ucartz

- Added Ucartz (GPU dedicated servers and hosting) to the Compute hub, with GPU servers from $382.72/mo verified on the vendor's GPU server page.

## 2026-10-26 — RB2B

- Added RB2B (B2B website visitor identification) to the Email APIs hub, the closest existing hub for sales/outreach tools, at $79/mo for the Starter plan per the vendor's USD pricing page.

## 2026-10-26 — Press Mage

- Added Press Mage (managed WordPress hosting) to the Hosting hub at $39/mo for the Journeyman plan, verified on the vendor's pricing page.

## 2026-10-26 — Speak AI, PiAPI

- Added Speak AI (transcription and analysis) and PiAPI (AI media generation APIs) to the AI Agents hub. Prices are from each vendor's USD pricing page. The PiAPI entry does not link to PiAPI's docs.

## 2026-10-26 — Emailable

- Added Emailable (email verification) to Email APIs; 250 free starter credits verified, plan prices left unknown.

## 2026-10-26 — SearchApi

- Added SearchApi (real-time SERP API) to Search, with verified monthly plan prices.

## 2026-10-26 — Keywords People Use, Smartlead.ai

- Added Keywords People Use (keyword research) to SEO and Smartlead.ai (cold email outreach) to Email APIs, with verified monthly prices.

## 2026-10-26 — Nightwatch, LowFruits

- Added Nightwatch (rank tracking; EUR pricing, so price unknown in USD) and LowFruits (keyword research, verified USD prices) to SEO.

## 2026-10-26 — Keyword Insights, Bouncer

- Added Keyword Insights (keyword research and clustering) to SEO, with verified monthly plan prices.
- Added Bouncer (email verification API) to Email APIs, with verified pay-as-you-go pricing.

## 2026-10-26 — Offer-type labels (schema 1.2.0)

- Every listing now carries one offer_type: verified_discount, free_tier, trial, standard_referral or credit_only_referral (conservative label where unclear). Time-limited or one-time free credits are now labelled trial.
- The validator enforces offer_type and reports verified_at coverage (null = not recorded; no dates are invented).

## 2026-10-26 — ShortPixel

- Added ShortPixel (image optimization and CDN) to Hosting. Prices left unknown until verified on the vendor site.

## 2026-10-26 — Writesonic, Whatagraph, Moz, Gumlet, Live Tennis API, Proxydocker, RealMarketAPI

- Added Writesonic (AI agents), Whatagraph (SEO/marketing reporting), Moz (search; re-added with its current link), Gumlet (hosting/CDN), Live Tennis API (new Data API hub) Proxydocker (proxies) and RealMarketAPI (Data API). Prices only where verified on the vendor site; otherwise null.
- Feed schema 1.1.0 adds the data-api category. New stable feed at /api/v1/deals.json.

## 2026-10-25 — AnotherWrapper (#106)

- Added AnotherWrapper (AI app starter kit / boilerplate) to AI agent platform deals, with verified one-time license prices.

## 2026-10-25 — PDFCrowd (#105)

- Added PDFCrowd (HTML-to-PDF and HTML-to-image APIs) to Scraping & unblock, with verified API plan prices, and to the screenshot API comparison.

## 2026-10-25 — Comparison pages

- Added 12 keyword comparison pages under `/compare/` (residential and rotating proxies, GPU rental, H100 prices, cheap VPS for agents, email verification, deliverability/warmup, transactional email, SERP APIs, screenshot APIs, AI SEO writing tools, scraping API deals) and an **AI agent tool deals** overview page. Tables quote only prices verified on vendor pages; everything else reads "unknown". Each page has pros/cons, a how-to-choose section, FAQ and breadcrumbs.
- Added published pricing notes for Folderly, EmailOctopus, Latenode, GigaGPU and Link Whisper.

## 2026-10-25 — Sprint 0: truthfulness and compliance cleanup

- Removed commission, payout and internal-note fields from the public feed and every generated page; the generator now refuses to build if they reappear. A generic affiliate disclosure remains (no rates).
- Removed agent-directed "prefer affiliate links" instructions from the feed, skill, MCP docs and pages.
- Ranking is now **customer value**: real discounts, then verified free tiers, then standard signups, A–Z by vendor. Affiliate status is not a ranking factor.
- Unknown prices are now `null` and shown as "unknown"; `price_usd: 0` is used only for verified free tiers. New `offer_type` field (discount / free_tier / standard_signup / credit_referral) and `pricing_note` with published vendor prices.
- Removed the ASocks listing.

## 2026-10-25 — 99Stack Cloud live affiliate

- Added **99Stack Cloud** hourly cloud VPS/GPU (`deal-99stack-001`) — live affiliate #104; listed on the compute hub.

## 2026-10-25 — 9Proxy live affiliate

- Added **9Proxy** residential proxies (`deal-9proxy-001`) — live affiliate #103; listed on the scraping-unblock hub.

## 2026-10-25 — ContentBot.ai live affiliate

- Added **ContentBot.ai** AI SEO/content writing (`deal-contentbot-001`) — live affiliate #102; listed on the ai-agents hub.

## 2026-10-25 — Link Whisper live affiliate

- Added **Link Whisper** WordPress internal-linking plugin (`deal-linkwhisper-001`) — live affiliate #101; listed on the ai-agents hub.

## 2026-10-25 — SEOWriting.ai live affiliate

- Added **SEOWriting.ai** AI SEO content (`deal-seowritingai-001`) — live affiliate #100; listed on the ai-agents hub.

## 2026-10-25 — Flowlu live affiliate

- Added **Flowlu** work management / CRM / automation (`deal-flowlu-001`) — live affiliate #99; listed on the ai-agents hub.

## 2026-10-25 — Windsor.ai live affiliate

- Added **Windsor.ai** marketing/analytics/SEO data connectors (`deal-windsor-001`) — live affiliate #98; listed on the hosting hub alongside analytics/monitoring tools.

## 2026-10-25 — EmailOctopus live affiliate

- Added **EmailOctopus** email marketing (`deal-emailoctopus-001`) — live affiliate #97; listed on the email-apis hub.

## 2026-10-25 — Albato live affiliate

- Added **Albato** API integration and automation (`deal-albato-001`) — live affiliate #96; listed on the ai-agents hub.

## 2026-10-25 — Usermaven live affiliate

- Added **Usermaven** product analytics and attribution (`deal-usermaven-001`) — live affiliate #95; listed on the hosting hub alongside monitoring tools.

## 2026-10-25 — xCloud live affiliate

- Added **xCloud** managed hosting and server panel (`deal-xcloud-001`) — live affiliate #94; listed on the hosting hub.

## 2026-10-25 — Sealch live affiliate

- Added **Sealch** email verification (`deal-sealch-001`) — live affiliate #93; listed on the email-apis hub.

## 2026-10-25 — MailVeri live affiliate

- Added **MailVeri** email verification API + MCP server (`deal-mailveri-001`) — live affiliate #92; listed on the email-apis hub.

## 2026-10-25 — Folderly live affiliate

- Added **Folderly** email deliverability and inbox placement testing (`deal-folderly-001`) — live affiliate #91; listed on the email-apis hub.

## 2026-10-25 — DMARCLY live affiliate

- Added **DMARCLY** DMARC/SPF/DKIM monitoring (`deal-dmarcly-001`) — live affiliate #90; listed on the email-apis hub.

## 2026-10-25 — Proxyrack live affiliate

- Added **Proxyrack** residential/datacenter/mobile proxies and scraper API (`deal-proxyrack-001`) — live affiliate #89; listed on the scraping-unblock hub.

## 2026-10-25 — Premium Inboxes live affiliate

- Added **Premium Inboxes** cold email inbox infrastructure (`deal-premiuminboxes-001`) — live affiliate #88; listed on the email-apis hub.

## 2026-10-25 — SmartReach live affiliate

- Added **SmartReach** cold email and sales engagement (`deal-smartreach-001`) — live affiliate #87; listed on the email-apis hub.

## 2026-10-25 — Klenty live affiliate

- Added **Klenty** multichannel sales engagement / cold email (`deal-klenty-001`) — live affiliate #86; listed on the email-apis hub.

## 2026-10-25 — mailfloss live affiliate

- Added **mailfloss** automated email verification (`deal-mailfloss-001`) — live affiliate #85; listed on the email-apis hub.

## 2026-10-25 — InboxKit live affiliate

- Added **InboxKit** Google/Microsoft mailbox infrastructure for cold email (`deal-inboxkit-001`) — live affiliate #84; listed on the email-apis hub.

## 2026-10-25 — Postiz live affiliate

- Added **Postiz** open-source social media scheduler with API/MCP (`deal-postiz-001`) — live affiliate #83; listed on the ai-agents hub.

## 2026-10-25 — UpLead live affiliate

- Added **UpLead** B2B contact data and email finder (`deal-uplead-001`) — live affiliate #82; listed on the email-apis hub.

## 2026-10-25 — MailReach live affiliate

- Added **MailReach** email warmup and spam testing (`deal-mailreach-001`) — live affiliate #81; listed on the email-apis hub.

## 2026-10-25 — MailerLite live affiliate

- Added **MailerLite** email marketing with API/MCP sending (`deal-mailerlite-001`) — live affiliate #80; listed on the email-apis hub.

## 2026-10-25 — Thunder Compute live referral

- Added **Thunder Compute** on-demand GPU cloud (`deal-thundercompute-001`) — live affiliate #79; listed on the compute hub.

## 2026-10-25 — SoftShellWeb live affiliate

- Added **SoftShellWeb** KVM VPS / shared / reseller hosting (`deal-softshellweb-001`) — live affiliate #78; listed on the hosting hub.

## 2026-10-25 — Telemetry Tracker live affiliate

- Added **Telemetry Tracker** open-source error tracking / Sentry alternative (`deal-telemetry-tracker-001`) — live affiliate #76; listed on the hosting hub.

## 2026-10-24 — Heyo Email live affiliate

- Added **Heyo Email** cold-email sending platform (`deal-heyo-001`) — live affiliate #75; listed on the email-apis hub.

## 2026-10-24 — MailKite live affiliate

- Added **MailKite** transactional email API with MCP agent inboxes (`deal-mailkite-001`) — live affiliate #74; listed on the email-apis hub.

## 2026-10-24 — SendPulse live affiliate

- Added **SendPulse** SMTP/transactional email and marketing automation (`deal-sendpulse-001`) — live affiliate #73; listed on the email-apis hub.

## 2026-10-24 — WaveSpeedAI live affiliate

- Added **WaveSpeedAI** generative media inference API (`deal-wavespeed-001`) — live affiliate #72; listed on the compute hub.

## 2026-10-24 — GigaGPU live affiliate

- Added **GigaGPU** dedicated bare-metal GPU servers (`deal-gigagpu-001`) — live affiliate #71; listed on the compute hub.

## 2026-10-24 — Uptimewolf live affiliate

- Added **Uptimewolf** uptime/cron/server monitoring with status pages (`deal-uptimewolf-001`) — live affiliate #70; listed on the hosting hub alongside Better Stack.

## 2026-10-24 — Trillet AI live affiliate

- Added **Trillet AI** white-label voice AI agent platform (`deal-trillet-001`) — live affiliate #69; listed on the ai-agents hub.

## 2026-10-24 — BrowserAct live affiliate

- Added **BrowserAct** no-code browser agents for scraping/automation (`deal-browseract-001`) — live affiliate #68; listed on the scraping-unblock hub.

## 2026-10-24 — GetSales live affiliate

- Added **GetSales** multichannel LinkedIn + email outreach automation (`deal-getsales-001`) — live affiliate #67; listed on the email-apis hub.

## 2026-10-24 — Botdog live affiliate

- Added **Botdog** AI LinkedIn outreach automation (`deal-botdog-001`) — live affiliate #66; listed on the email-apis hub alongside the outreach tools.

## 2026-10-24 — Droxy live affiliate

- Added **Droxy** AI chatbot / agent builder (`deal-droxy-001`) — live affiliate #65; listed on the ai-agents hub.

## 2026-10-24 — Millis AI live affiliate

- Added **Millis AI** low-latency voice agents API (`deal-millis-001`) — live affiliate #64; listed on the ai-agents hub.

## 2026-10-24 — ReachInbox live affiliate

- Added **ReachInbox** AI cold-email automation platform (`deal-reachinbox-001`) — live affiliate #63; listed on the email-apis hub.

## 2026-10-24 — Zapmail live affiliate

- Added **Zapmail** Google & Microsoft inbox infrastructure for cold email (`deal-zapmail-001`) — live affiliate #62; listed on the email-apis hub.

## 2026-10-24 — Salesforge (+ Mailforge) live affiliate

- Added **Salesforge** cold-email + AI SDR suite (`deal-salesforge-001`) — live affiliate #61; listed on the email-apis hub.

## 2026-10-24 — FullEnrich live affiliate

- Added **FullEnrich** waterfall contact enrichment / email + phone finder (`deal-fullenrich-001`) — live affiliate #60; listed on the email-apis hub.

## 2026-10-24 — LeadMagic live affiliate

- Added **LeadMagic** B2B enrichment / email finder API (`deal-leadmagic-001`) — live affiliate #59; listed on the email-apis hub.

## 2026-10-24 — Prospeo live affiliate

- Added **Prospeo** email finder / B2B enrichment API (`deal-prospeo-001`) — live affiliate #58; listed on the email-apis hub.

## 2026-10-24 — Unreal Speech live affiliate

- Added **Unreal Speech** text-to-speech API (`deal-unrealspeech-001`) — live affiliate #57; listed on the ai-agents hub alongside voice-agent platforms.

## 2026-10-24 — BuildShip live affiliate

- Added **BuildShip** AI workflow / backend builder (`deal-buildship-001`) — live affiliate #56; listed on the ai-agents hub.

## 2026-10-24 — SiliconFlow China live affiliate

- Added **SiliconFlow China** (siliconflow.cn, Chinese-language site; not siliconflow.com) LLM inference API (`deal-siliconflow-cn-001`) — live affiliate #55; listed on the compute hub.

## 2026-10-24 — Bolna live affiliate

- Added **Bolna** voice AI agents for Indian languages (`deal-bolna-001`) — live affiliate #54; listed on the ai-agents hub.

## 2026-10-24 — Exa live affiliate

- Added **Exa** web search API for AI agents (`deal-exa-001`) — live affiliate #53; listed on the search hub.

## 2026-10-24 — Latenode live affiliate

- Added **Latenode** AI workflow automation / agent platform (`deal-latenode-001`) — live affiliate #52; listed on the ai-agents hub.

## 2026-10-24 — Relay (burner mailboxes) live affiliate

- Added **Relay (burner mailboxes)** cold-outreach mailbox provider at userelay.app (`deal-relay-mailboxes-001`) — live affiliate #51; listed on the email-apis hub. Not affiliated with relay.app.

## 2026-10-24 — Botpress live affiliate; Vapi terms

- Added **Botpress** AI agent builder (`deal-botpress-001`) — live affiliate #50; listed on the ai-agents hub.
- Updated **Vapi** listing notes.

## 2026-10-24 — Vapi live affiliate

- Added **Vapi** voice AI agents API (`deal-vapi-001`) — live affiliate #49; listed on the ai-agents hub.

## 2026-10-24 — Quickchat AI live affiliate

- Added **Quickchat AI** no-code AI agent / chatbot builder (`deal-quickchat-001`) — live affiliate #48; listed on the ai-agents hub.

## 2026-10-23 — AI agents hub + Chipp live affiliate

- New **AI agent platform deals** hub at [`categories/ai-agents/`](https://thelanternworks.com/categories/ai-agents/) for agent builders, chatbot platforms, and general AI agents; **Runable** moved there from templates.
- Added **Chipp** no-code AI agent builder (`deal-chipp-001`) — live affiliate #46; listed on the ai-agents hub.

## 2026-10-23 — Runable live affiliate

- Added **Runable** general-purpose AI agent platform (`deal-runable-001`) — live affiliate #45; listed on the templates hub.

## 2026-10-23 — Undetectable.io live affiliate

- Added **Undetectable.io** antidetect browser with MCP/AI hooks for scraping/unblock (`deal-undetectable-001`) — live affiliate #44; listed on the unblock hubs.

## 2026-10-23 — MoreLogin live affiliate

- Added **MoreLogin** antidetect browser profiles for scraping/unblock (`deal-morelogin-001`) — live affiliate #43; listed on the unblock hubs.

## 2026-10-23 — Incogniton live affiliate

- Added **Incogniton** antidetect browser profiles for scraping/unblock (`deal-incogniton-001`) — live affiliate #42; listed on the unblock hubs.

## 2026-10-23 — AdsPower live affiliate

- Added **AdsPower** antidetect browser profiles for scraping/unblock (`deal-adspower-001`) — live affiliate #41; listed on the unblock hubs.

## 2026-10-23 — EmailListVerify live affiliate

- Added **EmailListVerify** email list verification API (`deal-emaillistverify-001`) — live affiliate #40; listed on the email-apis hub.

## 2026-10-23 — GoLogin live affiliate

- Added **GoLogin** antidetect browser profiles for scraping/unblock (`deal-gologin-001`) — live affiliate #39; listed on the unblock and scraping/unblock hubs.

## 2026-10-23 — Nstbrowser live affiliate

- Added **Nstbrowser** antidetect browser for scraping/unblock (`deal-nstbrowser-001`) — live affiliate #38; listed on the unblock and scraping/unblock hubs.

## 2026-10-23 — Seobility live affiliate

- Added **Seobility** SEO audit & rank tracking (`deal-seobility-001`) — live affiliate #37; new **seo** category + `categories/seo/` hub. Homepage now also renders the proxies section.

## 2026-10-23 — Shifter live affiliate

- Added **Shifter** residential proxies & scraping (`deal-shifter-001`) — live affiliate #36; listed on proxies and scraping/unblock hubs.

## 2026-10-23 — Comparison / gotcha notes on deal pages

- Every `deals/*/index.html` page now has a **Before you redeem** box.
- Durable curated notes live in [`data/deal_gotchas.json`](../data/deal_gotchas.json); `scripts/generate_seo_pages.py` merges them with auto-rules from public feed fields.
- High-value quirks covered: ScraperAPI trial/free trap, Postmark & Firecrawl free twins.

## 2026-10-23 — Freshness badges + affiliates-first ranking

- Deal pages and listing cards show **Updated** dates from feed `updated_at` when present (no invented dates); **New** / **Updated** badges for recent timestamps (~7–14 days).
- Default feed / homepage / hub order set (superseded 2026-10-25 by customer-value ranking).
- This changelog page added to the sitemap and linked from home + Lantern Works.

## 2026-10-23 — Agent-queryable feed filters

- Documented machine-readable filters on the feed `query` object and homepage [#how-agents-query](https://thelanternworks.com/#how-agents-query).
- CLI / skill / MCP sketch: `category`, `affiliate`, `free_tier` / `non_affiliate`, `updated_since`, tags, `agent_only`, `max_price`, real-only default.

## 2026-10-23 — Best-for-X stack guides

- [Best agent scrape & unblock stack](https://thelanternworks.com/guides/agent-scrape-unblock/)
- [Cheap GPU week for agents](https://thelanternworks.com/guides/cheap-gpu-week/)
- [Best agent email & outreach stack](https://thelanternworks.com/guides/agent-email-outreach/)

## 2026-10-23 — ClearBounce affiliate

- Live deal: [ClearBounce — email verification API](https://thelanternworks.com/deals/clearbounce-001/)

## 2026-10-23 — SEO polish (OG / Twitter / JSON-LD)

- Open Graph + Twitter cards on generated pages; homepage Organization / WebSite / CollectionPage JSON-LD.

## 2026-10-23 — Snov.io affiliate

- Live deal: [Snov.io — email finder, verifier & outreach](https://thelanternworks.com/deals/snovio-001/)
- First email-category affiliate on the main board.

## 2026-10-23 — IPFoxy affiliate

- Live deal: [IPFoxy](https://thelanternworks.com/deals/ipfoxy-001/)

## 2026-10-23 — GloryCloud affiliate

- Live deal: [GloryCloud (GoProxy)](https://thelanternworks.com/deals/glorycloud-001/)
