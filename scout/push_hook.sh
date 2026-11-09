#!/bin/bash
# v3.0 push hook. Every path (4h cycle, hourly RunPod refresh, --force):
#  - holds out/.scout.lock; callers that already hold it (run_cycle.sh, run_runpod_refresh.sh) export SCOUT_LOCK_HELD=1 so we
#    don't re-lock (a second flock on a new fd from a child would deadlock against the parent).
#  - v3.1: verifies both latest files + out/latest_manifest.json share one generation_id and the manifest hashes (else exit 3).
#  - prunes expired region claims from both latest files (scout_io.py prepush, atomic rewrite, stats recomputed) and refuses
#    (exit 3) if any expired availability_expires_at remains (e.g. an 8h overall row). --force never overrides this.
SCOUT="${SCOUT_DIR:-$(cd "$(dirname "$0")" && pwd)}"; SCOUT_OUT="${SCOUT_OUT:-$SCOUT/out}"
if [ "${SCOUT_LOCK_HELD:-0}" != "1" ]; then
  exec 9>"$SCOUT_OUT/.scout.lock"
  flock -w "${LOCK_WAIT:-900}" 9 || { echo "skip push: $SCOUT_OUT/.scout.lock busy >${LOCK_WAIT:-900}s"; exit 75; }
fi
# only push if the last collect+enrich/refresh succeeded (checked before prepush writes anything to the log)
# v3.1: key on the last '== exit N' line (NOTE lines may follow it), not the last line
# v3.2: the latest '== ... cycle start' / '== ... runpod refresh start' must be followed by an '== exit N' line (else that run was
# killed or is still running, and an older 'exit 0' must not count); N is taken from the first '== exit' after that start.
LAST_EXIT=$(awk '/^== .*(cycle start|runpod refresh start)$/ {st=NR; ex=""} /^== exit / {if (st && ex=="") ex=$3; if (!st) pre=$3} END {if (st) print (ex==""?"none":ex); else print (pre==""?"none":pre)}' "$SCOUT_OUT/cron.log" 2>/dev/null)
[ "$LAST_EXIT" = "none" ] && [ "$1" != "--force" ] && { echo "skip push: latest run start in cron.log has no '== exit' after it (killed or still running)"; exit 1; }
[ "$LAST_EXIT" = "0" ] || [ "$1" = "--force" ] || { echo "skip push: last cycle not ok"; exit 1; }
( cd "$SCOUT" && python3 scout_io.py "$SCOUT_OUT" ) || exit 3
[ "${PUSH_DRY_RUN:-0}" = "1" ] && { echo "dry run: would push"; exit 0; }
# Publisher is this repo's scripts/push_scout_snapshot.sh. The work box fetched origin/main into
# bin/push_scout_snapshot.sh and sed-inserted t112_availability_rate_7d.json after RUN_LOG.txt.
# That file is not kept here. The canonical script already lists it; the same sed still runs on a
# temp copy so the file is published even when the name sits on only one side of RUN_LOG.txt.
# The tracked script is never modified.
PUSH_SRC="$(cd "$(dirname "$0")/.." && pwd)/scripts/push_scout_snapshot.sh"
[ -f "$PUSH_SRC" ] || { echo "missing push script $PUSH_SRC" >&2; exit 2; }
PUSH_BIN="$(mktemp)"
cp "$PUSH_SRC" "$PUSH_BIN"
sed -i "s/RUN_LOG.txt; do/RUN_LOG.txt t112_availability_rate_7d.json; do/" "$PUSH_BIN"
bash "$PUSH_BIN" "$SCOUT_OUT"
rm -f "$PUSH_BIN"
