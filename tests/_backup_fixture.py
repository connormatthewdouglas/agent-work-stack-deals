"""Fixed price-history repo for the backup/restore tests (Relay 2026-11-17, Bjorn: never time of day or live data).

The tests used to back up the live checkout, so they broke whenever a collector rewrote data/ before pytest ran
(scout-import, gpu-refresh, lium-collect) and their snapshot-lag checks moved with the calendar. This builds a
small committed git repo with fixed snapshots and a fixed clock instead; the same backup and restore code runs on it.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
SNAP_DATES = [(date(2026, 11, 8) + timedelta(days=i)).isoformat() for i in range(10)]  # 11-08 .. 11-17


def _w(root: Path, rel: str, obj) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def make_repo(base: Path) -> Path:
    """A committed, clean repo under base/repo with every file the backup carries."""
    root = base / "repo"
    rows = [{"advertiser": "AWS", "gpu": "H100", "tier": "On-demand", "price_usd": 6.88},
            {"advertiser": "Lambda", "gpu": "B200", "tier": "On-demand", "price_usd": 7.99}]
    _w(root, "api/v1/gpu-prices.json", {"feed_updated_at": "2026-11-17T06:00:00Z", "rates": rows})
    _w(root, "api/v1/gpu-prices/history.json", {
        "last_snapshot": SNAP_DATES[-1], "changes": [{"rate_id": "aws-h100", "date": SNAP_DATES[3]}],
        "series": [{"rate_id": "aws-h100", "points": [[d, 6.88] for d in SNAP_DATES]},
                   {"rate_id": "lambda-b200", "points": [[SNAP_DATES[-1], 7.99]]}]})
    for rel in ("data/feed_state.json", "data/owner_hold.json", "data/price_confirmations.json"):
        _w(root, rel, {"fixture": True})
    _w(root, "data/gpu_pricing/aws.json", {"vendor": "AWS", "records": [rows[0]]})
    _w(root, "data/gpu_pricing/lambda.json", {"vendor": "Lambda", "records": [rows[1]]})
    _w(root, "data/gpu_availability/latest.json", {"checked_at": "2026-11-17T06:00:00Z", "rows": []})
    for d in SNAP_DATES:
        _w(root, f"data/gpu_pricing/snapshots/{d}.json", {"schema": "lantern-works-gpu-snapshot/1", "date": d, "rows": rows})
    env = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
           "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
           "GIT_AUTHOR_DATE": "2026-11-17T06:00:00Z", "GIT_COMMITTER_DATE": "2026-11-17T06:00:00Z",
           "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(base)}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "fixture"]):
        subprocess.run(cmd, cwd=root, env=env, check=True, stdout=subprocess.DEVNULL)
    return root


def snaps(root: Path) -> list[Path]:
    return sorted((root / "data/gpu_pricing/snapshots").glob("*.json"))
