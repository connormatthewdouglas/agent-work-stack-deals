# gpu-prices.json: model and form fields

Every rate in `api/v1/gpu-prices.json` carries these fields (since 0.5.0, T75). File-level timestamps and `held_stale` fields are documented below.


| Field | Type | Meaning |
|---|---|---|
| `gpu` | string | The GPU name as the vendor lists it (e.g. `H100 SXM`, `RTX PRO 6000 Max-Q`). Unchanged. |
| `canonical_model` | string | The tracked model this row belongs to, so consumers don't re-derive families: `H100`, `H100 SXM`, `H100 PCIe` and `H100 NVLink` are all `H100`; `A100*` is `A100`; the four `RTX PRO 6000*` strings are `RTX PRO 6000`. `H100 NVL` (94 GB) is its own model. Same grouping as the /gpu/ pages. |
| `form_factor` | string, never null | `SXM`, `SXM2`..., `PCIe`, `NVL`, or `not stated`. Taken from the vendor record when it states one, otherwise from the form named in the GPU string or in the vendor's own GPU id cited in the source (e.g. RunPod `NVIDIA B300 SXM6 AC` → `SXM6`) (an HGX board in the vendor quote counts as SXM). `NVLink` names the bridge, not the form, so it is `not stated`. Never guessed from the model alone. |
| `form_class` | string, H100 rows only | Ranking split used on the H100 pages: `SXM`, `PCIe`, `NVL` or `form not stated`. Unchanged. |

## Feed-level timestamps and held_stale.deal_id (P66 / P67, Nov 2026)

Every timestamp in `api/v1/gpu-prices.json` is UTC with a trailing `Z` (e.g. `2026-11-22T18:51:23Z`). The generator rewrites them at write time (`core.deals.apply_utc_z`). Parsers still accept a trailing `Z`, `+00:00`, and other numeric offsets.

| Field | Type | Meaning |
|---|---|---|
| `feed_updated_at` | string (ISO-8601 UTC, `Z`) | When the ranked GPU price rows in this file last changed. Independent of the deal catalog. |
| `prices_verified_through` | string (ISO-8601 UTC, `Z`) | Newest `verified_at` among ranked rates. |
| `availability_collected_at` | string (ISO-8601 UTC, `Z`) or null | When the imported Scout availability snapshot was collected. |
| `deal_feed_updated_at` | string (ISO-8601 UTC, `Z`) | When the served deal catalog (`api/v1/deals.json`, also `source_feed`) last changed. Taken from that file's `updated_at`, which is the later of the source `deals.json` `updated_at` and `data/feed_state.json` (set when served deal content changes). It is not a GPU price-check time. It can lag `feed_updated_at` when GPU prices move and the deal catalog does not; that lag is left visible and is never advanced to hide staleness. |

`held_stale[].deal_id` is the public deal catalog id for that vendor when one exists in `deals.json` (the same id as on the vendor pricing record). It is null when no such deal exists — the vendor is tracked for GPU prices only, and links go to the vendor's own page. Ids are never invented. A null `deal_id` means the vendor has no row in the deal catalog; it does not mean a value is missing or failed to load.

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
## failure_reason, failure_reason_detail (additive, P41, Nov 2026; MCP)

`compare_gpu_prices` and `estimate_job_cost` add these to every result's `availability` (and to the row itself). They describe a failed or "no" stock probe with a fixed reason, so a hit ratio can group the nos. Computed at call time from the probe outcome already on the row (`core/probe_reason.py`). A lapsed claim keeps the last no beside `last_known_in_stock` instead of dropping it. Brief rows carry the fields only when `failure_reason` is set. Ranking never reads them.

| Field | Type | Meaning |
|---|---|---|
| `failure_reason` | `sold_out`, `region`, `quota`, `other`, or null | `sold_out`: the probe (or the last firm answer on a lapsed claim) said out of stock, and the source did not state region or quota. `region` / `quota`: only when the source itself states that reason. `other`: a recorded probe failure (`check_failed_http` / `check_failed_timeout`) that is not one of those three. Null when the source does not say (unknown, `no_source`, a last-known in-stock, or never probed). Never guessed: `derived_from_regions` or "no confirmed region" is not `region`. |
| `failure_reason_detail` | string or null | The source or Scout detail, passed through unchanged. Null when there is no source detail (our stale-claim note is not used). |

HTTP-failed probes that never landed in a Scout snapshot cannot be invented here. When such a row does appear, it is `other`.
## next_check_at, will_backfill, backfill_eta (additive, P40, Nov 2026; MCP only)

`compare_gpu_prices` adds these to every result whose stock is unknown (`in_stock` null, including a lapsed claim) and to every `stale_prices` entry (`core/check_schedule.py`). They are computed when you call the tool, because a "next check" time written into the static feed would go out of date. Brief rows carry `next_check_at` and `will_backfill`. Ranking never reads them.

| Field | Type | Meaning |
|---|---|---|
| `next_check_at` | string (ISO-8601 UTC) or null | The next scheduled run, at or after the request, that can re-check this row. Null when no schedule covers it. GitHub cron can start late. |
| `will_backfill` | boolean or null | `true` ("filling"): a scheduled check covers this row and will try again. `false` ("scope limit"): nothing scheduled re-checks it. `null`: not derivable from our config. `true` does not promise the source will answer, and a missed check is never re-run for the past. |
| `backfill_eta` | string (ISO-8601 UTC) or null | The last scheduled attempt in that cycle: for daily prices the 14:47 UTC fallback after the 10:23 UTC primary run. Other schedules have no fallback, so this equals `next_check_at`. Null when `will_backfill` is not `true`. |
| `next_check_basis` | string | Which schedule or config produced the answer. |

How each case is derived (each constant is asserted against its workflow file in `tests/test_p40_next_check.py`):

- **Unknown stock, row has Scout stock data** (`availability.origin` `scout`, including `no_source` reads such as `api_null_signal` / `unconfirmed_two_reads` and lapsed claims): the next 4-hourly import slot of `.github/workflows/scout-import.yml` (00/04/08/12/16/20 UTC, from :10). A new Scout push can import sooner. `will_backfill: true`.
- **Unknown stock, no Scout stock source** (no Scout row, or Scout `no_api`): scope limit. `will_backfill: false`, `next_check_at: null`.
- **Stale price, `price_check` `daily`** (also `rotating snapshot`): `.github/workflows/gpu-refresh.yml`, 10:23 UTC, fallback 14:47 UTC.
- **Stale price, Lium**: `.github/workflows/lium-collect.yml`, every 2 h at :40 UTC (`scripts/collect_lium.py`). Lium is marked `manual snapshot` in the feed but has this scheduled collector.
- **Stale price, `price_check` `batch`** (Scout wider-GPU batch): `scripts/import_scout_wider.py` in the next 4-hourly `scout-import.yml` run (from :10 UTC), when Scout has published a batch.
- **Stale price, any other `manual snapshot`** (for example Clore.ai, Cirrascale): scope limit. `will_backfill: false`, `next_check_at: null`.
- **Anything else**: all null, with basis "not derivable".
## last_verified_before and gap_days on price changes (additive, P46, Nov 2026)

On every up/down change in `/api/v1/gpu-price-changes.json` and in `changes` of `/api/v1/gpu-prices/history.json`, and on `get_price_changes` rows and `compare_gpu_prices` `history.recent_changes` (`core.gpu_history.change_gap`).

| Field | Type | Meaning |
|---|---|---|
| `last_verified_before` | string (ISO-8601 UTC) or null | `verified_at` of the last daily snapshot that still showed the previous price for this rate (the last time we confirmed the old price). Null on `new` and `removed` entries, and when that timestamp is missing. |
| `gap_days` | number (2 dp) or null | Days from `last_verified_before` to the `verified_at` of the first snapshot that showed the new price. The vendor changed the price inside that window: after `last_verified_before`, and at or before `last_verified_before` + `gap_days`. Null when either timestamp is missing, or when they are out of order. |


## last_known_in_stock and last_known_at (additive, P36, Nov 2026)

On every GPU rate's `availability` in `gpu-prices.json` and in `compare_gpu_prices` / `estimate_job_cost` (full mode; brief rows carry them only when they add something: `in_stock` is null and last_known is a firm value). Display only: ranking still reads `in_stock`.

| Field | Type | Meaning |
|---|---|---|
| `last_known_in_stock` | boolean or null | The last firm true/false stock answer. Set when a claim lapses (expired) or is dropped because the price changed after the stock check (`price_join_guard`). A current firm claim reports itself in full mode. A quota, region, or rate-limit failure, or a recorded check failure, does not overwrite it (P64): the current reading is unknown (`in_stock` null) and the previous last_known value and time stay put. Null when there was never a firm, dated claim. Never invented. |
| `last_known_at` | string (date-time) or null | The `checked_at` of that firm claim (ISO UTC). Null when `last_known_in_stock` is null. Not updated when a later check fails. |

last_known is marked stale **8 hours** after `last_known_at`. That number is `AVAIL_MAX_AGE_H` in `core/gpu_availability.py`. An `in_stock` true reading and a sold_out (`in_stock` false) last_known use this same clock. last_known stays visible beside the stale mark and is not dropped. A live firm claim may still lapse sooner under existing claim lifetimes (1 hour for Lambda, Verda, RunPod/Oblivus overall, and region-derived claims; 15 minutes for Verda spot); those lifetimes apply equally to true and false.

| Failure / outcome | Keeps last_known? | Ageing |
|---|---|---|
| `quota` (source-stated rate limited, quota exhausted, quota exceeded, and similar) | Yes. Current reading is unknown (`in_stock` null). `checked_at` / `last_check_at` move to this check. | Marked stale 8 hours after `last_known_at` (`AVAIL_MAX_AGE_H` in `core/gpu_availability.py`). Still shown, not dropped. |
| `region` (source-stated region unavailable, not in region, not served, and similar) | Yes, same as quota. Current reading is unknown. `checked_at` / `last_check_at` move to this check. | Same 8-hour clock (`AVAIL_MAX_AGE_H`). |
| `sold_out` (firm `in_stock` false, and the source did not state region or quota) | This is a real observation: it updates last_known to false at this check time. | Same 8-hour clock from that observation (`AVAIL_MAX_AGE_H`). Same clock as `in_stock` true. |
| `other` (`check_failed_http`, `check_failed_timeout`) | Yes (not a firm observation; last_known is not updated). Current reading is unknown. | Same 8-hour clock on the prior last_known, if any. No separate ageing rule for the failed check itself. |
| `no_source` / unknown with no prior firm claim | Nothing to keep; last_known is not invented. | No last_known is shown. If a prior last_known exists, it is kept and ages on the same 8-hour clock. |
| Price-join drop (`price_join_guard`, #211) | Yes: last_known is the firm, dated claim that was dropped. `in_stock` is null. | Then the same 8-hour clock (`AVAIL_MAX_AGE_H`) as any other last_known. |
| Claim lapse (time / `availability_expires_at`) | Yes (P36): last_known is the firm claim that just lapsed. | The claim lapses when now is after `availability_expires_at` (UTC). A claim at the exact expiry instant is still valid. There is no grace period or clock-skew tolerance. Once lapsed, it is marked stale; last_known is still shown, not dropped. Live claims may lapse sooner than 8 hours under the existing lifetimes above, equally for true and false. |

## last_known claim window (additive, P68, Nov 2026)

`last_known_in_stock` is flagged against **that row's own** last firm claim window, and the window is shown on every GPU row so a client can check it (Brain #1081). The P64 8h `stale_guard` clock is unchanged: `in_stock` is still nulled on that clock (or sooner when a live claim's own `availability_expires_at` has lapsed). last_known stays visible; it is not dropped or rewritten.

| Field | Type | Meaning |
|---|---|---|
| `max_age_hours`, `availability_expires_at` | number / string or null | The current reading's claim window (P72). Shown on every row, including `no_source`. |
| `last_known_expires_at` | string (date-time, UTC `Z`) or null | Expiry of the last firm stock claim, anchored on `last_known_at`. A later failed or `no_source` read never extends this window. |
| `last_known_max_age_hours` | number or null | TTL in hours that produced `last_known_expires_at`. |
| `last_known_outside_window` | boolean | True when now is after `last_known_expires_at`. Absent when there is no last_known. |

A Verda 0.25 h last_known is flagged 15 minutes after `last_known_at`, even though `stale_guard` would only mark `availability_stale` at 8 h (or at the live claim expiry). A failed read after a 1 h firm claim keeps the 1 h last-known window, not `checked_at + 8 h`.
## marketplace_query and composition_flag (additive, P45, Nov 2026)

On marketplace-median rates (`price_status=marketplace`) in `gpu-prices.json` and `compare_gpu_prices`, and on
up/down marketplace median moves in `gpu-price-changes.json`, `history.json`, `get_price_changes` and
`compare_gpu_prices` `history.recent_changes`. Requested by hermesagentj. Additive. Ranking is unchanged.
Stale prices stay flagged as stale.

Daily snapshots (`data/gpu_pricing/snapshots/`) and history points keep `lowest_offer_usd` and `offer_count` when
the vendor record already has them. Older snapshots do not have these fields and are not rewritten.

| Field | Type | Meaning |
|---|---|---|
| `marketplace_query` | object or null | The literal marketplace filter used for this median, plus structured `filters` and `url` when known. Null when the row is not a marketplace median, or the query cannot be recovered from the record. For Vast.ai, `literal` is the decoded bundles filter; `vram_gb` is applied after the API query (it is not in the URL). For Clore.ai, `literal` is the documented method (`price.on_demand['USD-Blockchain']` / 24 / gpu_count, unrented, USD, spot/bid excluded, homogeneous servers). Never invented. Brief mode carries `{literal}` only. |
| `composition_flag` | `composition`, `price`, `mixed`, `unknown`, or null | Taken from successive median, minimum and listing count only, not from a host-intersection (that needs stable host ids, P44). `price` only when the listing count is unchanged and median and min moved in the same direction. `composition` when median and min moved in opposite directions, or only the basket/count changed. `mixed` when the listing count changed and median and/or min also moved. `unknown` when a median moved but the previous minimum or listing count was not recorded. Null when this is not a marketplace median, or nothing moved. A `composition`, `mixed` or `unknown` flag is **not a price move** and is not counted in `price_drops` / `price_rises` or titled as a drop or rise. The same rule applies to `gpu-price-changes.json` `counts`: `down` and `up` include only price moves (`composition_flag` is null or `price`); `composition`, `mixed` and `unknown` are separate additive counts. |
| `composition_previous` | object or null | The previous snapshot's `median_usd`, `lowest_offer_usd`, `offer_count` and `verified_at` used to classify the flag (full mode). The previous reading's age stays visible. Null when there is no previous snapshot for this rate. |

## availability_status, availability_reason, availability_reason_detail (additive, Scout schema 3.2, Nov 2026)

| Field | Type | Meaning |
|---|---|---|
| `availability_status` | string or null | Lantern Scout's own stock status for the row, carried through unchanged: `in_stock`, `out_of_stock` or `unknown`. Null when Scout has no row for this quote. Also inside `availability` on Scout-origin rows. It is Scout's value as of `availability.checked_at`; `availability.status` / `availability.in_stock` remain the site's expiry-guarded claim and are unchanged. |
| `availability_reason` | string or null | Scout's machine-readable reason for the status (e.g. `no_source`), unchanged. |
| `availability_reason_detail` | string or null | Scout's finer reason (e.g. `no_api`), unchanged. |


## machine_ids and listing_ids (additive, P44, Nov 2026)

Vendor-native identifiers recorded by Scout on availability rows and inside `available_regions_detail`. Null when the vendor did not provide one, or when Scout has no availability collector for that vendor. Never invented. Schema 3.2 is unchanged.

| Field | Type | Meaning |
|---|---|---|
| `machine_ids` | array of integers, or null | Vast.ai `machine_id` values from the offers that made up this snapshot row (overall or region). |
| `listing_ids` | array of integers, or null | Clore.ai marketplace listing `servers[].id` values for the unrented servers in this snapshot row. |

Lium node ids are not in this import yet: Scout has no Lium availability collector.

## T116: stock frequency is not a dollar cost

`expected_cost_usd` is **deprecated and always null**. `expected_cost_label` explicitly marks the deprecation.
The old `hourly / max(observed_share, 0.1)` formula was not a quote or predicted bill and must not be used
for quotes, budgets, rankings, or financial forecasts. No replacement monetary estimate is emitted.
Use `hourly_equiv_usd` and the existing whole-instance/minimum-GPU rules for compute subtotals.

`availability_rate_7d` remains a descriptive observation: `rate` (stocked / known checks, null with zero known),
`checks` (legacy known count), `known_checks`, `unknown_checks`, `total_checks`, `in_stock_checks`,
`window_start`, `window_end`, `window_days`, and first/last observation timestamps. `window_days` is the planned window (7; the name is not a claim that checks span seven days) and is not renamed. P58 (additive) publishes `first_check_at` (ISO timestamp of the earliest check actually in the window, null if none) and `observed_hours` (the actual coverage in hours from `first_check_at` to `last_check_at`, or to `window_end` when last is missing, rounded to 1 decimal; null if no usable first stamp). P59 (additive) adds `coverage_note`, set only when `observed_hours` is not null and is shorter than `window_days` × 24 (e.g. "Covers 24.1h of the planned 7-day window."); otherwise null. The rate is unchanged. P61 (additive) adds a file-level `availability_window_summary` on `gpu-prices.json` and on the `compare_gpu_prices` output: `no_window_count` is the number of ranked rates with no 7-day stock window, split by `no_stock_source` (no stock source was read), `read_no_usable_signal` (a source was read but `in_stock` is null), and `signal_no_window_yet` (a usable `in_stock` true/false is present, but no 7d window yet). `earliest_first_check_at` is the earliest `first_check_at` among current windows (null if none). Counts are computed from the row data. `content_build_id` is a 16-character sha256 prefix of the canonicalized ranked-row content, excluding timestamps and ids; a price-only rebuild changes it. `generation_id` is unchanged. Unknown observations
are excluded from the share, but not hidden from the counts. P38 (additive) splits `unknown_checks` by why each check had no stock answer, using the row's own
`availability_reason` (Scout T113 enum): `never_ran_checks` = no stock reading was taken (`check_failed_timeout`,
`check_failed_http`, or `stale`/backoff); `no_source_checks` = the probe ran but the source gives no stock signal
(`no_source`: the vendor API returned no stock field, two reads did not confirm, no matching API row, or no API).
`unknown_checks` is unchanged and always equals `never_ran_checks + no_source_checks` when both are set. Both are null
when any unknown check in the window has no recorded reason, or when the source does not carry the split yet
(`source: scout_t112` rows until Scout's T112 build emits `never_ran_checks_7d` / `no_source_checks_7d`); never a guessed split. Legacy captures without unknown counts emit null,
not an invented zero. `sample_status` distinguishes observed, insufficient_sample (<6 known), and all_unknown;
`window_stale` flags windows whose last observation is older than 24h or undated. Sparse/old data remains
labelled historical description, never a probability forecast. `source` is `scout_t112` or `git_history`.
P62 (additive): when `last_check_at` is older than the planned 7-day window, the current `rate` is null (not the old share presented as current). The object keeps `last_check_at`, adds `last_observed_rate` (the last computed share, or null when that window had no known checks), `window_status` `lapsed`, and `stale_age_hours` (age of `last_check_at`, 1 decimal). A current window is unchanged and has no `window_status`. Site copy for a lapsed row is "lapsed · last checked <age> ago" instead of a blank cell.

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

## max_age_source, availability_expires_at on every availability row, probe_error (additive, P72 / P73, Nov 2026)

P72 (marxsignal) and P73 (morpheus404). Additive optional fields on each rate's `availability` object and, when present, on imported Scout rows. The imported snapshot schema stays `lantern-works-gpu-availability/1`. Scout snapshot version stays 3.2. Ranking does not read these fields.

| Field | Type | Meaning |
|---|---|---|
| `max_age_source` | `provider`, `policy`, or `fallback` | Where `max_age_hours` came from. `provider`: the vendor stated the lifetime (`provider_max_age_hours`). `policy`: the TTL `stale_guard` actually applied. That is Scout's already-computed `availability_expires_at` / `_min_expiry` when present (15 min Verda spot; 1 h for Lambda, Verda, and region-derived claims), otherwise the 8 h `AVAIL_MAX_AGE_H` bar used on main (including RunPod, Oblivus, Novita, and Thunder). Annotation runs only after `stale_guard` and does not change enforcement. `fallback`: there is no time basis to compute an expiry. |
| `max_age_hours` | number or null | Claim lifetime in hours. Null only when `max_age_source` is `fallback`. Never invented. |
| `availability_expires_at` | string (ISO-8601 UTC, `Z`) or null | Present on every availability row, including `no_source` and `never_ran`. Null when there is no check time to add a lifetime to, together with `max_age_reason`. |
| `max_age_reason` | string | Why expiry is null. Omitted when expiry was computed. |
| `probe_error` | object or absent | Written when the stock/terms probe crashes: `type` (exception class) and `message` (short, with secrets, tokens, and credential-bearing URLs stripped). |
| `probe_attempted_at` | string (ISO-8601 UTC, `Z`) or absent | The crash attempt time. This is not a successful check. If a historical field is called `checked_at`, freshness, the 72h ceiling and `expire_held_rows` still read only successful-check stamps (`evidence.checked_at`, `verified_at`, or a successful `checked_at`). Failed collection never writes a fresh `verified_at` or success `checked_at`. |

## cancellation (additive, P63, Nov 2026)

Reserved / commitment rows may carry a `cancellation` object written by the reserved-terms probe (Civo legal terms, CloudRift terms of service, Hyperstack contracts docs). It is absent when no probe has run (unknown stays unknown). Schema stays `lantern-works-gpu-prices/1`. Ranking and stale/TTL behaviour are unchanged.

| Field | Values | Meaning |
| --- | --- | --- |
| `terms_flag` | `present_and_read` \| `confirmed_absent` \| `unreadable` | Whether cancellation terms were observable at probe time. Every probe writes one of these three. A failed fetch (including a disallowed or empty response) is `unreadable`. |
| `terms_read_at` | ISO-8601 timestamp, or absent | When the terms page was successfully read. **Absent** on `unreadable`. Never used to refresh `checked_at` / `verified_at` of the price. |
| `cancel_window` | object with `text` (and `value` / `unit` only when the vendor publishes a number), or absent | The published cancel / notice window. Omitted when the vendor does not publish one. |
| `cancel_fee` | object with `text` (and `value` / `kind` only when published), or absent | The published cancel / early-exit fee or refund rule. Omitted when the vendor does not publish one. |
| `source_url` | https URL | The official page that was read (or attempted). |
| `quote` | string, or absent | Visible page text that supports a `present_and_read` window or fee. Existing price `evidence` quotes and quote IDs are left untouched. |

`present_and_read` requires a published window or fee. `confirmed_absent` is a successful read that found neither. `unreadable` must not stamp `terms_read_at` and must not invent a window or fee.
## stock_age_hours and stock_read_state (additive, P74, Nov 2026)

P74 (morpheus404, Brain #1142 and #1172). Computed at serve/read time on `compare_gpu_prices` and `find_available_gpus` results, and rendered on GPU pages. Not written into the static `gpu-prices.json` schema (that schema stays `lantern-works-gpu-prices/1`). Ranking, TTLs and `stale_guard` do not read these fields. Unknown stays unknown. Timestamps are never invented.

| Field | Type | Meaning |
|---|---|---|
| `stock_age_hours` | number or null | Hours from the reader clock back to the stock claim time: `last_known_at` when the claim has lapsed or `in_stock` is unknown after a prior firm answer; otherwise `stock_read_at`, or the stock `checked_at` when `stock_read_at` is absent. Null when no stock stamp exists (`never_read`). Not price `data_age_hours`. `probe_attempted_at` and the price row's `verified_at` / `checked_at` are not used. |
| `stock_age_basis` | `stock_read_at`, `checked_at`, `last_known_at`, or null | Which stock stamp was used. |
| `stock_read_state` | `never_read`, `read`, or `read_expired` | `never_read`: no stock check timestamp. `read`: a check was taken and the claim has not expired. `read_expired`: a check was taken and the claim has expired (`availability_stale`, or now is after `availability_expires_at`). |
