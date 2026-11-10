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
