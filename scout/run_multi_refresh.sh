#!/bin/bash
# v3.3 STAGED (not on the live routine path): multi-source fast refresh = RunPod + Oblivus + Verda + Lambda region claims.
# Same lock/temp/push protocol as run_runpod_refresh.sh. The log marker ends in "runpod refresh start" so push_hook.sh's
# start/exit pairing still applies. NO_PUSH=1 skips push_hook.sh. Hard timeout (default 15 min) keeps it inside the 20-min slot.
export SCOUT_DIR="${SCOUT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
cd "$SCOUT_DIR" || exit 1
exec 9>out/.scout.lock; export SCOUT_LOCK_HELD=1
if ! flock -w "${LOCK_WAIT:-900}" 9; then echo "== skip lock busy $(date -u +%FT%TZ) multi-source runpod refresh: >${LOCK_WAIT:-900}s, skipped (exit 75; not an exit line)" >> out/cron.log; exit 75; fi
rm -f out/.*.tmp*
{ echo "== $(date -u +%FT%TZ) multi-source runpod refresh start"; timeout "${MULTI_TIMEOUT:-900}" python3 refresh_multi.py; rc=$?; rm -f out/.*.tmp*; echo "== exit $rc"; } >> out/cron.log 2>&1
# v3.3: rc is this run's own exit code (a concurrent run may have appended lines to cron.log)
[ "$rc" = "0" ] && { timeout 120 python3 t112_build.py out/.t112.tmp && mv -f out/.t112.tmp out/t112_availability_rate_7d.json || { rm -f out/.t112.tmp; echo "NOTE t112 build failed (non-fatal)"; }; } >> out/cron.log 2>&1  # T112
if [ "$rc" = "0" ] && [ "${NO_PUSH:-0}" != "1" ] && [ -x ./push_hook.sh ]; then ./push_hook.sh >> out/cron.log 2>&1; fi
exit ${rc:-1}
