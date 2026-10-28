#!/usr/bin/env python3
"""GPU refresh freshness: warn when the daily refresh looks late, fail when it is clearly missed.

The last refresh time is the oldest `checked_at` among records the refresh job touches (it stamps every
record it reads, parsed or not; vendor-level holds are skipped). The latest dated snapshot in data/gpu_pricing/snapshots/ is reported too.
  * WARN  (exit 0, GitHub ::warning::) if there is no snapshot for today (UTC) or the last refresh is > 24 h old.
  * FAIL  (exit 1) if the last refresh is more than --fail-hours (default 26) old.
GitHub cron is best-effort (runs can be hours late or dropped), so gpu-refresh.yml has a primary and a
fallback slot; this check is the backstop that makes a missed day visible.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.gpu import load_vendor_files  # noqa: E402
from core.gpu_history import SNAPSHOT_DIR  # noqa: E402


def status(now: datetime, fail_hours: float = 26.0) -> tuple[int, list[str]]:
    # Oldest checked_at among records the refresh touches (vendor-level holds are skipped). The refresh stamps
    # every such record, readable or not, so a hand-added vendor with a fresh stamp can't mask a missed run.
    stamps = [datetime.fromisoformat(r["checked_at"]) for d in load_vendor_files() if not d.get("stale") for r in d["records"]]
    last = min(stamps)
    age_h = (now - last).total_seconds() / 3600
    snaps = sorted(p.stem for p in Path(SNAPSHOT_DIR).glob("????-??-??.json"))
    latest = snaps[-1] if snaps else None
    msgs = [f"last GPU refresh {last.isoformat()} ({age_h:.1f} h ago); latest snapshot {latest}"]
    if age_h > fail_hours:
        return 1, msgs + [f"FAIL: last GPU refresh is older than {fail_hours:g} h (scheduled run missed)"]
    warn = []
    if latest != now.date().isoformat():
        warn.append(f"no snapshot for {now.date().isoformat()} (UTC) yet")
    if age_h > 24:
        warn.append("last refresh is more than 24 h old")
    return 0, msgs + [f"::warning::GPU refresh late: {w}" for w in warn]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fail-hours", type=float, default=26.0)
    a = ap.parse_args()
    code, msgs = status(datetime.now(timezone.utc), a.fail_hours)
    print("\n".join(msgs))
    return code


if __name__ == "__main__":
    sys.exit(main())
