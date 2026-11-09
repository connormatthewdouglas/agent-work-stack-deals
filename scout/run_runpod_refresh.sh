#!/bin/bash
# v3.0 RunPod-only hourly refresh. Shares out/.scout.lock with run_cycle.sh (flock), so it never overlaps a 4h cycle.
# NO_PUSH=1 skips push_hook.sh (for tests). v3.1: SCOUT_DIR defaults to this script's directory (repo scout/; the work box used /workspace/lantern-scout).
export SCOUT_DIR="${SCOUT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
cd "$SCOUT_DIR" || exit 1
exec 9>out/.scout.lock; export SCOUT_LOCK_HELD=1  # push_hook.sh then skips its own flock
if ! flock -w "${LOCK_WAIT:-900}" 9; then echo "== skip lock busy $(date -u +%FT%TZ) runpod refresh: >${LOCK_WAIT:-900}s, skipped (exit 75; not an exit line)" >> out/cron.log; exit 75; fi
rm -f out/.*.tmp*
{ echo "== $(date -u +%FT%TZ) runpod refresh start"; python3 refresh_runpod.py; rc=$?; rm -f out/.*.tmp*; echo "== exit $rc"; } >> out/cron.log 2>&1
# v3.3: rc is this run's own exit code (a concurrent run may have appended lines to cron.log)
if [ "$rc" = "0" ] && [ "${NO_PUSH:-0}" != "1" ] && [ -x ./push_hook.sh ]; then ./push_hook.sh >> out/cron.log 2>&1; fi
exit ${rc:-1}
