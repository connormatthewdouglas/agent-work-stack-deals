#!/bin/sh
# Open (or comment on) ONE open GitHub issue per pipeline when a run on main fails, so failures are loud.
# Usage: sh scripts/pipeline_issue.sh "<pipeline name>"   env: GH_TOKEN, GH_REPO, RUN_URL, optional NEEDS (toJSON(needs)), DETAIL
set -eu
name="$1"
title="Pipeline failing: $name"
if [ "${2:-}" = "--green" ]; then  # close the open issue for this pipeline on the next green run
  for n in $(gh issue list --label pipeline-failure --state open --json number,title -q ".[] | select(.title == \"$title\") | .number"); do
    gh issue close "$n" --comment "$(date -u +%Y-%m-%dT%H:%M:%SZ): green run, closing. Run: $RUN_URL"
  done
  exit 0
fi
failed=""
if [ -n "${NEEDS:-}" ]; then
  failed=$(printf '%s' "$NEEDS" | python3 -c 'import json,sys;print(", ".join(k for k,v in json.load(sys.stdin).items() if v.get("result")=="failure" or (v.get("outputs") or {}).get("ok")=="false"))')
fi
body="$(date -u +%Y-%m-%dT%H:%M:%SZ): $name failed${failed:+ (jobs: $failed)}. ${DETAIL:-}
Run: $RUN_URL
This issue stays open (new failures comment here) and closes itself on the next green run. Runs no longer go red (no per-run email); this issue is the failure signal."
gh label create pipeline-failure --color B60205 --description "A main-branch pipeline run failed" 2>/dev/null || true
n=$(gh issue list --label pipeline-failure --state open --search "in:title \"$title\"" --json number,title -q ".[] | select(.title == \"$title\") | .number" | head -1)
if [ -n "$n" ]; then gh issue comment "$n" --body "$body"; else gh issue create --title "$title" --label pipeline-failure --body "$body"; fi
