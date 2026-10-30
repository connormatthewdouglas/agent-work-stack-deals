# Scout availability data (scout-data branch)

GPU availability on the site comes from Lantern Scout snapshots. The pipeline runs entirely on GitHub's free tier.

1. **Publish.** After each collection, Scout runs this from a checkout of `main` on the machine that collects the data:

   ```sh
   scripts/push_scout_snapshot.sh <scout out dir>
   ```

   `<scout out dir>` is Scout's output directory. It must contain `availability_v2_latest.json` (raw) and `feed_enriched_v2_latest.json` (enriched).
   - **What it copies:** those two files, their `.csv` versions and `RUN_LOG.txt` (when present). They go to the orphan branch `scout-data` under `latest/`.
   - **Manifest:** it writes `latest/manifest.json`, which records `collected_at`, row counts, a sha256 for each file, and `pushed_at`.
   - **Source files:** it only copies, never moves or edits them.
   - **Auth:** it uses the machine's existing `gh` login and prints no credentials.
   - **Unchanged snapshot:** it exits 0 without a commit.
   - **History:** each snapshot is one commit on `scout-data`.
2. **Import and rebuild.** `.github/workflows/scout-import.yml` runs at :15 past every hour, with a cheap gate first. A run does the work only on a 4-hourly slot (00, 04, 08, 12, 16 or 20 UTC; 08:15 comes before the 10:23 UTC daily refresh), when scout-data has a snapshot not yet imported, when a published stock claim has passed `availability_expires_at`, or when started by hand.
   - **What it imports:** it reads `scout-data:latest/feed_enriched_v2_latest.json` and runs `scripts/import_scout_availability.py`. Only `in_live_feed` rows are imported.
   - **Stale snapshots:** a snapshot older than 8 hours is refused. The current data stays and the refusal is noted in the run summary.
   - **Rebuild:** pages and feeds are rebuilt either way, so expired claims flip to unknown. The tests run before anything is published.
   - **Expiry (Gauge re24, design (a)):** a build leaves out any claim that expires within 25 minutes (Scout's cadence plus deploy time). Every other claim is published with its real `availability_expires_at`.
     - Every Scout push rebuilds, even when no claim is renewed.
     - The `*/10` backstop also rebuilds once any published claim is within 20 minutes of expiry. So a fresh build normally replaces static output before any claim it holds expires (worst-case static staleness 0).
     - **Tradeoff:** a claim leaves the static pages and feeds up to 25 minutes before it truly expires.
     - **Residual risk:** a rebuild needs a Scout push or a GitHub cron run. If both stall for more than about 20 minutes, a static claim could outlive its expiry.
     - Two consumers stay correct even then: `compare_gpu_prices` / `estimate_job_cost` apply expiry at request time and are the source of truth, and the pages' script flips the claim to unknown in the browser. Feed consumers must enforce `availability_expires_at` themselves.
   - **Deploys never stack:** `validate-and-deploy` has one concurrency group per ref with cancel-in-progress, so the latest wins. Bot-only data commits skip the published-package jobs (pypi-install, docker); validate, tests and T41 still gate.
   - **Publishing:** it commits only if something changed, then dispatches the gated Pages deploy.
   - **deals.json:** it never changes deals.json. If deals.json would change, it stops without publishing, which keeps the public gist in lockstep.
   - **Timing:** it shares the `gpu-refresh` concurrency group with the daily price refresh. The refresh's 14:47 UTC fallback slot also rebuilds pages and feeds.
3. **Expiry.** A stock claim past its `availability_expires_at` shows as "unknown (stale availability, last checked …)". This applies on the site, in `compare_gpu_prices`, and in the reader's browser (see CHANGELOG 0.3.30). The limit is 1 hour for Lambda, Verda, region and region-derived claims, and 8 hours for marketplace overall claims (Vast, Clore). If Scout stops publishing, claims expire instead of going stale silently.

## Triggers (decided 2026-10-30)

- **Main path:** Scout's snapshot push dispatches `scout-import` ("Dispatch Scout import on snapshot push").
- **Backstop:** the GitHub Actions schedule in `scout-import.yml`, `*/10 * * * *`, gated. A scheduled run does work only on a 4-hourly slot (minute 10–24), a new Scout snapshot, or an expired claim; otherwise it exits cheaply. GitHub cron can be delayed or skipped under load, which is why it is only the backstop.
- **Parked:** the Cloudflare cron Worker `lantern-works-import-cron` (`cron-dispatch/`). Its cron trigger is removed and it has no token, so nothing depends on a user token. See `cron-dispatch/README.md` to revive it.
