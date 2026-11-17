# Price history backup and restore

**What:** `.github/workflows/price-history-backup.yml` runs daily at 06:37 UTC and on manual dispatch. It packs:
- `data/gpu_pricing/**`: vendor records plus the dated `snapshots/YYYY-MM-DD.json`
- `api/v1/gpu-prices.json` and `api/v1/gpu-prices/history.json`
- availability and feed-state files
- `scout-data:latest/*`

It writes everything into `lw-price-history-<UTC>.tar.gz` with a sha256 manifest, uploaded as the Actions
artifact `price-history-<run-id>` and kept for 90 days.

**D1:** the price history does not live in D1. The hosted stats and watch databases and the telemetry DB are
exported as well, gpg-encrypted, but only when the repo secrets `CLOUDFLARE_API_TOKEN` (D1 read/export on the
account), `CLOUDFLARE_ACCOUNT_ID`, and `BACKUP_PASSPHRASE` exist. Without them the job backs up the data files
only and posts a notice. Adding the secrets is a Bjorn/Frosty step.

**Tested restore:** the `restore-test` job restores the artifact just made into a scratch sqlite. A run fails when:
- the manifest schema is not `lantern-works-price-history-backup/1`;
- any fixed file (feed, history, feed state) is missing;
- any count is 0, or the snapshot file count, rows, newest snapshot or history series differ from the manifest;
- the newest snapshot is more than 2 days older than the backup;
- any restored repo file is missing or differs from the backup's commit (`--require-git`: compared with
  `git show <manifest.commit>:<path>` by blob id).

D1 dumps are also loaded. The freshness watchdog flags a last successful backup older than 30h.

**Restore by hand:**
```sh
gh run list -w price-history-backup.yml -s success -L 1          # pick the run id
gh run download <run-id> -n price-history-<run-id> -D /tmp/bk
python3 scripts/restore_price_history.py /tmp/bk --verify            # proof only
python3 scripts/restore_price_history.py /tmp/bk --into /path/to/fresh-worktree   # then review + PR (Mart merges)
```
For D1, restore into a local or scratch database first with `wrangler d1 execute <db> --local --file <dump>.sql`.
Writing to the production D1 (`--remote`) is a human decision.
