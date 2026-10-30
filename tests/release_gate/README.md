# T41: pricing-decision release gate (Lantern Works)

## How to run

- Live site (what agents see now): `python3 tests/release_gate/run_t41.py --source live`. It fetches the public feeds and pages from thelanternworks.com and exits 1 on any failing case. Run it after each deploy.
- Local build (CI): `python3 tests/release_gate/run_t41.py --source local`, after `python3 scripts/generate_seo_pages.py`.

There are 21 cases in `cases.json`. Each case is a question an agent would ask, such as "cheapest H100" or "cheapest on-demand L40S". Each one has an expected property taken from the repo's own rules: `core/gpu.py`, `core/deals.py`, `core/stack.py`, and the feed methodology. No price is hardcoded. Every expected value is recomputed from the live feed at run time.

`run_t41.py` works like this:
- It fetches `/api/v1/gpu-prices.json`, `/api/v1/gpu-price-changes.json`, and the homepage. Requests are sequential, 3 s apart, and back off on 429 or 5xx.
- It imports the repo's `core` and runs `mcp_server/server.py` tools in-process: `compare_gpu_prices`, `get_price_changes`, `optimize_stack`. These tools load the same public URLs. Telemetry is off. No secrets are needed.

## Run (release gate)
From the repo root, after `python3 scripts/generate_seo_pages.py` has built the feed:
```
pip install "mcp>=1.19,<2"   # mcp 2.x removed FastMCP
python3 tests/release_gate/run_t41.py                 # --source local (default): checks the built api/v1/*.json + index.html
python3 tests/release_gate/run_t41.py --source live   # optional: the public site (fetches are 3 s apart and back off)
```
In local mode the MCP tools read the built files through `LANTERN_*_FILE`, so no network is used. The script exits 1 if any case fails (`--no-fail` reports only). CI runs this as the `release-gate` job in `.github/workflows/validate-and-deploy.yml`, and `deploy` needs that job to pass.

The section below is Gauge's original live run, kept as written.

## Result 2026-10-29 (run 15:11 UTC = 11:11 AM EDT; repo ab2b037, VERSION 0.3.12; feed_updated_at 13:57:45Z, 88 rates / 14 vendors)
**19 of 20 cases pass, 1 fails.**

FAIL T41-01 (evidence completeness). On both Vast.ai marketplace rows, the public `basis` text comes from an older snapshot than the row's own fields and its `evidence.quote`:
- A100 SXM: basis says "7 ... offers ... min $1.1347/hr". evidence.quote, offer_count, and lowest_offer_usd say 6 offers, min $1.3389.
- RTX 4090: basis says "42 ... offers ... min $0.3356/hr". The fields and evidence say 43 offers, min $0.3887.

The median is the same in both, so ranking is unaffected. But the quote users see does not match the numbers published next to it.

Fix: rewrite `quote`/`basis` for marketplace records from the same API call that sets offer_count and lowest_offer_usd.

Observation, not a failure: for 37 rates, `basis` is not a substring of `evidence.quote`. All of their $ amounts do match. Examples are RunPod "H200 141GB $5.29/hr" and Modal "$0.001261/sec" against "$ 0.001261 / sec". The methodology calls basis "the exact vendor quote". Either reword the methodology or publish the verbatim snippet as basis.

Passed items worth noting:
- The earlier audit's Lambda 8x finding is fixed: gpu_count 8 and server_hourly_usd set (T41-09).
- The Modal preemption finding is fixed: there is an interruption_quote (T41-07).
- Reserved rows are never ranked first (T41-05).
- Whole-server billing holds on live CoreWeave and Lambda rows: 9 GPUs are billed as 16 (T41-11).
- The homepage shows "88 rates from 14 vendors", which matches the feed (T41-16).
