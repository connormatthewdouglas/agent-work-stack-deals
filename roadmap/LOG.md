# Roadmap log

Ships with commits, CI runs, URLs and versions (newest first).

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
- Decisions relayed by Bjorn under Frosty's delegation: the package name lantern-works-deals-mcp stays; the display name goes GPU-first; GPU tools come first in the order; the Stack Optimizer gets no new non-GPU lines.

## Oct 29 (late morning): hosted MCP endpoint

Decisions relayed by Bjorn under Frosty's delegation:
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
| devto | https://dev.to/lanternworks/describe-your-agent-get-the-cheapest-sourced-infra-stack-bci | pending (Frosty edits) |
| hashnode | https://lanternworks.hashnode.dev/describe-your-agent-get-the-cheapest-sourced-infra-stack | pending (Frosty edits) |

Pending, no tag yet: Glama (needs sign-in), Smithery (needs sign-in), mcp.directory (no edit path).
