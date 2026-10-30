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
2. **Import.** `.github/workflows/scout-import.yml` runs every 4 hours at 00:15, 04:15, 08:15, 12:15, 16:15 and 20:15 UTC, and can also be started by hand.
   - **What it imports:** it reads `scout-data:latest/feed_enriched_v2_latest.json` and runs `scripts/import_scout_availability.py`. Only `in_live_feed` rows are imported.
   - **Stale snapshots:** a snapshot older than 8 hours is refused. The current data stays, the refusal is noted in the run summary, and the run ends green with nothing deployed.
   - **On a new snapshot:** it regenerates the pages and the GPU index and runs the tests. It commits only if something changed, then dispatches the gated Pages deploy.
   - **deals.json:** it never changes deals.json. If deals.json would change, it stops without publishing, which keeps the public gist in lockstep.
   - **Timing:** it shares the `gpu-refresh` concurrency group, so it never runs at the same time as the daily price refresh at 10:23 UTC.
3. **Expiry.** Any stock claim older than 8 hours shows as "unknown (stale availability, last checked …)". This applies on the site, in `compare_gpu_prices`, and in the reader's browser (see CHANGELOG 0.3.30). If Scout stops publishing, claims expire instead of going stale silently.
