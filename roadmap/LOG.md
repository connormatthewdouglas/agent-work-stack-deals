# Roadmap log

Ships with commits, CI runs, URLs and versions (newest first).

## 2026-10-29 — 0.3.24: F1 (#46) + Gauge re-audit F2–F6; T24; T12; Web Analytics check
- T24 (fcfad56a): 12 /cost/{h100,a100,l40s,rtx-4090}-{10,100,730}-hours/ pages, 1 GPU, on-demand only, held/reserved/thin/marketplace/serverless/multi-GPU excluded, variants unmixed, ties named; H100 SXM 100 h reproduces T34 ($320 tie Hyperstack/Thunder, median $399, max $474.60, 5 vendors). In sitemap (Part A is indexable per spec); Part B calculators not built.
- T12 (31e468b2, worker 30cf9d74): /stats.json watches.weekly_per_key: ISO-week calls/alerts per opt-in key, labelled by HMAC(key id, server secret), 90-day window; counters never pruned earlier.
- Web Analytics: f512c10 beacon is already the Cloudflare Web Analytics JS beacon; nothing created.
- 0.3.24 (8634ac53, worker 7a8e51a9): #46 optimizer availability ranking; F2 home counts; F4 README; F5 get_deal alias; F3 client checks re-run on 0.3.23 (LlamaIndex hosted 12/local 8, mcpo 8 routes, Continue/Roo configs parse). F6: index feed_commit = ef2f9b28 (last feed commit), correct. Live: optimize_stack A100 100 h picks Hyperstack $108 and notes out-of-stock Verda $79.65. T41 local+live 21/21; gist same.

## 2026-10-29 — 0.3.23: E5 availability ranking (#45); T41-03 tightened
- Merged Core's #45: compare_gpu_prices results carry `availability` and `in_stock`; rows marked out of stock rank after in-stock/unknown rows and are never "cheapest"; the summary names a cheaper out-of-stock row with its check time. Home spread A100 now $1.08 (Hyperstack).
- T41-03 reviewed: still excludes reserved rows from the expected minimum, and now also fails outright if the row shown first is reserved, thin or held (negative check confirmed).
- Release 211dae8a: PyPI 0.3.23, MCP Registry 0.3.23, worker 7ac09a39. Follow-up 45b28069: index `feed_commit_for_listing_counts` is the last commit of the feed blob (HEAD-independent, so CI's determinism test passes). CI green, T41 live 21/21, 315 tests.

## 2026-10-29 — 0.3.22: Gauge EOD fixes E1–E4, E6–E9
- E1 /install/ version comes from core.deals.VERSION. E2 both READMEs list 8 tools (+ report_issue_url). E3 duplicate deal-cloreai-001 retired (noindex redirect to /deals/clore-ai/; "Also not counted: 2 vendors"; gist re-synced, byte-identical). E4 "later" dropped from VAST_NOTE and CHANGELOG. E6 CloudRift tier ASCII "On-demand" via core.gpu.normalize_tier (quotes verbatim; 2026-10-29 snapshot keys aligned; test added). E7 PyPI summary lists H100, H200, A100, L40S, RTX 4090/5090. E8 CHANGELOG notes the Massed Compute pull (aa59c8d2). E9 index records a real commit sha.
- Release ef2f9b28: PyPI 0.3.22, MCP Registry 0.3.22, worker 04574125. Install tests: stdio 8 tools ok, hosted 12.

## 2026-10-29 — 0.3.21: price alerts back on at $0; #43 + #44
- Alerts (d1d0e35f): daily GitHub Actions push of HMAC-signed event batches to the worker; worker matches, signs, sends (https-only, public IP after DNS, dedupe by event_id). Proof: run 40954987898 sent=7, all 7 signatures verified; rerun sent=0.
- Merged #43 (data/gpu_throughput.json, 71 cited figures, 8 gaps) and #44 (estimate_job_cost uses cited MLPerf throughput for inference; training still returns missing).
- Release 2b396207: PyPI 0.3.21, MCP Registry 0.3.21, worker 96cbb5ca. stdio 8 tools ok, hosted 12 (8 read-only ok). T41 live 21/21. 309 tests.

## 2026-10-29 — 0.3.20: estimate_job_cost, report_issue_url, GPU Price Index; Atrium batch; T33

- aa40add2 (#38, T33): /gpu/free-credits/ now generated (scripts/free_credits_page.py), each amount quoted from the program's official page with its URL and a 2026-10-29 check date; in the sitemap; no referral links.
- #31 confirmed merged earlier (fcf27fc3). Merged #41 (T20 estimate_job_cost, dfa31ea2), #42 (T28 examples, 44378d24), #39 (T22 /embed/ badge, merge fa4dff5e with sitemap/generator regenerated).
- 00bb8422 T40: /report-price/ (from Atrium #36, not the stale branch), "Wrong price?" on every rate row, `report_issue` in gpu-prices.json and gpu-price-changes.json, `report_issue_url` on compare_gpu_prices results (public row fields only).
- d123282d T21: scripts/gpu_index.py (Gauge's reference; past days frozen by snapshot SHA-256), api/v1/gpu-price-index.json + .csv (CC BY 4.0), /gpu/index/ and /gpu/index/methodology/, validate_feed check, tests. Rebuilt by generate_seo_pages in the daily refresh.
- Release 0.3.20: https://pypi.org/project/lantern-works-deals-mcp/0.3.20/ and MCP Registry 0.3.20. Hosted worker version 0cb5d94d-d39a-4753-adbf-12152eece6fc.
- Install tests 2026-10-29: clean `uvx lantern-works-deals-mcp@0.3.20` over stdio listed 8 tools and all 8 returned ok; hosted /mcp listed 12 (8 + create_watch_key, watch_price, list_watches, delete_watch), all 8 read-only tools returned ok. /install/ now separates package (8) and hosted (12) counts, derived from server.py and hosted/src/watch_store.py; per-client checks are labelled as 0.3.19 / 7 tools.
- Reversed /compare/ URLs (runpod-vs-lambda, verda-vs-runpod, nebius-vs-coreweave) are noindex meta-refresh stubs with canonicals, kept out of the sitemap (scripts/compare_redirects.py).
- Telemetry gap: estimate_job_cost and get_price_changes aren't counted in telemetry yet.

## 2026-10-28 — 0.3.6: optimize_agent_stack + /stack/

- b07eb72: MCP tool `optimize_agent_stack` (deterministic keyword/regex parse, no LLM; cheapest cited option per component from gpu-prices, stack-pricing and priced deals; "no sourced price tracked" where there is no data; pulled / do_not_relist listings excluded; manual-only signups flagged; referral disclosure per option). New core/agent_stack.py, core/compliance.py (pulled-ID hashes shared with the generator), /stack/ page (nav + sitemap), tests/test_agent_stack.py, tests/test_stack_page.py (JS parse matches Python).
- Version 0.3.6: https://pypi.org/project/lantern-works-deals-mcp/0.3.6/ and MCP Registry io.github.connormatthewdouglas/lantern-works-deals 0.3.6.
- Clean-env check: `scripts/test_pypi_install.py --version 0.3.6 --uvx` → RESULT ok, 6 tools listed (compare_deals, compare_gpu_prices, get_deal, optimize_agent_stack, optimize_stack, search_deals).
- CI for b07eb72 (run 40743990395): docker and pypi-install failed only because they ran before PyPI served 0.3.6; follow-up 9b8fb39 run 40744636561 all green (tests, validate, docker, pypi-install, deploy, live-checks).
- Page: https://thelanternworks.com/stack/

## 2026-10-28 (Oct 28 evening): adoption measurement

`scripts/adoption_report.py` now reports installs, opt-in telemetry and repeat operators against the goal (50 installs, 10 repeat operators), with caveats. Tests: `tests/test_adoption_report.py`. No new tracking was added.

Numbers from a run at ~6:10 PM ET on Oct 28 (pypistats has data only for 2026-10-27 UTC so far):

- **PyPI, 2026-10-27:** 847 downloads without mirrors (2,144 with mirrors).
  - Minus 520 with no OS in the user agent (scanners and mirroring tools) and 174 from our own CI (pypi-install job = 2 per run, docker job = 1 per run, counted from Actions job history).
  - That leaves an estimated **153 external installs**. This is an upper bound: other people's CI, registry builds, repeat downloads and our manual test installs all still count.
- **Opt-in telemetry:** 0 real calls. The 2 test rows (version 0.0.0) are excluded.
- **Distinct opt-in installs and repeat operators:** not measurable. The collector stores no install ID (by design), and adding one would be new tracking that needs approval.
- **Cloudflare beacon:** not queried. This needs a read-only CF_API_TOKEN + CF_ACCOUNT_ID + CF_SITE_TAG; for now, use the dashboard.
- **Goal status:** installs ~153 / 50, but this is an unverified upper bound. Repeat operators: unknown / 10.

## 2026-10-28 7:09 PM ET: stack posts live + adoption baseline

- **Stack Optimizer posts:**
  - dev.to: https://dev.to/lanternworks/describe-your-agent-get-the-cheapest-sourced-infra-stack-bci
  - Hashnode: https://lanternworks.hashnode.dev/describe-your-agent-get-the-cheapest-sourced-infra-stack
  - Both return HTTP 200, and the Hashnode post's canonical points to the dev.to URL (checked 7:09 PM ET).
- **Adoption baseline** (`scripts/adoption_report.py`, run about 7:07 PM ET), against the goal of 50 installs and 10 repeat operators:
  - PyPI has **no Oct 28 data yet**; the latest day is still 2026-10-27 UTC. The 7:02 PM run got HTTP 502 from pypistats; the rerun succeeded.
  - Oct 27: 847 downloads without mirrors − 520 with no OS in the user agent − 174 from our CI = **~153 estimated external installs**. This is an upper bound, not a confirmed count.
  - Opt-in telemetry: 0 real calls (2 test rows with version 0.0.0 excluded).
  - Distinct installs and repeat operators: **not measurable**; the collector stores no IDs.
  - Cloudflare beacon: not queried (no API token).
  - Goal status: installs ~153 / 50 (upper bound); repeat operators unknown / 10.

## 2026-10-28 evening: 0.3.7, built for repeat use (no new tracking)

- **New tool `get_price_changes(since=None, gpu=None, limit=50)`.** Without `since`, it returns the latest day's moves (/api/v1/gpu-price-changes.json). With `since='YYYY-MM-DD'`, it returns every move on or after that date (/api/v1/gpu-prices/history.json). Every change cites the vendor's source_url.
- **Freshness fields:** `compare_gpu_prices` and `optimize_agent_stack` now return `data_checked_at`, `next_refresh_utc` (the daily 10:23 UTC refresh) and a neutral hint: "Prices refresh daily; call get_price_changes(since='…') to see what moved."
- **Telemetry:** no new tracking; `get_price_changes` is not counted.
- **Commits:**
  - bad6c3a: the tool, freshness fields, tests and README quickstart.
  - 8c5d1fe: install page TESTED_VERSION 0.3.7.
  - CI run 40785000424: all jobs green (tests, validate, docker, pypi-install, deploy, live-checks).
- **Releases:**
  - PyPI: https://pypi.org/project/lantern-works-deals-mcp/0.3.7/
  - MCP Registry: io.github.connormatthewdouglas/lantern-works-deals 0.3.7 (latest).
- **Clean-env check:** `scripts/test_pypi_install.py --version 0.3.7 --uvx` passed for both pip and uvx. It lists 7 tools; `get_price_changes(since='2026-10-27')` returns 2 changes:
  - Vast.ai A100 SXM, $1.3389 → $1.1378 (−15.0%).
  - Vast.ai RTX 4090, $0.5022 → $0.5175 (+3.0%).
- **Known gap:** with `since`, `data_checked_at` is null, because history rows carry no verified_at. `next_refresh_utc` is still set. Fix in the next release.

## 2026-10-28 7:20 PM ET: 0.3.8 fix

- **Fix:** with `since`, `get_price_changes` no longer returns a blank `data_checked_at`.
  - It falls back to the newest daily snapshot date and explains the source in a new `data_checked_at_basis` field.
  - Live result for `since='2026-10-27'`: `2026-10-28`, basis "date of the newest daily snapshot".
  - Test: `test_data_checked_at_never_blank_with_since`.
- **Released:**
  - PyPI: https://pypi.org/project/lantern-works-deals-mcp/0.3.8/
  - MCP Registry: 0.3.8 (latest).
- **Clean-env check:** `test_pypi_install.py --version 0.3.8 --uvx` passed for both pip and uvx. The install page now says it's tested on 0.3.8.

## 2026-10-28 8:30 PM ET — 0.3.8 / get_price_changes rollout
- Verified lantern-works-deals-mcp 0.3.8 from PyPI in a clean venv: 7 tools (adds get_price_changes). get_price_changes(since="2026-10-21") returned 2 moves (Vast.ai A100 SXM $1.3389 -> $1.1378/hr, -15%; Vast.ai RTX 4090 $0.5022 -> $0.5175/hr, +3%), each with a vendor source_url. compare_gpu_prices and optimize_agent_stack return data_checked_at, next_refresh_utc and refresh_hint.
- PR #17 (examples/gpu-price-watcher with real output + cron line; links in install_page.py, README, examples/README; SKILL.md get_price_changes note in the source + 3 copies; manifest mcp_server block listing 7 tools at 0.3.8) CI green, merged as 81c12004be25462775301a0606e6864f9a385a59. SKILL.md already said 0.3.8 with 7 tools.
- Listings set to 0.3.8 / 7 tools (commit + PR body): docker/mcp-registry#6278 (commit 9ba4fe8, pin -> 81c1200), MobinX#977 (88257e4), punkpeye#17770 (78c869c), YuzeHao2023#758 (d5e7b64), rohitg00#389 (df421aa), e2b#1861 (d0e6f81); cline#3319 issue body edited. Disclosure line kept.
- Review: CodeRabbit on #389 just acknowledged the earlier fix; no reply needed. e2b cla-bot cannot match commit author "Lantern Works <lanternworks@agentmail.to>" to a GitHub user (commits 7959e99, d0e6f81). Fixing it means re-authoring and force-pushing the fork branch; not done, needs approval.
- MCP Registry live (0.3.8 active): "GPU rental prices checked daily, with price history; stack optimizer; AI-infra deals." Names no tools, so it does not mention all 7.
- Skipped Glama, mcp.so and mcp.directory as instructed.

## Oct 29 morning: audit pass (Pax T1–T10 + Gauge data-QA), 0.3.9 + 0.3.10

Live since about 9:45 AM ET (CI run 40883999616 green: tests, validate, pypi-install, docker, deploy, live-checks).

- T1/M2: the full-month column on /gpu/ tables is now rate × 730 (flat monthly plans as listed), with the basis in the header. Root cause: vendors with no deal id shared a lookup key, so rows showed another row's total. Test: every row is checked against its own rate.
- M1: /install/ now says 7 tools. The list is read from mcp_server/server.py so it can't drift. Grep found no current page saying 5 or 6 tools, apart from the historical changelog.
- T6/M3: "By GPU model (all N rates)" now counts every rate. Models outside the main families get their own rows, and the generator asserts the sum equals the headline.
- T7/M4: removed the Ucartz Radeon 780M row; validation rejects integrated GPUs. deal-ucartz-001 now starts at the RTX 4090 dedicated plan ($798.72/mo). Gist re-synced.
- T8/M5: feed_updated_at and /stack/ "Data as of" now come from the data. New prices_verified_through field.
- T9/M6: tier_class on every rate (on-demand, community, marketplace, interruptible, reserved, dedicated-monthly). Non-on-demand rows carry a badge, the tables have an "On-demand only" filter, compare_gpu_prices takes on_demand_only, and the summary names the cheapest on-demand rate.
- T10: RTX 4090 now has 6 rates from 5 vendors. Added SaladCloud ($0.16, Lowest/Batch, interruptible) and Novita AI ($0.67 on-demand, referral). Novita spot was left out as unreconciled. Hyperstack was added (12 rates, including reservation as its own tier). Shadeform was skipped because no region was available.
- Gauge items: tier casing fixed; RunPod is now "On-demand (Secure/Community Cloud)"; Modal is kept as preemptible with the vendor quote cited; interruptible must match the tier; Ucartz A100 min_gpus=2; A100 40/80 GB is never mixed (per-size summary, "A100 80GB" filter); tier_class is in the JSON feed; README says history runs "since 2026-10-27".
- Lambda 8x rows were left as they are. Lambda quotes the price per GPU, so the CoreWeave server-price schema would break quote verification; min_gpus=8 already enforces 8-GPU estimates.
- Daily snapshot: the 10:23 UTC cron did not fire on Oct 29. I dispatched it by hand (run 40883019376), and the 2026-10-29 snapshot now exists.
- Fixed a refresh bug: a quote line shared by on-demand and spot kept a stale sibling price, which failed the live source check. Fixed and tested.
- Releases: 0.3.9 and 0.3.10 on PyPI; MCP Registry has 0.3.10.
- Decisions relayed by Bjorn under the owner's delegation: the package name lantern-works-deals-mcp stays; the display name goes GPU-first; GPU tools come first in the order; the Stack Optimizer gets no new non-GPU lines.

## Oct 29 (late morning): hosted MCP endpoint

Decisions relayed by Bjorn under the owner's delegation:
- The hosted MCP endpoint runs on a free Cloudflare Python Worker (`hosted/`, account lanternworks@agentmail.to, free plan, no paid features). URL: https://lantern-works-mcp.lantern-works.workers.dev/mcp. It runs the same `core/` + `mcp_server/server.py` tool functions as the PyPI package (stateless streamable HTTP, JSON responses).
- It stores only anonymous aggregate call counts per tool per UTC day per `?ref=` channel tag in D1 (no IPs, user agents, arguments or personal data). These are public at /stats and /stats.json.
- Channel-tagged install links (`?ref=claude-code`, `install-page`, `github-readme`, `pypi-readme`) appear on /install/ and in the READMEs.
- There is no breaking rename: the name stays `lantern-works-deals-mcp`. Display text is GPU-first, and compare_gpu_prices and get_price_changes are listed before search_deals.
- Stack Optimizer: no new non-GPU lines.
- Pulse weekly report final and Hashnode variant were regenerated from the live feeds (2026-10-29T13:33:43Z) and are ready for Bjorn to publish.

## 2026-10-29 10:20 AM ET — hosted endpoint ref tags
Hosted endpoint: https://lantern-works-mcp.lantern-works.workers.dev/mcp (Streamable HTTP). Counts per tool, day and ref: /stats.json.

| ref | Listing | Status |
| --- | --- | --- |
| install | https://thelanternworks.com/install/ | live (PR #18) |
| github-readme | https://github.com/connormatthewdouglas/agent-work-stack-deals#readme | live (existing) |
| docker | https://github.com/docker/mcp-registry/pull/6278 | PR open |
| awesome-mcp | https://github.com/punkpeye/awesome-mcp-servers/pull/17770 | PR open |
| mobinx | https://github.com/MobinX/awesome-mcp-list/pull/977 | PR open |
| yuzehao | https://github.com/YuzeHao2023/Awesome-MCP-Servers/pull/758 | PR open |
| rohitg00 | https://github.com/rohitg00/awesome-devops-mcp-servers/pull/389 | PR open |
| e2b | https://github.com/e2b-dev/awesome-ai-agents/pull/1861 | PR open |
| llmops | https://github.com/tensorchord/Awesome-LLMOps/pull/1067 | PR open (DCO blocked: first commit unsigned) |
| cline | https://github.com/cline/mcp-marketplace/issues/3319 | issue open |
| devto | https://dev.to/lanternworks/describe-your-agent-get-the-cheapest-sourced-infra-stack-bci | pending (owner edits) |
| hashnode | https://lanternworks.hashnode.dev/describe-your-agent-get-the-cheapest-sourced-infra-stack | pending (owner edits) |

Pending, no tag yet: Glama (needs sign-in), Smithery (needs sign-in), mcp.directory (no edit path).

## Oct 29 (midday): 0.3.11 Gauge re-audit release
- tier_class "reserved" documented (README, CHANGELOG) and excluded from every "cheapest" by default (compare_gpu_prices `include_reserved=false`, stack optimizer, calculator, estimate sort); Hyperstack H200 $2.79 reservation is no longer cheapest H200.
- verified_at/checked_at/evidence now use each vendor page's own fetch time (fresh refresh 13:55–13:57Z), not the refresh start.
- Modal stays interruptible with cited quote (modal.com/pricing): "Modal Functions are subject to preemption by default; while interruptions are rare, they can happen."
- Lambda 8x rows: gpu_count 8, server_hourly B200 $53.52, H100 SXM $31.92, A100 SXM $22.32, V100 $6.32 (= lambda.ai/pricing per-GPU × 8). Verda A100 40GB re-parsed. SaladCloud RTX 4090 $0.16 quote names the "Lowest" priority tier. README: snapshots since 2026-10-27.
- Shipped: PyPI + MCP Registry 0.3.11 (Registry listing carries hosted `?ref=mcp-registry` remote), hosted Worker redeployed, install page tested 0.3.11. Commits a2a4046, a17bb16; CI 40887899672 green (docker incl.).
- Pulse report regenerated from the corrected feed (TensorDock "stale" line removed); dev.to post needs 4 edits (feed timestamps, Vast RTX 4090 $0.486 / -6.1%, Vast A100 SXM $1.4383 / +26.4%, TensorDock line).

## Oct 29 (late morning): Gauge leftovers + T17 per-model JSON views
- Lane change: per-GPU pages, vendor-vs-vendor pages and /gpu/changes + RSS + docs moved to Atrium (handoff: /workspace/agent-deals-feed/HANDOFF-atrium.md; no WIP existed, so no wip branch).
- /gpu/price-comparison/ sorts reserved rows after all pay-as-you-go rows.
- All 4 Modal rows carry the preemption quote in evidence (interruption_quote/_source_url/_checked_at; validator accepts this optional triple; refresh preserves it).
- Verda A100 40GB ($1.593 / $0.7965) and 80GB ($2.226 / $1.113) confirmed in a fresh fetch; raw parsed text at /workspace/gauge/verda-a100-snippet.txt. Rows kept.
- T17: /api/v1/gpu/index.json + /api/v1/gpu/<family>.json (h100, h200, a100, l40s, l40, rtx-4090, rtx-5090, rtx-a6000, rtx-a5000, rtx-3090): cheapest split by bucket (on-demand, spot-community, serverless, monthly) and VRAM, reserved listed but never cheapest, per-row verified_at, source_url and quote, last_checked = max verified_at. ~14 KB for H100 vs ~133 KB full feed.

## Oct 29 (10:40 AM ET): release 0.3.12 + availability (Mart, release owner)
- Merged after review + green CI: #20 T3 optimizer fixes, #19 T5 neutral referral disclosure (feed schema 1.5.0; gist re-synced byte-identical), #22 T35 whole-server billing (merged main into the branch to clear a generated-page conflict; 9 GPUs on CoreWeave 8-GPU H100 for 10 h = $984.80), #23 T37 data-age flags + max_data_age_hours.
- NOT merged: #21 T4 fail-closed. The generator's own gate reports all 203 live deals registry-approved (203/203, 0 mismatches), but writing `compliance_status` into public deals.json trips the private-field guard (`compliance_status` is in PRIVATE_FIELDS / `compliance_` prefix), so the backfill can't ship as designed. Needs a decision: allow a public `compliance_status: approved` field, or switch #21 to a differently named public field.
- 0.3.12 on PyPI + MCP Registry; hosted Worker redeployed (compare_gpu_prices returns data_age_hours/excluded_too_old live); install page tested 0.3.12.
- Availability (T11/T19) from Lantern Scout v2 (QA-passed): data/gpu_availability/latest.json via scripts/import_scout_availability.py; each GPU rate gets `availability` {status, in_stock, checked_at, offer_count/stock_level/available_regions, note}. Unknown = "unknown" (never "out of stock"; e.g. RunPod Community Cloud), Vast.ai counts marked consistency-checked only, availability timestamp separate from the daily price `verified_at`, note "Stock changes within minutes ... not a guarantee". 5 of 88 rates have a signal (RunPod Secure H100 SXM/A100 SXM/RTX 4090 stock Low; Vast A100 SXM 9 offers, RTX 4090 46 offers). Import is manual from the box for now (CI can't reach Scout's output).

## Oct 29 (11:30 AM ET): release 0.3.13 (Mart)
- #24 T36 merged (main merged into branch, conflict with max_data_age_hours resolved, CI green): typed outputSchema on all 7 tools, ok/error{code,message}, mode brief|full. Hosted Worker rebuilt from main and redeployed; live tools/list shows outputSchema on 7/7, brief + full calls ok, gpu="ZZZ" returns not_found with isError true; /stats kept counting (compare_gpu_prices 6 -> 9).
- #21 T4 merged per decision (b): public `publish_status: "approved"` set only from the private registry; build and fail-closed gate use it; compliance_* stays private, guard unchanged. Backfill 203/203 registry-approved, 0 mismatches; feed schema 1.6.0; gist deals.json re-synced byte-identical (README untouched). Live: 203 deals, 88 rates.
- Availability: Gauge's 4 fixes (manual-snapshot label with per-row time, Vast count = separate later check, own note for unknown rows, CHANGELOG). Re-imported Scout v2.1 (11:11 AM ET files): 12 rows with a signal, 5 in stock; RunPod nulls use Scout's availability_note ("returned no stock status ... not known, not sold out").
- Gap: no MCP tool takes a GPU count, so "9x H100 bills 16" is only reachable through core (stack._gpu_options), verified on live data: CoreWeave $984.80, Lambda 8x $638.40, both "9 requested, 16 billed".
- 0.3.13 on PyPI + MCP Registry; uvx serverInfo 0.3.13; install page tested 0.3.13.

## 2026-10-29 ~11:45 ET — 0.3.14 (Mart)
- PR #25 (T41 release gate) merged after the Vast basis fix; local `run_t41.py --source local` 20/20.
- Gauge (C): Crusoe and Lightning AI rows pulled pending re-verification (they had been live briefly in the 102-rate feed); Vultr/Scaleway not added (403). Added Massed Compute L40S $0.97, kept OVHcloud $1.80 excl. VAT, Koyeb $1.20 (whole GPU), CloudRift, Spheron. Shadeform still held (cents pricing vs T41-01).
- Clore.ai marketplace: RTX 4090 / RTX 5090 ranked (109 / 125 listings, median + lowest + range); A100 40GB (7), H100 NVL (1), L40S (2) held as thin; no H200. Manual snapshot (API 401s CI): not auto-refreshed, auto-holds after 7 days. deal_id null (no registry entry; referral not used).
- 0.3.14 on PyPI + MCP Registry; hosted worker redeployed.

## 2026-10-29 ~12:00 ET — Clore deal + 0.3.15 (Mart)
- 99e0dbc: Clore.ai deal `deal-clore-ai` added; registry-derived publish_status approved (build: approved=204). 203 -> 204 deals, no id dropped. Clore rate rows linked. Gist deals.json synced (identical); gist README untouched.
- 70de953: 0.3.15 (Gauge re-audit): price-comparison summary excludes reserved (L40S $0.63, RTX 5090 $0.65; new T41-21, 21/21 local); Clore price_check/snapshot_at/hold_after on feed + page; Spheron relabelled marketplace/aggregator and RTX 5090 re-quoted; Massed Compute/Koyeb single-span quotes; basis = summary, evidence.quote = verbatim. Shadeform still held (Gauge: no cents conversion).
- PyPI + Registry 0.3.15; hosted worker 9d579e2e. Live: 204 deals (all approved), 101 rates, 20 vendors.

## 2026-10-29 ~12:30 ET — 0.3.16 (Mart)
- d091505: Spheron RTX 5090 marked price_check "rotating snapshot" (row specs/"Last known" rotate between fetches; no stable span); Hyperstack Spot/Reservation and SaladCloud quotes are single continuous spans; Vast/Clore quotes labelled "API fields"; tests/release_gate/README documents `--source live`.
- PyPI + Registry 0.3.16 (pypi-install needed 2 reruns for PyPI lag); hosted worker f7996149. T41 21/21 local and live. Gist deals.json identical. Live: 204 deals, 101 rates, 20 vendors.
- Note: daily refresh reported Spheron L40S "quoted context not found" in a dry run; L40S quote may need the same treatment if it rotates.

## 2026-10-29 — PR #27 merged (Mart)
- Merged Atrium's PR #27 (Pax H1-H7, #31 fixes, Pulse spec pages: per-GPU `*-rental-price`, vendor-vs-vendor `compare/*-gpu-prices`, `/gpu/changes/` + `changes.xml`, `/docs/watch-gpu-prices/`, `/lanternworks/` about page). Merge commit c8e17a3f.
- Conflict in scripts/gpu_pages.py resolved: one `_quote_html(esc, r)` (short excerpt; marketplace rows keep the "API fields:" label); rotating-snapshot verified label kept.
- H7 kept as meta-refresh; target /gpu/cheapest-h100-rental/ has a self canonical. /gpu/h100-rental-price/ now has rel=canonical to /gpu/cheapest-h100-rental/ and is out of the sitemap. Spec-page canonicals now end in "/".
- Checks: 188 pytest passed, validator 0/0, links 0 broken, T41 21/21 local and live. Gist deals.json identical. No package code changed, so no PyPI release or hosted redeploy.

## 2026-10-29 — PR #28 merged (Mart)
- Merged Atrium's PR #28 (Pax H8: plain wording for feed field names on deal pages, "Referral link"/"Direct link"/"Price not verified" badges, collapsible /deals/ categories, install code boxes with copy button, one table style; #31 rate-count note now explains marketplace medians, reserved rows and held prices). Merge commit 90270cb5.
- Canonicals (owner decision, shipped in the same deploy): each /gpu/<model>-rental-price/ is canonical and in the sitemap; each /gpu/cheapest-<model>-rental/ has rel=canonical to it and is out of the sitemap (content not merged yet). H7 meta-refresh on /compare/h100-rental-price-comparison/ now points to /gpu/h100-rental-price/. The earlier H100 canonical from #27 is reverted. Test added in tests/test_gpu.py.
- Checks: 189 pytest passed, validator 0/0, links 0 broken, T41 21/21 local and live. Gist deals.json identical. No package code changed, so no PyPI release or hosted redeploy. Shared checkout was clean, nothing stashed.

## 2026-10-29 — PR #29 merged (Mart)
- Merged Atrium's PR #29 (390px overflow fixes: tables on /install/, /gpu/price-comparison/, /stack/, /for-agents/ and the stack optimizer wrapped in .tscroll, sticky first column on wide tables, long links/code wrap, pre scrolls). Merge commit 8b57c38c. Markup/CSS only.
- Checks: 189 pytest passed, validator 0/0, links 0 broken, T41 21/21 local and live. Gist deals.json identical. Canonical setup holds: 7 /gpu/<model>-rental-price/ pages self-canonical and in the sitemap, /gpu/cheapest-*-rental/ canonical to them and out of it, H7 refresh to /gpu/h100-rental-price/. No PyPI release or hosted redeploy. Shared checkout clean, nothing stashed.

## 2026-10-29 — PR #31 merged (Mart)
- Merged Atrium's PR #31: /methodology/ page (sources, daily checks, holds, reserved not ranked) and T28 install snippets for LlamaIndex, Open WebUI, Roo Code and Continue. Merge commit fcf27fc3.
- License fix before merge (8308581f): the PR said data was CC BY 4.0 and code MIT, but the repo LICENSE is MIT for everything (pyproject license = "MIT"). The page now says code and data are MIT, matching LICENSE. Moving the data to CC BY 4.0 would need a LICENSE change and is the owner's call.
- Checks: 191 pytest passed, validator 0/0, links 0 broken, T41 21/21 local and live. Hosted /mcp tools/list returns 7 tools, matching the install page. Gist deals.json identical. Sitemap has /methodology/ and the 7 -rental-price pages, no cheapest-* pages; canonicals unchanged. No PyPI release or hosted redeploy. Shared checkout clean.

## 2026-10-29 — PR #30, PR #32 merged; release 0.3.17 (Mart)
- PR #30 (Relay, T38 price-change cursors and stable event/rate ids): merged main in (59b3aa49), CI green, merge commit 08ca3fa7.
- PR #32 (T39 rate_id on every compare row and optimizer option, deterministic quote_id receipts): retargeted to main after #30, merged main in (36ccca0d), CI green, merge commit 2cd561ec.
- Release 0.3.17 (74bef944): PyPI uploaded, MCP Registry published, hosted worker redeployed (version c2489a69). Hosted check: serverInfo 0.3.17; compare_gpu_prices rows carry rate_id; optimize_stack returns the same quote_id on two calls with different issued_at; get_price_changes returns event_id and next_cursor.
- Checks: 211 pytest passed, validator 0/0, links 0 broken, T41 21/21 local and live. Gist deals.json identical. Canonicals and sitemap unchanged.
- Main CI live-checks failed on the release push: check_gpu_sources flags Massed Compute L40S On-Demand ($0.97 quote not found on https://massedcompute.com/pricing/; the fetched page has no "L40S" text). Not changed here; needs a re-check by hand or a hold.
- Moved a stray old clone (main/pr27) out of the repo dir; it was making the tests and validator read old pages.

## 2026-10-29 — PR #33 merged; release 0.3.18 (Mart)
- PR #33 (optimizer "10 H100 gpu hours" parse): merge commit 0056af02. Release 0.3.18 (96763588): PyPI, MCP Registry, hosted worker 778ff94c; hosted check: serverInfo 0.3.18, "10 H100 gpu hours" gives quantity 10. #33 arrived after 0.3.17 had shipped, so it went out as its own version. Docker failed on PyPI lag; rerun passed.

## 2026-10-29 — Split license; release 0.3.19 (Mart)
- Owner approved CC BY 4.0 for the data (11:07 AM ET). Code stays MIT (LICENSE). New LICENSE-DATA: CC BY 4.0 legal text, attribution "Lantern Works". Every JSON feed (deals.json, api/v1/deals.json, gpu-prices.json, history.json, gpu-price-changes.json, api/v1/gpu/*.json, stack-pricing.json) carries a `license` object; schema.json allows it. /methodology/, README and mcp_server/README updated; LICENSE-DATA ships in the wheel.
- Commit 9f7d969e. PyPI 0.3.19, MCP Registry 0.3.19, hosted worker 62cadded (serverInfo 0.3.19). Gist deals.json patched, identical. T41 21/21 local and live. Live: /methodology/ shows CC BY 4.0; live deals.json, api/v1/deals.json, gpu-prices.json, history.json carry license data CC-BY-4.0.
- live-checks still fails on the Massed Compute L40S source check (unchanged).

## 2026-10-29 — Pulled Massed Compute L40S $0.97 pending re-verify (Mart)
- At Gauge's request: deleted data/gpu_pricing/massed-compute.json (Gauge's prepared diff; test count 114 -> 113). Its pricing page no longer lists L40S. Same pattern as dd32f4b4. Removed the row from today's snapshot (2026-10-29) so the change feed doesn't report it as "new". No Massed deal entry or page existed, so no label change was needed; no $0.97 remains on any page or feed.
- tests/test_quote_receipts.py::test_every_compare_row_has_the_feed_rate_id now reads the local api/v1/gpu-prices.json (patched loader), not the live site, so data pulls can deploy.
- No package code change, so no PyPI release.

## 2026-10-29 — PR #34 hosted price watches merged and deployed (Mart)
- Reviewed head 9ea1094c (CI green). Keys stored as SHA-256 hashes only; signing secret derived from WATCH_SIGNING_MASTER, never stored; only optional email beyond the webhook URL; https-only, port 443, literal private/loopback/link-local/numeric IP forms blocked; per-key 2000 calls/day, 20 watches, 100 alerts/day, 200 signups/day; own D1 DB; stats counter code unchanged (stats.json gains a `watches` aggregate); no name collision with the 7 tools; no secrets in the repo.
- Fixes on the PR: 96de7495 DNS check (DoH A+AAAA at signup and before each cron POST, fail closed, subrequest budget); b02e7672 None D1 args inlined as NULL (create_watch_key 500'd live: Pyodide None -> JS undefined); 6ab36547 cron disabled + install page says alert delivery is paused. Merge 5e4d0b81.
- Deploy: D1 lantern-works-hosted-watches 6afa052d-5eaf-4b69-9d78-edf538941b45 + schema; WATCH_SIGNING_MASTER set from a generator (copy in a 600 file outside the repo, never printed). Worker version 37907d3c-7edc-49a9-81ba-838b8a6015a3. Live: localtest.me (resolves to 127.0.0.1) rejected; create key, watch_price, list (1), delete_watch, list (0) all OK. T41 live 21/21.
- Cron CPU (forced every-minute schedule, 11 runs, 0 watches): 67-167 ms, median ~86 ms vs the free plan's 10 ms. Cron disabled (crons = []); alerts are not delivered until the cron is made cheaper or moved off the Worker.
- Cron count: the CLI can't list other Workers' crons on this account (MCP connector is for a different account); deploys with 2 and 3 schedules were accepted, now 0.

## 2026-10-29 — T30 outbound click counts (Mart)
- Beacon from f512c10 confirmed: Cloudflare Web Analytics (cookieless) counts virtual /e/out/<deal-id>/ page views; the tracker sends only that path (no cookies, storage, user agent, query or search text) and nothing is stored by us.
- Added: outbound vendor links without a deal id (GPU tables) now count as /e/out/h-<vendor-hostname>/. New scripts/click_report.py: private per-vendor daily counts from the GraphQL API (aggregate date x path), writes only outside the repo (600). Needs a read-only Analytics token (CF_API_TOKEN, CF_ACCOUNT_ID, CF_SITE_TAG), not set yet.

- 2026-10-29: /cost/ fixes G1-G5 (site only, no package release). 4f38b068 + 8610ffa9 (test escape fix; 4f38b068 CI red on one test assertion, fixed next commit). Out-of-stock rows ranked last, labelled 'out of stock when checked at <ET>', excluded from lowest/median/cheapest; 'stock is not checked here' removed. Single-in-stock-vendor variants (Thunder A100 80GB $1.09, Hyperstack A100/H100 NVLink $1.40/$2.60, Lambda A100 SXM 40GB $199/100h now sole in-stock after Verda $1.593 OOS) listed under 'Other variants (not compared)'. OVHcloud (US) L40S $1.80 marked excl. tax/VAT. RTX 4090: only 2 in-stock on-demand vendors (Novita $67, RunPod Secure $89 /100h) so no cheapest line, reason stated. New /cost/ index in sitemap, linked from /gpu/. Live hosted tools/list = 12; no '11 tools' text found in repo. T41 local+live 21/21, gist lockstep OK.

- 2026-10-29: /cost/ copy fixes H1-H2 (site only). c0cffbf4, CI green, Pages deployed. Cheapest lines + FAQ scoped to variant (e.g. Cheapest A100 SXM 80GB: Hyperstack $160.00/100h). Page-level lowest in-stock on-demand row computed from feed: A100 Thunder Compute A100 80GB (variant not stated) $10.90/$109.00/$795.70; H100 Hyperstack H100 PCIe $25.00/$250.00/$1,825.00; L40S CloudRift $6.30/$63.00/$459.90 (10/100/730h). Top line now 'Not an availability claim, except rows marked out of stock when checked' on all 12 pages. T41 local+live 21/21, gist lockstep OK.

- 2026-10-29: 0.3.25 RTX 4090 coverage depth (Bjorn task c). Added on-demand 1x RTX 4090: Nova Cloud $0.42/hr (Canada; nova-cloud.ai/gpu-models/4090; schema.org InStock on /pricing, avail checked 23:15Z) and RunC.AI $0.42/hr (multi-region; runc.ai/gpu/rtx-4090; availability unknown, no public stock signal). Held: SimplePod (inconsistent 'from'), Runcrate (aggregated lowest live rate), Beam ('from' machine; task rate serverless). Genesis Cloud $0.55 not added: page unreachable (TLS error), unverifiable. Code: records can carry region + record-level availability (Scout takes precedence). Live: /cost/rtx-4090 cheapest Nova Cloud and RunC.AI (tie) $4.20/$42.00/$306.60 (10/100/730h); compare_gpu_prices cheapest on-demand Nova Cloud $0.42. Commits 76a410a2 (release; CI red: gpu index sha), 1e766c16 (CI red: Genesis unreachable in source check), cf3c006d, 5afeaaa7 (CI green, Pages deployed). PyPI + MCP registry 0.3.25, worker 279a0f48. T41 local+live 21/21, install tests ok, gist lockstep OK. Only 2 new listed (target 3).

- 2026-10-29 Mart: 0.3.26 (Gauge re10 I1-I5): RTX 4090 /cost/ page-lowest line from feed with ties; Nova Cloud static-label availability (basis vendor_static_label, in_stock null); region in RATE_FIELDS+outputSchema; A100/H100/L40S 'not marked out of stock' wording; tie-aware compare_gpu_prices summary. Commits 1ae2192b, 6559afdb; worker 71f04011; PyPI+MCP registry 0.3.26; CI green; T41 21/21 local+live; gist lockstep.

- 2026-10-29 Mart: site-only fixes for Gauge re11 J1-J5 (no package change, no release): /install/ 0.3.23 lines labelled history with current 0.3.26; a100/h100 'only vendor not marked out of stock'; RTX 4090 page-low line gets '(not marked out of stock)'; cheapest-rtx-4090 names ties via MCP rule; '(separate check, time shown)'; unified stock explainer in gpu_pages/spec_pages/generate_seo_pages. Commits dcce3215, 85c47d0c; CI green; T41 21/21 local+live; gist lockstep.

- 2026-10-29 Mart: 0.3.27 shipped (PyPI, MCP Registry, worker 2ceecef2-8991-4f7c-a69a-4de46d51e08e). H100/A100 depth: +Jarvislabs (H100 SXM 3.49, A100 80GB 1.49, A100 40GB 0.89), Civo (H100 SXM 2.99, A100 80GB 1.79, 40GB 1.09; LON1), Oblivus (H100 PCIe 3.50, A100 PCIe 80GB 1.47; vendor stock count), E2E Networks (H100 3.99, A100 80GB 2.10, 40GB 1.98; India), CloudRift A100 SXM 80GB 1.05. Held: Massed Compute/Crusoe/Lightning (pulled), Koyeb (serverless), Northflank/Denvr/HPC-AI/Oblivus SXM+NVLink/Vultr HGX (multi-GPU only), Vultr A100 PCIe (CI 403), DeepInfra (model-deployment GPUs), GMI ('from' price), Together (HGX cluster), Paperspace (promo/commitment), Seeweb (EUR), Latitude (anomalous), CloudRift/Cudo H100 (on request). Core NOTE = stock explainer; tie_label shared. Commits 7d528498, 1e05d7a8.

- 2026-10-29 Mart: 0.3.28 shipped (PyPI, MCP Registry, worker 1072228a-ae4e-421e-8a08-a1d6e7d8d9dd) for Gauge re13. J6 Oblivus quote + stock_level from one capture (H100 PCIe 0 = out of stock when checked; A100 PCIe 80GB 10), detail notes count changes often. J7 E2E region cites https://www.e2enetworks.com/pricing.md (Delhi NCR, Chennai), INR claim dropped; Civo/Jarvislabs/Oblivus region wording verified against cited pages. J8 cheapest-a100 summary generated from feed with memory-size note. Index: A100 series already 80GB-only (INDEX_GPUS); series_vram_gb published + methodology note; history unchanged. Commits bca96591, ea828918.

- 2026-10-29 Mart: J8 fix (site-only, a6c28da7): /gpu/cheapest-a100-rental/ 80GB clause now covers every on-demand, not-out-of-stock 80GB A100 variant from the feed -> CloudRift A100 SXM 80GB at $105.00. Index regenerated (no change). CI green; no package release.

- 2026-10-29 Mart: Gauge re14 K1/K2 site part (3ca59e33, site-only): /gpu/cheapest-*-rental/ rank out-of-stock rows last per table (h100: Oblivus H100 PCIe #22, Verda H100 SXM #23 of 23; a100: Verda A100 SXM 40GB spot #27 and on-demand #28 of 28), new T41-22 guards it; /cost/a100-* adds 'Cheapest A100 80GB (any variant) among tracked providers: CloudRift A100 SXM 80GB at $10.50 / $105.00 / $766.50'. Index regenerated (no change). CI green first try; T41 22/22 local+live; gist ok. QUEUED for next batched release (package): K2 MCP part - A100 summary names cheapest 80GB row next to 'memory sizes differ'.

- 2026-10-29 0.3.29 (Mart): Scout v2.5 availability imported (64 feed rows -> 25 in_live_feed rows, snapshot 01:14:24Z); Lambda labelled authenticated vendor API; Clore shows unrented servers; unknown rows show checked_at; K2 MCP 80GB note; /cost/ other-variants OOS last. Commits 8f51d5ca, 0b46ed5e; worker 5ef44530-efbe-4fa0-a550-87699c794f0f; PyPI+Registry 0.3.29; CI green after index-lag rerun; T41 22/22 local+live; gist in lockstep.

- 2026-10-29 0.3.30+0.3.31 (Mart, Gauge re16): 8h availability staleness guard (AVAIL_MAX_AGE_H=8) in availability_for and at MCP call time, plus client-side expiry on static pages and an importer refusal; exact-variant MCP lead with the stock check time; /cost/ other-variants wording and in-stock times; T41-23 (9h fixture). 0.3.31 = tz fallback for 0.3.30 (PyPI 0.3.30 was uploaded first and is superseded). Commits ea934f4c, e0c82165; worker 93ea9274-1dff-47b9-9618-ee2e94fec912; CI green on first run; T41 23/23 local+live; gist lockstep.
