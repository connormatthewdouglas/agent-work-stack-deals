#!/bin/sh
# Pre-merge: import the LATEST scout-data snapshot into a throwaway worktree of HEAD, rebuild, and run the full
# test suite there, so a change in Scout's data or note text fails CI before the live import does (v34, 2026-10-30).
# Usage: sh scripts/check_latest_scout_import.sh   (needs: git fetch access to origin scout-data; python deps installed)
set -eu
ROOT=$(git rev-parse --show-toplevel)
W=$(mktemp -d)/wt
T=$(mktemp -d)
trap 'git -C "$ROOT" worktree remove --force "$W" >/dev/null 2>&1 || true; rm -rf "$T"' EXIT
git -C "$ROOT" fetch -q origin scout-data
git -C "$ROOT" worktree add -q --detach "$W" HEAD
for f in feed_enriched_v2_latest availability_v2_latest; do
  git -C "$ROOT" show "origin/scout-data:latest/$f.json" > "$T/$f.json"
done
git -C "$ROOT" show origin/scout-data:latest/manifest.json > "$T/manifest.json" 2>/dev/null || : > "$T/manifest.json"
git -C "$ROOT" show origin/scout-data:latest/latest_manifest.json > "$T/latest_manifest.json" 2>/dev/null || : > "$T/latest_manifest.json"
echo "scout-data $(git -C "$ROOT" rev-parse --short origin/scout-data): $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("generation_id"))' "$T/manifest.json" 2>/dev/null || echo '?')"
cd "$W"
LW_SCOUT_MANIFESTS="$T/manifest.json:$T/latest_manifest.json" LW_SCOUT_AVAIL="$T/availability_v2_latest.json" \
  python3 scripts/import_scout_availability.py "$T/feed_enriched_v2_latest.json"
python3 scripts/generate_seo_pages.py > /dev/null
python3 scripts/gpu_index.py . api/v1 > /dev/null
python3 scripts/generate_seo_pages.py > /dev/null
if ! git diff --quiet -- deals.json api/v1/deals.json; then echo "deals.json changed during an availability rebuild"; exit 1; fi
# the index pins the commit that last changed gpu-prices.json; in a throwaway tree that is "uncommitted": commit locally
git -c user.name=ci -c user.email=ci@localhost commit -qam "ci: latest scout snapshot (throwaway)" || true
python3 scripts/gpu_index.py . api/v1 > /dev/null && python3 scripts/generate_seo_pages.py > /dev/null
LANTERN_DEALS_FILE=api/v1/deals.json python3 -m pytest -q tests
echo LATEST_SCOUT_IMPORT_OK
