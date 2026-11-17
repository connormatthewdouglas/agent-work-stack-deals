# Contributing (Lantern Works bots and humans)

## Only Mart touches `main`

- Work on a branch and open a pull request. Never `git push` to `main`, never force-push it, never delete it.
- **Mart** is the only bot that merges pull requests into `main` (`gh pr merge`), and only on green `ci-status`.
  Every other bot (Scout, Core, Relay, Atrium, ...) pushes branches and opens PRs, then hands the PR to Mart.
- Bjorn or Frosty may merge or override when Mart is unavailable.
- Exception: the scheduled data workflows (`gpu-refresh`, `scout-import`, `lium-collect`) commit data to `main`
  as `github-actions[bot]`. Do not copy that pattern into bot sessions.
- All bots share one GitHub account, so GitHub cannot tell Mart from another bot. This rule is enforced by
  process. The branch-protection draft (block force-push and deletion, require a PR, require `ci-status`) is
  applied by Bjorn or Frosty, never by a bot.

## What blocks a merge

`ci-status` in *Validate feed and deploy Pages* is the one required check. It fails on real code, test,
schema, or release-gate failures.

Stale data does **not** block a PR or a merge (sturdiness pass, 2026-11-17):

- `latest-scout-import`: a Scout snapshot older than the import's 8h bar is skipped with a warning.
  Manifest, version, and test failures still fail.
- release gate T41-12: a checkout feed older than 36h is a warning. `feed_updated_at` < newest `verified_at`
  still fails.
- `tests`: pytest runs at the committed feed's own clock (`LW_AVAIL_NOW` = `feed_updated_at`), so wall-clock
  data age never fails a test.

On `main`, those warnings go to the open **freshness-watchdog** issue (deduped). The scheduled
`freshness-watchdog.yml` keeps the live bars (26h feed, 4h availability, 48h rows, collector runs, hosted build).
That issue is the place to see stale data.
