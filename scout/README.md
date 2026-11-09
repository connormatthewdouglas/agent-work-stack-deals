# Lantern Scout — availability collectors (T11/T19, T18 design)

This tree lives at `scout/` in the agent-work-stack-deals repo. `scripts/build_clore.py` stays next to `scripts/import_clore_snapshot.py`; it builds the Clore price snapshot, which is a different job from this availability collector.

## Running from the repo

`SCOUT_DIR` defaults to the directory of the shell script (this folder). The work box used `/workspace/lantern-scout`. Cron and routines there call `run_cycle.sh` and `run_multi_refresh.sh`. From a checkout:

```
<checkout>/scout/run_cycle.sh
<checkout>/scout/run_multi_refresh.sh
```

The deals checkout the work-box push hook already used is `/workspace/agent-deals-feed/repo`, so after cutover those become `/workspace/agent-deals-feed/repo/scout/run_cycle.sh` and `.../run_multi_refresh.sh`. Until this is merged and the box is switched, `/workspace/lantern-scout` stays the runtime. `run_runpod_refresh.sh` is the older RunPod-only refresh.

Secrets are never committed. Verda and Lambda read `secrets/verda.env` and `secrets/lambda.env` relative to the working directory (`VERDA_CLIENT_ID`, `VERDA_CLIENT_SECRET`, `LAMBDA_API_KEY`). `wider_gpu.py` honors `WGPU_SECRETS_DIR` instead of `secrets/`. Hyperstack reads `HYPERSTACK_API_KEY`, then `/workspace/secrets/hyperstack_api_key.txt`. Novita reads `NOVITA_API_KEY`, then `/workspace/secrets/novita_api_key.txt`. Names only: `secrets.env.example`. `secrets/` and `out/` are gitignored.

`feed-src/` stays `$SCOUT_DIR/feed-src`. `enrich_feed_v2.py` treats it as a scratch clone: if it is a git checkout it `git fetch`es and `git reset --hard origin/main`, otherwise it clones this repo into it. Pointing that path at the repo checkout would reset the checkout, so it is not redirected here. It is gitignored. `collect_v2.feed_min_market_offers` reads `feed-src/core/gpu.py` (`MIN_MARKET_OFFERS`).

`push_hook.sh` runs `scripts/push_scout_snapshot.sh` from this repo. It does not keep `bin/push_scout_snapshot.sh`. The work box fetched `origin/main:scripts/push_scout_snapshot.sh` and ran `sed` to insert `t112_availability_rate_7d.json` after `RUN_LOG.txt`. The repo script already lists that file. The hook still applies the same sed to a temp copy, so the T112 file is published either way, and the tracked script is not edited.

`collect.py` → `out/availability_latest.{json,csv}` + timestamped JSON (normalized rows:
vendor, gpu_model, tier, region, in_stock, offer_count, stock_level, price_usd_hr, source_url, collected_at UTC, refresh_rate).
`enrich_feed.py` → `out/feed_enriched_latest.json`: existing feed rows (H100/A100/RTX 4090, repo `data/gpu_pricing/*.json`)
plus region / in_stock / offer_count / refresh_rate. Repo files are NOT modified. Unknown stays `null`/`"unknown"`.

## Vendor coverage (existing feed vendors first)
| Vendor | Region | In-stock | Offer count | How (public, no auth) | Status |
|---|---|---|---|---|---|
| Vast.ai | yes (country, `geolocation`) | yes | yes (rentable offers) | `console.vast.ai/api/v0/bundles` | collector ✅ |
| RunPod | yes (Secure Cloud DC ids) | stock level High/Med/Low | no | `api.runpod.io/graphql` gpuTypes.lowestPrice + dataCenters.gpuAvailability (no key) | collector ✅ |
| TensorDock | per-host in marketplace | likely | likely | old v0 hostnodes API 404; v2 needs token | blocked (needs account/API token) |
| Verda (DataCrunch) | yes (FIN-01 etc.) | yes | no | `/v1/instance-availability` → 401 | blocked (API creds) |
| Lambda | yes | yes (`regions_with_capacity_available`) | no | `/api/v1/instance-types` → needs API key | blocked (free account + key) |
| Hyperstack, CoreWeave, Nebius, DigitalOcean, Modal, Thunder, 99stack, Ucartz, Novita, Salad | region lists on pages at best | no public signal | no | static pricing pages | unknown (daily list price) |
| AWS/GCP/Azure spot | yes | spot price ≠ stock | no | AWS needs creds; Azure Retail Prices API is public (price+region, no stock) | future: Azure prices |

## Refresh design (T18)
- Marketplace/spot rows (Vast, RunPod stock, Verda/Hyperstack spot): every 4h, `refresh_rate="4h (marketplace/spot)"`.
- Static list prices stay daily: `refresh_rate="daily (list price)"`.
- Each row carries its own `collected_at`/`availability_checked_at`; consumers should treat >2× cadence as stale.
```
# crontab (UTC): availability every 4h, staggered from the daily price job
17 */4 * * * cd /workspace/lantern-scout && python3 collect.py && python3 enrich_feed.py >> out/cron.log 2>&1
```
Polite: 2s gap between Vast calls, one RunPod GraphQL call per run (~6 requests/run).

## v2 (QA fixes from Gauge, 2026-10-29)
Files: `collect_v2.py`, `enrich_feed_v2.py` → `out/availability_v2_latest.{json,csv}`, `out/availability_v2_<stamp>.json`,
`out/feed_enriched_v2_latest.{json,csv}`. v1 files kept.
- RunPod: Secure and Community queried separately (`lowestPrice(secureCloud:true|false)`). Per-data-center rows come from
  `dataCenters.gpuAvailability`, which does not say the cloud type. They are labeled that way and never joined to a cloud tier.
- TensorDock dropped (feed marks it `stale`): 47 current rows.
- Vast: `availability_snapshot_price_usd` and `offer_count` come from the same collector snapshot (`availability_checked_at`).
  Feed price keeps its own `price_checked_at`.
- Join key: (vendor, gpu, vram_gb, RunPod cloud tier, region='all').
- `in_stock`: JSON true/false/null, CSV `true`/`false`/empty. `region`: `all` = aggregate row, country/DC id = per-region row, null = not known.
  Vast 0-offer models get offer_count 0, in_stock false, vram_gb null (no offers to read VRAM from).
- `stock_level` values seen from RunPod this run: `Low`, `null` (null → in_stock null). High/Medium are assumed to mean in stock but were not seen.

## v2.1 (Mart's minor items)
- `vram_gb` is never guessed. If a Vast model has 0 verified rentable offers, its `all` row has `vram_gb: null` with a `vram_note` saying why: no offers to read VRAM from, and no feed row to check it against. This run (15:08Z) Vast had H100 PCIe offers, so no null.
- **RunPod Community Cloud:** RunPod exposes it only some of the time. At 11:17 ET it showed A100 PCIe Low $1.19 and RTX 4090 Low $0.34. The collector records whatever the API returns. When the API returns null, the row is `in_stock: null` with the note "unknown: RunPod's public API returned no stock status ...".
- Refresh is labeled per field: `price_refresh` (`daily` for list prices, `4h` for marketplace/spot) and `availability_refresh` (`4h`). `refresh_rate` is gone.
- **Vast needs a live check from an unblocked network.** `console.vast.ai/api/v0/bundles` worked from this box, but it may block or rate-limit some networks and datacenter IPs. Before trusting a scheduled run, confirm it returns offers (`errors` empty, Vast row count > 0) from the host where cron will run.

## v2.2 (Verda collector + Gauge QA fixes 1–6)
- **Verda** (DataCrunch API, OAuth client_credentials; creds in `secrets/verda.env`, read at runtime, never written to output):
  `/instance-types` for 1-GPU H100 SXM / A100 SXM types (vram_gb = gpu_memory / number_of_gpus), and `/instance-availability?is_spot=false|true` for locations FIN-01/02/03.
  Rows: one per (model, vram, on-demand|spot) × (all + each location). `in_stock=false` means no location lists the type. offer_count is not exposed, so it's null. No RTX 4090 at Verda.
  Feed join: the vendor name "Verda (formerly DataCrunch)" is normalized to Verda. The key is (gpu, vram_gb, On-demand|Spot).
- Vast 0 at the feed's VRAM: if the model was queried without error but has no aggregate at that VRAM, the row gets `in_stock=false, offer_count=0`, the query's timestamp and URL, and a note.
- RunPod nulls (Secure tier and DC rows) say "unknown: RunPod's public API returned no stock status ...".
- Vast offers with no geolocation get `region: null` and are still counted in `all`.
- Any collector error exits 1, writes only the timestamped snapshot, and keeps the `*_latest` files. Enrich refuses a snapshot older than 8h.
- The feed is read from a fresh shallow clone, `feed-src/` (fetched and reset each run; scratch only, never pushed). The old `/workspace/agent-deals-feed/repo` checkout is not used.

## v2.3
- Null regions are skipped when sorting or listing regions, but still counted in `all` (fixes a TypeError). Test: `python3 test_v23.py`.
- Archive files are `out/availability_v2_<YYYYMMDDTHHMMSSZ>.json` (with seconds). A failed run writes `..._FAILED.json` and leaves `*_latest` untouched.
- Verda rows have `source: "authenticated vendor API (not publicly reproducible)"`. A sold-out result carries `observation: "authenticated observation: sold out ..."`; in the enriched feed it appears as `availability_source_type` / `availability_observation`. All other rows have `source: "public no-auth API"`.

## Ops notes (v2.3 follow-up)
- A broken snapshot is NOT auto-renamed: renaming a bad archive to `*_BROKEN.json` is a manual step today.
- `feed-src/` is a scratch clone that is `git reset --hard` on every run. Never keep anything else in it.

## v2.4 (Lambda + Clore.ai, 2026-10-29)
- **Lambda** (`collect_v2.lambda_`): read-only `GET https://cloud.lambda.ai/api/v1/instance-types`, basic auth `KEY:` from `secrets/lambda.env`
  (read at runtime, never output). No launch/mutating endpoint is ever called. Types mapped: 1x H100 SXM5, 1x H100 PCIe, 1x A100 SXM4 40GB,
  1x A100 PCIe 40GB, 8x H100 SXM5, 8x A100 80GB SXM4. VRAM is asserted from `gpu_description`. `in_stock` = `regions_with_capacity_available`
  non-empty; per-region rows only for regions with capacity. Source label `authenticated vendor API (not publicly reproducible)`; offer_count null.
  Join key adds GPU count from the tier ("(1x GPU)" / "(8x GPU)").
- **Clore.ai** (`collect_v2.clore`): public no-auth `GET https://api.clore.ai/v1/marketplace`. An unrented server (`rented == false`) is a rentable offer;
  `offer_count` = unrented servers (not GPUs). Exact names only: `A100SXM440GB`→A100 SXM 40, `GeForce RTX 4090` (24 GB; 4090 D/Laptop/23/48 GB hosts skipped),
  `H100 NVL` (94). Region = `specs.net.cc`. Price left null (feed keeps its own price).
- Join audit: Vast/RunPod/Verda keys all matched their feed rows; no VRAM/naming mismatch found, so no join change.
- Checked, no free signal: Hyperstack `/v1/core/stocks` needs an API key (401).
- Tests: `python3 test_v24.py` (runs test_v23 too; offline, fake key).

## v2.5 (Gauge QA on v2.4, 2026-10-29)
- **S1 Clore.ai:** Clore rows no longer emit `offer_count`. That name clashed with the feed's Clore `offer_count`, which counts USD-listed offers (for example, 109 for RTX 4090).
  Clore rows now carry `unrented_servers` (int). `in_stock = unrented_servers > 0`. The `availability_note` is always `unrented servers (one server may hold several GPUs), any currency`.
  A zero count or an unlisted model is explained in `observation`. Enrich never copies a Clore value into `offer_count`; it stays null there even if a snapshot row carries one. The value goes to the enriched `unrented_servers` column instead.
- **S2 live feed vs repo-only:** enrich reads the published `https://thelanternworks.com/api/v1/gpu-prices.json` (`rates`) with one public GET. Each row gets
  `in_live_feed` true/false, or null if the live feed can't be read. A row is matched on (vendor, gpu, vram_gb, tier). Stats split every count into `live_feed` / `repo_only` / `live_feed_unknown`
  and list `repo_only_rows`. These are rows in `data/gpu_pricing` that the site does not publish, e.g. Clore A100 SXM 40 and H100 NVL.
- `enrich_feed_v2.py` is now import-safe: `enrich(vendor_files, snap, live_keys)` is a pure function, and the git/network work runs only under `__main__`.
- Tests: `python3 test_v25.py` runs v2.4 and v2.3 too, all offline. It covers Clore `unrented_servers`, the enrich offer_count guard, the live/repo split, and the Vast zero-offer fallback:
  a queried model with no offers gets in_stock false and offer_count 0, and an errored run stays null. In test_v24, the Clore asserts were moved to `unrented_servers` / `observation`.

## v3.0 freshness, pruning, push safety
- `runpod_refreshed_at` (top level of `availability_v2_latest.json` and `feed_enriched_v2_latest.json`, and `meta.runpod_refreshed_at`) is set by the hourly RunPod refresh. When present and later than `collected_at`, it **takes precedence** for RunPod rows. All other vendors are as of `collected_at`. Each claim's own `checked_at` / `availability_expires_at` takes precedence over both. The enriched file also carries `snapshot_collected_at` and `stats.stats_recomputed_at`.
- The refresh re-reads RunPod only. Expired 1h region claims from other vendors (Vast, Verda, Oblivus) are dropped: their region rows, `available_regions_detail` entries, `available_regions` and `region_conflicts`. Stats, including `region_conflicts`, are then recomputed.
- Every push path (4h cycle, hourly refresh, `push_hook.sh --force`) runs `scout_io.py` first. It prunes expired region claims from both latest files and refuses with exit 3 if any expired `availability_expires_at` remains, such as an 8h overall row.
- The latest four files (snapshot and enriched, json and csv) are written to temp files and renamed only after all four are written. Collect stages its snapshot in `out/availability_v2_staged.json`, and enrich promotes the pair.
- `push_hook.sh` takes `out/.scout.lock` when run standalone. `run_cycle.sh` and `run_runpod_refresh.sh` hold the lock and export `SCOUT_LOCK_HELD=1`, so the hook does not re-lock.
- Second reads wait at least 60s after each source's own first read. The measured gaps are in `meta.second_read_gap_s`.

## v3.1
- Set `SCOUT_DIR` to run a sandbox copy; it defaults to the directory of the script (`scout/` in this repo; the work box used `/workspace/lantern-scout`). `run_cycle.sh` and `run_runpod_refresh.sh` export it to `push_hook.sh` and enrich (feed-src is resolved relative to it).
- `out/latest_manifest.json` holds `generation_id`, `written_at` and the sha256 of all four latest files. Both latest JSONs carry the same `generation_id`. `push_hook.sh` refuses (exit 3) unless all three match and the hashes agree. Ship the files as one matched set.
- RunPod: all first reads are done first, then each second read follows at least 60s after its own first read. Rows carry `second_read_gap_s`, and the meta has `runpod_second_read_gap_s`. This adds about 60s to a run.
- Verda spot region claims expire after 15 minutes; other region claims after 1h, and overall rows after 8h.
- push_hook keys on the last `== exit N` line in cron.log, so NOTE lines after it are ignored.

## v3.2
- Verda Spot claims expire after 15 minutes, both the overall row and the region rows.
- Overall rows with `derived_from_regions: true` (Verda, Oblivus) are recomputed whenever region claims are pruned (any push path or the RunPod refresh). `in_stock` is true only if a remaining unexpired region is in stock, otherwise null. The enriched feed is then re-joined from the pruned snapshot.
- push_hook needs an `== exit 0` after the latest `cycle start` / `runpod refresh start` line in cron.log.
- Vast (model, VRAM) groups below the feed's `MIN_MARKET_OFFERS` (read from feed-src `core/gpu.py`) carry `feed_status: held_below_min_offers`.
