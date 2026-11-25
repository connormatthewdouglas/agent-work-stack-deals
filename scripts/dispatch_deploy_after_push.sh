#!/bin/sh
# After a GITHUB_TOKEN push to main, wait until the API shows that SHA, then
# dispatch validate-and-deploy.yml --ref main. Token pushes do not fire on: push,
# so a bare dispatch can resolve the previous SHA (2026-11-25 scout-import:
# pushed 604562fc8, run 45619454895 started on 030301b589).
#
# Usage: sh scripts/dispatch_deploy_after_push.sh <full-pushed-sha>
# Env: GH_TOKEN (or GITHUB_TOKEN), GH_REPO or GITHUB_REPOSITORY.
# Optional: LW_DISPATCH_WAIT_SECONDS (default 120), LW_DISPATCH_POLL_SECONDS (2),
# LW_DISPATCH_RUN_WAIT_SECONDS (30), LW_DISPATCH_MAX_REDISPATCH (2).
# The token is never printed or passed on a command line.
set -eu

SHA=${1:-}
REPO=${GH_REPO:-${GITHUB_REPOSITORY:-}}
WAIT=${LW_DISPATCH_WAIT_SECONDS:-120}
POLL=${LW_DISPATCH_POLL_SECONDS:-2}
RUN_WAIT=${LW_DISPATCH_RUN_WAIT_SECONDS:-30}
MAX_REDISPATCH=${LW_DISPATCH_MAX_REDISPATCH:-2}

case "$SHA" in
  *[!0-9a-fA-F]*|'') SHA='' ;;
esac
if [ "${#SHA}" -ne 40 ]; then
  echo "dispatch_deploy_after_push: need the full 40-character pushed SHA" >&2
  exit 2
fi
if [ -z "$REPO" ]; then
  echo "dispatch_deploy_after_push: GH_REPO or GITHUB_REPOSITORY is required" >&2
  exit 2
fi
for n in "$WAIT" "$POLL" "$RUN_WAIT" "$MAX_REDISPATCH"; do
  case "$n" in
    *[!0-9]*)
      echo "dispatch_deploy_after_push: wait/poll/redispatch values must be integers" >&2
      exit 2
      ;;
  esac
done

# GET /repos/{owner}/{repo}/commits/main → .sha  (via gh api; token stays in the env)
main_sha() {
  gh api "repos/${REPO}/commits/main" --jq .sha
}

wait_for_main() {
  start=$(date +%s)
  observed=""
  while :; do
    if observed=$(main_sha); then
      if [ "$observed" = "$SHA" ]; then
        echo "dispatch_deploy_after_push: main is at ${SHA}"
        return 0
      fi
    else
      observed="unreadable"
    fi
    now=$(date +%s)
    if [ $((now - start)) -ge "$WAIT" ]; then
      echo "dispatch_deploy_after_push: timed out after ${WAIT}s waiting for main to reach ${SHA}; last seen ${observed}" >&2
      exit 1
    fi
    sleep "$POLL"
  done
}

list_runs() {
  gh run list --workflow=validate-and-deploy.yml --event workflow_dispatch --branch main \
    --json databaseId,headSha,status,event --limit 10
}

# Prints "id sha" of the first run whose databaseId is not in $1 (space-separated).
new_run_from_list() {
  KNOWN_IDS=$1 list_runs | python3 -c '
import json, os, sys
known = set(os.environ.get("KNOWN_IDS", "").split())
for row in json.load(sys.stdin):
    rid = str(row.get("databaseId") or "")
    if rid and rid not in known:
        print(rid, row.get("headSha") or "")
        break
'
}

wait_for_new_run() {
  start=$(date +%s)
  while :; do
    found=$(new_run_from_list "$1") || found=""
    if [ -n "${found:-}" ]; then
      printf '%s\n' "$found"
      return 0
    fi
    now=$(date +%s)
    if [ $((now - start)) -ge "$RUN_WAIT" ]; then
      echo "dispatch_deploy_after_push: timed out after ${RUN_WAIT}s waiting for the dispatched run to appear" >&2
      exit 1
    fi
    sleep "$POLL"
  done
}

wait_for_main

known=$(list_runs | python3 -c 'import json,sys; print(" ".join(str(r.get("databaseId") or "") for r in json.load(sys.stdin) if r.get("databaseId")))') || known=""
attempts=0
max_attempts=$((MAX_REDISPATCH + 1))
while [ "$attempts" -lt "$max_attempts" ]; do
  attempts=$((attempts + 1))
  echo "dispatch_deploy_after_push: dispatching validate-and-deploy.yml --ref main (want ${SHA}, attempt ${attempts}/${max_attempts})"
  gh workflow run validate-and-deploy.yml --ref main
  result=$(wait_for_new_run "$known")
  run_id=${result%% *}
  run_sha=${result#* }
  if [ "$run_sha" = "$SHA" ]; then
    echo "dispatch_deploy_after_push: run ${run_id} is on ${SHA}"
    exit 0
  fi
  echo "dispatch_deploy_after_push: run ${run_id} is on stale head ${run_sha}, wanted ${SHA}" >&2
  if [ "$attempts" -ge "$max_attempts" ]; then
    echo "dispatch_deploy_after_push: gave up after ${attempts} dispatch(es); last run ${run_id} was stale" >&2
    exit 1
  fi
  # A later dispatch on the same concurrency group cancels the stale run.
  echo "dispatch_deploy_after_push: re-dispatching (concurrency cancel-in-progress drops the stale run)"
  known="${known} ${run_id}"
  sleep "$POLL"
done
