#!/usr/bin/env python3
"""Gate pre-check for latest-scout-import (Gauge NO-GO B1 / Bjorn 2026-11-17: empty or zero-row = fail).

Missing data is not stale data. Exits 1 when the Scout snapshot:
  * has no rows,
  * has no parseable availability_checked_at on any row, or
  * has zero rows for a source (vendor) that has rows in the committed data/gpu_availability/latest.json
    (owner-held vendors excepted, since the importer drops them anyway).
Exit 0 means the snapshot has data; whether it is too OLD is the importer's 8h check, which only warns in CI.
Usage: python3 scripts/check_scout_snapshot_rows.py SNAPSHOT.json [COMMITTED_latest.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def problems(snapshot: dict, committed: dict | None, held=lambda v: False) -> list[str]:
    from core.gpu_availability import age_hours
    rows = [r for r in (snapshot.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return ["Scout snapshot has zero rows (missing data, not stale)"]
    out = []
    if not any(age_hours(r.get("availability_checked_at")) is not None for r in rows):
        out.append("Scout snapshot has no parseable availability_checked_at on any row (missing data, not stale)")
    have = {str(r.get("vendor")) for r in rows}
    before = {str(r.get("vendor")) for r in ((committed or {}).get("rows") or []) if isinstance(r, dict)}
    gone = sorted(v for v in before - have if not held(v))
    if gone:
        out.append(f"Scout snapshot has zero rows for source(s) on main: {', '.join(gone)} (missing data, not stale)")
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    snap = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    cp = Path(argv[1]) if len(argv) > 1 else ROOT / "data" / "gpu_availability" / "latest.json"
    committed = json.loads(cp.read_text(encoding="utf-8")) if cp.is_file() else None
    from core.owner_hold import hold_names, is_held
    names = hold_names()
    p = problems(snap, committed, lambda v: is_held(v, names))
    for x in p:
        print(f"::error title=Scout snapshot missing data::{x}")
    print("scout snapshot rows: " + ("FAIL" if p else f"ok ({len(snap.get('rows') or [])} rows)"))
    return 1 if p else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
