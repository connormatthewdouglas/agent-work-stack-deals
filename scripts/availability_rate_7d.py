#!/usr/bin/env python3
"""T112: trailing-7-day observed in-stock share per (vendor, gpu, vram_gb, tier) from the git history of
data/gpu_availability/latest.json (one Scout import = one check; duplicate generations counted once).
Only true/false readings enter the rate; unknown checks are counted separately, never treated as failures.
P38 (additive): unknown checks are also split by the row's own availability_reason (Scout T113 enum):
never_ran_checks = no stock reading was taken (check_failed_timeout, check_failed_http, stale/backoff);
no_source_checks = the probe ran but the source gives no stock signal (no_source). unknown_checks stays the total; both
are null for a row when any of its unknown checks has no recorded reason (older captures), never a guessed split.
Lium (collected by scripts/collect_lium.py, not by Scout, so absent from latest.json) is counted from the git history of
data/gpu_pricing/lium.json plus the working-tree file: each record's availability.in_stock at its own availability.checked_at
is one check; a capture stamp seen in several commits (or the working tree and HEAD) counts once; a record with no
availability object adds no check (no invented checks). The working tree is included so a just-collected capture in the
same job is counted before the successful commit lands in git.
Writes data/gpu_availability/rate_7d.json, read by core/availability_rate.py. Needs full git history (fetch-depth 0).
Usage: availability_rate_7d.py [--days 7]"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = "data/gpu_availability/latest.json"
LIUM_SRC = "data/gpu_pricing/lium.json"
OUT = ROOT / "data" / "gpu_availability" / "rate_7d.json"
# P38: availability_reason (Scout T113 enum) of an unknown check -> which split count it adds to
UNKNOWN_SPLIT = {"check_failed_timeout": "never_ran_checks", "check_failed_http": "never_ran_checks",
                 "stale": "never_ran_checks", "no_source": "no_source_checks"}


def rows_from_docs(docs: list) -> tuple[list, int]:
    """Per-row counts from Scout import docs (newest first, as git log lists them); a repeated generation counts once."""
    seen, counts = set(), {}
    for doc in docs:
        gen = doc.get("generation_id") or doc.get("collected_at")
        if not gen or gen in seen:
            continue
        seen.add(gen)
        for r in doc.get("rows") or []:
            k = (r["vendor"], r["gpu"], r.get("vram_gb"), r["tier"])
            c = counts.setdefault(k, {"checks": 0, "in_stock_checks": 0, "unknown_checks": 0,
                                      "never_ran_checks": 0, "no_source_checks": 0, "_unclassified": 0,
                                      "first_check_at": None, "last_check_at": None})
            if r.get("in_stock") is True or r.get("in_stock") is False:
                c["checks"] += 1
                c["in_stock_checks"] += r["in_stock"] is True
            else:
                c["unknown_checks"] += 1
                c[UNKNOWN_SPLIT.get(r.get("availability_reason"), "_unclassified")] += 1
            stamp = r.get("checked_at") or doc.get("collected_at")
            if stamp:
                c["first_check_at"] = min(c["first_check_at"] or stamp, stamp)
                c["last_check_at"] = max(c["last_check_at"] or stamp, stamp)
    for c in counts.values():
        if c.pop("_unclassified"):
            c["never_ran_checks"] = c["no_source_checks"] = None  # cannot split without a reason on every unknown check
    rows = [{"vendor": v, "gpu": g, "vram_gb": m, "tier": t, **c,
             "rate": round(c["in_stock_checks"] / c["checks"], 4) if c["checks"] else None}
            for (v, g, m, t), c in sorted(counts.items(), key=str)]
    return rows, len(seen)


def lium_docs_as_scout(docs: list) -> list:
    """Adapt lium.json docs to the Scout import shape: one pseudo-doc per distinct availability.checked_at capture."""
    out = []
    for doc in docs:
        by_stamp: dict = {}
        for r in doc.get("records") or []:
            av = r.get("availability")
            stamp = av.get("checked_at") if isinstance(av, dict) else None
            if not stamp:
                continue  # no availability reading recorded: not a check
            by_stamp.setdefault(stamp, []).append(
                {"vendor": r.get("vendor") or doc.get("vendor") or "Lium", "gpu": r["gpu"], "vram_gb": r.get("vram_gb"),
                 "tier": r["tier"], "in_stock": av.get("in_stock"), "checked_at": stamp})
        out += [{"generation_id": f"lium:{s}", "collected_at": s, "rows": rows} for s, rows in by_stamp.items()]
    return out


def working_tree_doc(src: str, root=ROOT):
    """The on-disk file, if readable. A just-collected capture is not in git until the job commits."""
    path = Path(root) / src
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _history(src: str, since, root=ROOT) -> list:
    shas = subprocess.run(["git", "log", f"--since={since.isoformat()}", "--format=%H", "--", src], cwd=root,
                          capture_output=True, text=True, check=True).stdout.split()
    docs = []
    for sha in shas:
        try:
            docs.append(json.loads(subprocess.run(["git", "show", f"{sha}:{src}"], cwd=root, capture_output=True, text=True, check=True).stdout))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
    wt = working_tree_doc(src, root)
    if wt is not None:
        docs.insert(0, wt)  # newest; rows_from_docs dedupes by generation_id / capture stamp
    return docs


def main() -> int:
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
    now = datetime.now(timezone.utc).replace(microsecond=0)
    since = now - timedelta(days=days)
    docs = _history(SRC, since) + lium_docs_as_scout(_history(LIUM_SRC, since))
    rows, n_gen = rows_from_docs(docs)
    OUT.write_text(json.dumps({"schema": "lantern-works-availability-rate/1", "window_days": days,
                               "window_start": since.isoformat(), "window_end": now.isoformat(),
                               "generations": n_gen, "rows": rows}, indent=1) + "\n", encoding="utf-8")
    print(f"{n_gen} generations (Scout imports + Lium captures) in {days}d; {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
