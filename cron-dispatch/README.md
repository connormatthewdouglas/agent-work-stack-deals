# cron-dispatch (PARKED)

Parked on 2026-10-30 by Bjorn's decision. The Worker `lantern-works-import-cron` has no cron trigger (`crons = []`) and no token. Nothing depends on it.
The main path is Scout's snapshot push, which dispatches scout-import. The backstop is the gated GitHub Actions schedule in `.github/workflows/scout-import.yml`.
To revive it, a fine-grained PAT is needed: this repo only, Actions read/write. Add it with `npx wrangler secret put GH_DISPATCH_TOKEN`, restore `crons = ["*/10 * * * *"]`, and deploy.
