#!/usr/bin/env python3
"""Gate pre-check for latest-scout-import (Gauge NO-GO B1 / Bjorn 2026-11-17: empty or zero-row = fail).

Missing data is not stale data. Exits 1 when the Scout snapshot:
  * has no rows,
  * has no parseable availability_checked_at on any row, or
  * has zero rows for a source (vendor) that has rows in the committed data/gpu_availability/latest.json
    (owner-held vendors excepted, since the importer drops them anyway), UNLESS Bjorn's rule below applies.
Bjorn 2026-11-17: if a vendor is listed in meta.nonfatal_errors (Scout's availability_v2_latest.json) and its
last good rows are still on main, it warns as stale, with a hard fail once those rows are older than 7 days
(168h) by their own availability_checked_at. A vendor that's empty with no nonfatal entry fails.
Exit 0 means the snapshot has data; whether it is too OLD is the importer's 8h check (warns; >168h fails).
Usage: python3 scripts/check_scout_snapshot_rows.py SNAPSHOT.json [COMMITTED_latest.json] [--avail AVAIL.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


STALE_FAIL_H = 168  # Bjorn 2026-11-17: hard fail after 7 days


def check(snapshot: dict, committed: dict | None, held=lambda v: False, nonfatal: dict | None = None,
          now=None) -> tuple[list[str], list[str]]:
    """(failures, warnings)."""
    from core.gpu_availability import age_hours
    rows = [r for r in (snapshot.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return ["Scout snapshot has zero rows (missing data, not stale)"], []
    out, warn = [], []
    if not any(age_hours(r.get("availability_checked_at"), now) is not None for r in rows):
        out.append("Scout snapshot has no parseable availability_checked_at on any row (missing data, not stale)")
    have = {str(r.get("vendor")) for r in rows}
    main_rows = [r for r in ((committed or {}).get("rows") or []) if isinstance(r, dict)]
    before = {str(r.get("vendor")) for r in main_rows}
    nonfatal = {str(k): v for k, v in (nonfatal or {}).items()}
    gone = []
    for v in sorted(v for v in before - have if not held(v)):
        if v not in nonfatal:
            gone.append(v)
            continue
        ages = [a for a in (age_hours(r.get("availability_checked_at"), now) for r in main_rows
                            if str(r.get("vendor")) == v) if a is not None]
        if not ages:
            out.append(f"{v}: listed in nonfatal_errors but its rows on main have no parseable checked_at (missing data)")
        elif min(ages) > STALE_FAIL_H:
            out.append(f"{v}: listed in nonfatal_errors ({str(nonfatal[v])[:80]}); last good rows on main are "
                       f"{min(ages):.1f}h old (> {STALE_FAIL_H}h hard cap)")
        else:
            warn.append(f"{v}: zero rows this snapshot, listed in nonfatal_errors ({str(nonfatal[v])[:80]}); "
                        f"last good rows on main kept, {min(ages):.1f}h old (stale; fails after {STALE_FAIL_H}h)")
    if gone:
        out.append(f"Scout snapshot has zero rows for source(s) on main with no nonfatal_errors entry: "
                   f"{', '.join(gone)} (missing data, not stale)")
    return out, warn


def problems(snapshot: dict, committed: dict | None, held=lambda v: False) -> list[str]:
    """Failures only, with no nonfatal_errors (back-compat)."""
    return check(snapshot, committed, held)[0]


def main(argv: list[str]) -> int:
    import argparse
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("committed", nargs="?")
    ap.add_argument("--avail", help="Scout availability_v2_latest.json (meta.nonfatal_errors)")
    if not argv:
        print(__doc__)
        return 2
    a = ap.parse_args(argv)
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    cp = Path(a.committed) if a.committed else ROOT / "data" / "gpu_availability" / "latest.json"
    committed = json.loads(cp.read_text(encoding="utf-8")) if cp.is_file() else None
    nonfatal = {}
    if a.avail and Path(a.avail).is_file() and Path(a.avail).stat().st_size:
        av = json.loads(Path(a.avail).read_text(encoding="utf-8"))
        nonfatal = ((av.get("meta") or {}).get("nonfatal_errors") or {}) if isinstance(av, dict) else {}
    from core.owner_hold import hold_names, is_held
    names = hold_names()
    p, w = check(snap, committed, lambda v: is_held(v, names), nonfatal)
    for x in w:
        print(f"::warning title=Scout source stale (nonfatal)::{x}")
        if os.environ.get("LW_STALE_NOTES"):
            with open(os.environ["LW_STALE_NOTES"], "a", encoding="utf-8") as fh:
                fh.write(f"latest-scout-import: {x}\n")
    for x in p:
        print(f"::error title=Scout snapshot missing data::{x}")
    print("scout snapshot rows: " + ("FAIL" if p else f"ok ({len(snap.get('rows') or [])} rows, {len(w)} stale source(s))"))
    return 1 if p else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
