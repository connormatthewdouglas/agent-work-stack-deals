# gpu-prices.json: model and form fields

Every rate in `api/v1/gpu-prices.json` carries these fields (since 0.5.0, T75):

| Field | Type | Meaning |
|---|---|---|
| `gpu` | string | The GPU name as the vendor lists it (e.g. `H100 SXM`, `RTX PRO 6000 Max-Q`). Unchanged. |
| `canonical_model` | string | The tracked model this row belongs to, so consumers don't re-derive families: `H100`, `H100 SXM`, `H100 PCIe` and `H100 NVLink` are all `H100`; `A100*` is `A100`; the four `RTX PRO 6000*` strings are `RTX PRO 6000`. `H100 NVL` (94 GB) is its own model. Same grouping as the /gpu/ pages. |
| `form_factor` | string, never null | `SXM`, `SXM2`..., `PCIe`, `NVL`, or `not stated`. Taken from the vendor record when it states one, otherwise from the form named in the GPU string or in the vendor's own GPU id cited in the source (e.g. RunPod `NVIDIA B300 SXM6 AC` → `SXM6`) (an HGX board in the vendor quote counts as SXM). `NVLink` names the bridge, not the form, so it is `not stated`. Never guessed from the model alone. |
| `form_class` | string, H100 rows only | Ranking split used on the H100 pages: `SXM`, `PCIe`, `NVL` or `form not stated`. Unchanged. |

## price_basis_label, form_factor and cheapest grouping (additive, Nov 2026)

- `price_basis_label` (every row in `gpu-prices.json` and `/api/v1/gpu/<model>.json`): plain-language basis of the number.
  On-demand rows: **on-demand list price per GPU-hour; tracked providers only; excludes storage, egress, idle time and preemption.**
  Interruptible, serverless, reserved and monthly rows say so in their own label. The older `price_basis` field is unchanged.
- `form_factor` (every row): `SXM`, `PCIe`, etc. as stated by the vendor or GPU name; `unknown` in model views when the source does not say.
- `tier`: the vendor's own tier (e.g. RunPod Community Cloud vs Secure Cloud); `unknown` when the source does not say.
- `cheapest[bucket]` in model views has one row per (`vram_gb`, `form_factor`, `tier`) group, sorted by `vram_gb` then price,
  so SXM vs PCIe and Community vs Secure are never mixed in one cheapest row. Each cheapest row carries `group`, `verified_at` and `source_url`.
  Compare headline $/GPU-hour only within a group.
- `cheapest` omits the `reserved` and `serverless` buckets. A row is serverless when `core.serverless.rate_reason` matches
  (a `price_per_second_usd`, or serverless / flex / active-worker / per-second / scale-to-zero text on the tier, billing, or price basis).
  Other bucket keys (`on-demand`, `spot-community`, `monthly`) are omitted when every row in that bucket fails the headline rule,
  including `min_gpus` above 1. That is why `a100.json` has no `cheapest.monthly` and `l40.json` has no `cheapest.spot-community`.
  The rows themselves stay in `rows`. Schema id remains `lantern-works-gpu-model-view/1`.

## price_effective_at (additive, schema 3.2, Nov 2026)

| Field | Type | Meaning |
|---|---|---|
| `price_effective_at` | string (ISO-8601 UTC) or absent | The vendor's own stated instant when this listed public price takes effect. Set only from a sentence on the vendor's public page (Lambda: "These prices take effect November 16, 2026, at 00:00 UTC"). Absent when the vendor does not date the list. Until that instant the row is listed in `held_stale` with a `not yet in effect:` reason and is never ranked as a current price; after it, the field stays on the ranked rate as an annotation. Current prices that require a login are not invented.

## effective_at and min_bill_usd_per_hour (additive, P37/P43, Nov 2026)

On every rate in `gpu-prices.json` and every `compare_gpu_prices` result (full mode always; brief rows carry them only when they add something: `effective_at` when known, `min_bill_*` when `min_gpus` > 1). Computed by `core/rate_dates.py`. Display only: ranking never reads them.

| Field | Type | Meaning |
|---|---|---|
| `effective_at` | string (ISO-8601 UTC) or null | When the vendor started charging the current price. Different from `last_verified` / `verified_at` (when we last confirmed it). See `effective_at_basis`. Null when real data cannot date it: the price is the first one we recorded for this rate (it predates our tracking, which starts 2026-10-27), the rate left tracking in between, or the price moved after the latest daily snapshot. Never guessed. |
| `effective_at_basis` | `vendor_stated`, `first_observed` or null | `vendor_stated`: the vendor's page dates the price (`price_effective_at`), and `effective_at` is that instant exactly. `first_observed`: our daily snapshots (`/api/v1/gpu-prices/history.json`) saw a different price for this exact rate earlier, and `effective_at` is the `verified_at` in the first snapshot showing the current price. That is an upper bound: the change happened at or before it, and after the earlier price was last seen. If a stated date is older than an observed later change, the observed change wins. |
| `min_bill_usd_per_hour` | number or null | `min_gpus` x the per-GPU hourly price (`hourly_equiv_usd` in the feed, `hourly_usd` in MCP rows): the least you pay per hour for one allocation. Equals the hourly price when `min_gpus` is 1. Null when either input is missing. Also on `excluded_min_gpus` entries. |
| `min_bill_basis` | `hourly_rate`, `per_second_rate`, `monthly_equivalent` or null | What the hourly price is: the vendor's own per-GPU hourly rate; its per-second rate x 3600 (billed per second while running); or, for flat monthly servers, a derived equivalent (monthly price / 730 h). A `monthly_equivalent` is not a quoted hourly rate: the vendor bills the month. Marketplace rows use the median offer, as `hourly_equiv_usd` does. |


## batch_due_ledger (additive, P39, Nov 2026; MCP, full mode)

`compare_gpu_prices` (full mode) includes `batch_due_ledger`: one entry per scheduled build or collection, derived only from the workflow files and the current feed's membership (`core/batch_ledger.py`). Brief mode omits it (the member id lists would blow the brief-size budget). Ranking never reads it. Tests assert each schedule constant against its workflow file.

| Field | Type | Meaning |
|---|---|---|
| `build` | `gpu-refresh`, `lium-collect`, `scout-import`, or `scout-wider` | Which scheduled collection this entry is. `scout-wider` rides the same `scout-import.yml` run as `scout-import`. |
| `expected_at` | string (ISO-8601 UTC) | The next scheduled slot at or after the request. GitHub cron can start late. |
| `last_expected_at` | string (ISO-8601 UTC) | The most recently due slot, including a slot that is due now. Compare a row's `checked_at` to this to see "due, not renewed". This is not a claim that the run happened. |
| `fallback_expected_at` | string (ISO-8601 UTC) or null | For `gpu-refresh` only: the next 14:47 UTC fallback. Null on the other builds (they have no fallback). |
| `member_rate_ids` | array of `rate_id` | The feed rows this build is scheduled to cover, so "in the batch but failed" is distinguishable from "never in the batch". |
| `member_count` | integer | `len(member_rate_ids)`. |
| `schedule_basis` | string | Which workflow or script produced the answer. |

Membership:

- **gpu-refresh**: `price_check` is `daily` or `rotating snapshot`, excluding Lium (Lium has its own collector).
- **lium-collect**: Lium rows (`.github/workflows/lium-collect.yml`, every 2 h at :40 UTC).
- **scout-import**: rows whose `availability.origin` is `scout`, except Scout `no_api` (out of scope, not in the batch).
- **scout-wider**: `price_check` is `batch` (`scripts/import_scout_wider.py` in the same 4-hourly `scout-import.yml` run).

## availability_status, availability_reason, availability_reason_detail (additive, Scout schema 3.2, Nov 2026)

| Field | Type | Meaning |
|---|---|---|
| `availability_status` | string or null | Lantern Scout's own stock status for the row, carried through unchanged: `in_stock`, `out_of_stock` or `unknown`. Null when Scout has no row for this quote. Also inside `availability` on Scout-origin rows. It is Scout's value as of `availability.checked_at`; `availability.status` / `availability.in_stock` remain the site's expiry-guarded claim and are unchanged. |
| `availability_reason` | string or null | Scout's machine-readable reason for the status (e.g. `no_source`), unchanged. |
| `availability_reason_detail` | string or null | Scout's finer reason (e.g. `no_api`), unchanged. |

## T116: stock frequency is not a dollar cost

`expected_cost_usd` is **deprecated and always null**. `expected_cost_label` explicitly marks the deprecation.
The old `hourly / max(observed_share, 0.1)` formula was not a quote or predicted bill and must not be used
for quotes, budgets, rankings, or financial forecasts. No replacement monetary estimate is emitted.
Use `hourly_equiv_usd` and the existing whole-instance/minimum-GPU rules for compute subtotals.

`availability_rate_7d` remains a descriptive observation: `rate` (stocked / known checks, null with zero known),
`checks` (legacy known count), `known_checks`, `unknown_checks`, `total_checks`, `in_stock_checks`,
`window_start`, `window_end`, `window_days`, and first/last observation timestamps. Unknown observations
are excluded from the share, but not hidden from the counts. Legacy captures without unknown counts emit null,
not an invented zero. `sample_status` distinguishes observed, insufficient_sample (<6 known), and all_unknown;
`window_stale` flags windows whose last observation is older than 24h or undated. Sparse/old data remains
labelled historical description, never a probability forecast. `source` is `scout_t112` or `git_history`.

No MCP field was renamed or removed; the legacy dollar field must remain null wherever exposed.

## T117: usable citation URLs and API evidence

Every current price citation's `source_url` (also `evidence.source_url`) is a syntactically valid HTTPS URL
without appended operation text. The 23 RunPod and 12 Verda/DataCrunch legacy citations were repaired
mechanically, without changing prices, quotes, quote timestamps or identity. No replacement webpage was guessed.

- RunPod: `https://api.runpod.io/graphql` is **POST-only GraphQL**, not a browsable pricing page. A GET/HEAD
  rejection does not mean this citation is dead. `evidence.request_method=POST`, `evidence.operation`
  (`gpuTypes.securePrice` or `gpuTypes.communityPrice`), and `evidence.record_id` retain the exact quoted
  field and vendor GPU type id. An authenticated vendor API request may be needed to reproduce it;
  no credentials are published.
- Verda/DataCrunch: `https://api.datacrunch.io/v1/instance-types`, `request_method=GET`,
  `operation=instance-types`; `record_id` retains the exact instance key previously placed in parentheses.
  API access may require vendor authentication; evidence is not a promise of anonymous access.

`scripts/normalize_gpu_sources.py` runs at the Scout import boundary, splits only these known formats, and
rejects unrecognized invalid URLs before writing anything. `--check` validates without repair. The shared
price-record validator also rejects invalid URLs at export. Model feeds preserve request metadata, and
history exports normalize citations without rewriting historical snapshots. API evidence fields are additive;
no MCP fields are renamed.
