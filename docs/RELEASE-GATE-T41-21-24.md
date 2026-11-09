# Release gate cases T41-21 to T41-24

Source of truth: `tests/release_gate/cases.json`; runner: `tests/release_gate/run_t41.py --source local|live <out.json>`. All four run against the built repo (local) and the live site (live).

| ID | Checks | Pass when | Why |
|---|---|---|---|
| T41-21 | /gpu/price-comparison/ per-model summary | Each model's lowest rate is the minimum hourly price among rows with `min_gpus` <= 1, not reserved, and not `core.serverless.rate_reason`, with out-of-stock rows last. The expected value is computed in the gate, not by calling the page's `_pick_cheapest`. | 0.3.19: reserved CloudRift rows were shown as cheapest. N-GPU minimums and serverless rows must not be named as the single-GPU price. |
| T41-22 | Every /gpu/cheapest-<model>-rental/ page | In each ranked table, no row without "out of stock when checked" comes after a row with it. | Gauge re14 K1: out-of-stock rows were mixed into the price ranking. |
| T41-23 | Fixture: A100 rows with `checked_at` = now - 9 h; page /gpu/cheapest-a100-rental/ | `compare_gpu_prices` rows have `in_stock` null and `availability_stale` true; the summary makes no in-stock claim; the site cell reads "unknown (stale availability, last checked <ET time>)"; every stock claim carries `data-av-checked` and the page carries the expiry script. | Gauge re16: 8 h limit; static pages must not go stale silently between builds. |
| T41-24 | /api/v1/gpu-prices.json, /api/v1/gpu/<family>.json, raw HTML of every /gpu/cheapest-*-rental/ page (no JavaScript) | Every `in_stock: true` claim has `availability_expires_at` and now <= that time; no raw-HTML "available when checked" claim is older than 8 h. | Gauge re17 2e: clients that do not run JS must never get an expired stock claim. |
