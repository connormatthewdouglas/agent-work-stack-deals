#!/usr/bin/env python3
"""GPU refresh freshness: warn when the daily refresh looks late, fail when it is clearly missed.

The last refresh time is the oldest successful `checked_at` among records the refresh job re-verified.
A later `last_failed_check_at` means that row was not re-verified and is skipped (the failed attempt
does not count, and its previous `checked_at` does not make the whole run look stale). Vendor-level
holds and manual snapshots are skipped. If no auto-refresh record was successfully re-verified, the gate fails.
The latest dated snapshot in data/gpu_pricing/snapshots/ is reported too. The fail bar stays 26 h.
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
from core.owner_hold import is_held  # noqa: E402


def _parse_stamp(raw: str) -> datetime:
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _successfully_reverified(r: dict) -> bool:
    """True when checked_at is the last attempt. A later last_failed_check_at is not a successful re-read."""
    ca = r.get("checked_at")
    if not ca:
        return False
    fa = r.get("last_failed_check_at")
    if not fa:
        return True
    try:
        return _parse_stamp(str(fa)) < _parse_stamp(str(ca))
    except ValueError:
        return True


def successful_refresh_stamps(docs: list[dict] | None = None) -> list[datetime]:
    """Successful re-verification only. A failed attempt writes last_failed_check_at and must not
    make the gate look fresh, and its previous checked_at must not make a later successful run look missed.
    Vendor-level holds, owner holds, and manual snapshots are not auto-refreshed; row-level holds are not re-stamped.
    Owner-held vendors are frozen on purpose (same as a stale hold): their old checked_at must not fail this gate."""
    stamps = []
    for d in docs if docs is not None else load_vendor_files():
        if d.get("stale") or d.get("manual_snapshot") or is_held(d.get("vendor")):
            continue
        for r in d.get("records") or []:
            if r.get("stale") or is_held(r.get("vendor")) or not _successfully_reverified(r):
                continue
            stamps.append(_parse_stamp(str(r["checked_at"])))
    return stamps


def status(now: datetime, fail_hours: float = 26.0) -> tuple[int, list[str]]:
    stamps = successful_refresh_stamps()
    snaps = sorted(p.stem for p in Path(SNAPSHOT_DIR).glob("????-??-??.json"))
    latest = snaps[-1] if snaps else None
    if not stamps:
        return 1, [f"last GPU refresh none (no successfully re-verified auto-refresh record); latest snapshot {latest}",
                   f"FAIL: last GPU refresh is older than {fail_hours:g} h (scheduled run missed)"]
    last = min(stamps)
    age_h = (now - last).total_seconds() / 3600
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
