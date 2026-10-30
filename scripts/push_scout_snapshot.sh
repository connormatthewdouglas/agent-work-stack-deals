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
SCOUT_MSG_PY="$W/msg.py"
cat > "$SCOUT_MSG_PY" <<'PY'
import json, re, sys
from pathlib import Path
d = Path(sys.argv[1]); raw = json.loads((d / "availability_v2_latest.json").read_text())
gid = raw.get("generation_id")
m = re.match(r"^(\d{8}T\d{6}Z)-", gid or "")
at = (m.group(1)[:4] + "-" + m.group(1)[4:6] + "-" + m.group(1)[6:8] + "T" + m.group(1)[9:11] + ":" + m.group(1)[11:13] + ":" + m.group(1)[13:15] + "Z") if m else None
# unknown stays unknown: no generation_id -> say so, and keep collected_at only as a labeled fallback
print(f"scout snapshot {at} gen {gid}" if m else f"scout snapshot gen unknown (collected_at {raw.get('collected_at')})")
PY
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
import re
gid = raw.get("generation_id") or feed.get("generation_id")
gm = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z-", gid or "")
m = {"schema": "lantern-scout-snapshot-manifest/1", "feed_version": str(feed.get("version")),
     "generation_id": gid,  # this push's generation (20-min refresh); collected_at below is the 4 h cycle's time
     "generated_at": "{}-{}-{}T{}:{}:{}Z".format(*gm.groups()) if gm else None,
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
# v3.3 (Scout): commit message = this generation, not the 4h cycle's collected_at (which a 20-min refresh does not change)
git \
  commit -qm "$(python3 "$SCOUT_MSG_PY" latest)"
git -c credential.helper= -c credential.helper='!gh auth git-credential' push -q origin scout-data 2>/dev/null \
  || { echo "push to scout-data failed (check gh auth status)" >&2; exit 4; }
echo "scout-data: pushed $(git rev-parse --short HEAD)"
