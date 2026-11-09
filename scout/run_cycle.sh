#!/bin/bash
# Scout 4h cycle: collect + enrich + push hook.
# v3.0: holds out/.scout.lock (shared with run_runpod_refresh.sh) for the whole cycle, push included.
# v3.1: SCOUT_DIR defaults to this script's directory (repo scout/; the work box used /workspace/lantern-scout).
export SCOUT_DIR="${SCOUT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
cd "$SCOUT_DIR" || exit 1
exec 9>out/.scout.lock; export SCOUT_LOCK_HELD=1  # push_hook.sh then skips its own flock
flock -w 1800 9 || { echo "== skip lock busy $(date -u +%FT%TZ) cycle: >30min, skipped (exit 75; not an exit line)" >> out/cron.log; exit 75; }
rm -f out/.*.tmp* out/availability_v2_staged.json
{ echo "== $(date -u +%FT%TZ) cycle start"; python3 collect_v2.py && python3 enrich_feed_v2.py; rc=$?; rm -f out/.*.tmp* out/availability_v2_staged.json; echo "== exit $rc"; } >> out/cron.log 2>&1
# STAGED wider-gpu hook (not applied): runs after collect+enrich succeeded, under the same lock, before push. Non-fatal: its exit code
# never changes the cycle rc, and it logs a NOTE line (push_hook keys on the last "== exit N" line, so NOTE lines are ignored).
if [ "$rc" = "0" ] && [ -f ./wider_gpu.py ]; then { timeout -k 10 "${WGPU_TIMEOUT:-300}" python3 wider_gpu.py; wrc=$?; [ "$wrc" = "0" ] || { [ -e out/wider_gpu_prices_latest.json ] && mv -f out/wider_gpu_prices_latest.json "out/wider_gpu_prices_REJECTED_$(date -u +%Y%m%dT%H%M%SZ)-$$-${RANDOM}.json"; }; echo "NOTE wider-gpu rc=$wrc $(date -u +%FT%TZ)"; } >> out/cron.log 2>&1; fi  # rev 4: failed/killed run -> file moved aside
[ "$rc" = "0" ] || { [ -e out/wider_gpu_prices_latest.json ] && mv -f out/wider_gpu_prices_latest.json "out/wider_gpu_prices_REJECTED_$(date -u +%Y%m%dT%H%M%SZ)-$$-${RANDOM}.json"; echo "NOTE wider-gpu skipped: cycle rc=$rc" >> out/cron.log; }
[ "$rc" = "0" ] && { timeout 120 python3 t112_build.py out/.t112.tmp && mv -f out/.t112.tmp out/t112_availability_rate_7d.json || { rm -f out/.t112.tmp; echo "NOTE t112 build failed (non-fatal)"; }; } >> out/cron.log 2>&1  # T112
[ "$rc" = "0" ] && [ -x ./push_hook.sh ] && ./push_hook.sh >> out/cron.log 2>&1  # v3.3: gate on this cycle's own exit code
exit ${rc:-1}
