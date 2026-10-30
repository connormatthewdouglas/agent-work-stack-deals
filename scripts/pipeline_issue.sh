#!/bin/sh
# Open (or comment on) ONE open GitHub issue per pipeline when a run on main fails, so failures are loud.
# Usage: sh scripts/pipeline_issue.sh "<pipeline name>"   env: GH_TOKEN, GH_REPO, RUN_URL, optional NEEDS (toJSON(needs)), DETAIL
set -eu
name="$1"
failed=""
if [ -n "${NEEDS:-}" ]; then
  failed=$(printf '%s' "$NEEDS" | python3 -c 'import json,sys;print(", ".join(k for k,v in json.load(sys.stdin).items() if v.get("result")=="failure"))')
fi
title="Pipeline failing: $name"
body="$(date -u +%Y-%m-%dT%H:%M:%SZ): $name failed${failed:+ (jobs: $failed)}. ${DETAIL:-}
Run: $RUN_URL
This issue stays open (new failures comment here) until someone closes it after a green run."
gh label create pipeline-failure --color B60205 --description "A main-branch pipeline run failed" 2>/dev/null || true
n=$(gh issue list --label pipeline-failure --state open --search "in:title \"$title\"" --json number,title -q ".[] | select(.title == \"$title\") | .number" | head -1)
if [ -n "$n" ]; then gh issue comment "$n" --body "$body"; else gh issue create --title "$title" --label pipeline-failure --body "$body"; fi
