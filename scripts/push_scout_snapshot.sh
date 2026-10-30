#!/usr/bin/env bash
# Publish a Lantern Scout snapshot to the orphan branch scout-data, at latest/.
# Usage: scripts/push_scout_snapshot.sh <scout out dir>
# Copies (never moves or edits) availability_v2_latest.json and feed_enriched_v2_latest.json, plus their CSVs and
# RUN_LOG.txt if present, and writes latest/manifest.json (snapshot time, sha256, pushed_at). Uses the caller's
# existing git/gh auth. Prints no tokens or remote URLs. Exits 0 without a commit if nothing changed.
set -euo pipefail
OUT="${1:?usage: push_scout_snapshot.sh <scout out dir>}"
REPO_URL="https://github.com/connormatthewdouglas/agent-work-stack-deals.git"
for f in availability_v2_latest.json feed_enriched_v2_latest.json; do
  [ -s "$OUT/$f" ] || { echo "missing $f in the out dir" >&2; exit 2; }
done
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
git -c credential.helper= -c credential.helper='!gh auth git-credential' clone -q --depth 1 --branch scout-data "$REPO_URL" "$W/r" 2>/dev/null \
  || { echo "could not clone scout-data (check gh auth status)" >&2; exit 3; }
mkdir -p "$W/r/latest"
for f in availability_v2_latest.json feed_enriched_v2_latest.json availability_v2_latest.csv feed_enriched_v2_latest.csv RUN_LOG.txt; do
  [ -f "$OUT/$f" ] && cp "$OUT/$f" "$W/r/latest/$f"
done
python3 - "$W/r/latest" <<'PY'
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
d = Path(sys.argv[1])
feed = json.loads((d / "feed_enriched_v2_latest.json").read_text())
raw = json.loads((d / "availability_v2_latest.json").read_text())
times = [r.get("availability_checked_at") for r in feed.get("rows") or [] if r.get("availability_checked_at")]
m = {"schema": "lantern-scout-snapshot-manifest/1", "feed_version": str(feed.get("version")),
     "collected_at": raw.get("collected_at") or (max(times) if times else None),
     "max_availability_checked_at": max(times) if times else None,
     "rows": len(feed.get("rows") or []), "in_live_feed_rows": sum(1 for r in feed.get("rows") or [] if r.get("in_live_feed")),
     "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir()) if p.name != "manifest.json"}}
old = d / "manifest.json"
if old.exists() and {k: v for k, v in json.loads(old.read_text()).items() if k != "pushed_at"} == m:
    sys.exit(0)  # unchanged: keep the old pushed_at so git sees no diff
m["pushed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
old.write_text(json.dumps(m, indent=1) + "\n")
PY
cd "$W/r"
git add -A latest
if git diff --cached --quiet; then echo "scout-data: no change"; exit 0; fi
git \
  commit -qm "scout snapshot $(python3 -c 'import json;print(json.load(open("latest/manifest.json"))["collected_at"])')"
git -c credential.helper= -c credential.helper='!gh auth git-credential' push -q origin scout-data 2>/dev/null \
  || { echo "push to scout-data failed (check gh auth status)" >&2; exit 4; }
echo "scout-data: pushed $(git rev-parse --short HEAD)"
