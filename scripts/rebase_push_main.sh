#!/bin/sh
# Replay this job's commits onto origin/main, then push with the checkout GITHUB_TOKEN.
# Exit 0 when main accepted the commits. Exit 1 on a non-fast-forward push or a rebase
# conflict; the caller resets to origin/main and re-runs the collection. No PAT.
set -eu
git fetch -q origin main
if ! git merge-base --is-ancestor origin/main HEAD; then
  if ! git rebase origin/main; then
    git rebase --abort 2>/dev/null || true
    echo "rebase onto origin/main conflicted" >&2
    exit 1
  fi
fi
git push origin HEAD:main
