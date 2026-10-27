---
name: cheapest-gpu
description: Find the cheapest tracked GPU rental for a given GPU model, VRAM need and monthly hours, using the Lantern Works GPU price API.
---
# Cheapest GPU
1. With the MCP server: call `compare_gpu_prices` with `gpu` (e.g. `H100`); for a monthly total call `optimize_stack` with `gpu_hours` and `gpu_model`. Without MCP: GET https://thelanternworks.com/api/v1/gpu-prices.json.
2. (JSON path) Filter `rates` by `gpu` / `vram_gb` >= requirement.
3. Monthly cost = `hourly_equiv_usd` × hours (unit `hour`); for unit `month`, ceil(hours/730) × price.
4. Return the top 3 with the vendor quote, `source_url`/`checked_at` (or `verified_at`) and vendor link. Note `free_credits` separately. Affiliate status is not a ranking factor; disclose `affiliate: true`.
5. Prices exclude storage/egress/taxes — tell the user to confirm on the vendor page. Never sign up or pay without explicit user approval.

"Cheapest" means cheapest among tracked providers, not the whole market.
