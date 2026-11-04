#!/usr/bin/env python3
"""T112: trailing-7-day observed in-stock share per (vendor, gpu, vram_gb, tier) from the git history of
data/gpu_availability/latest.json (one Scout import = one check; duplicate generations counted once).
Only readings with in_stock true/false count; unknown/failed checks are excluded (T66 honesty rule).
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
OUT = ROOT / "data" / "gpu_availability" / "rate_7d.json"


def main() -> int:
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
    now = datetime.now(timezone.utc).replace(microsecond=0)
    since = now - timedelta(days=days)
    shas = subprocess.run(["git", "log", f"--since={since.isoformat()}", "--format=%H", "--", SRC], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.split()
    seen, counts = set(), {}
    for sha in shas:
        try:
            doc = json.loads(subprocess.run(["git", "show", f"{sha}:{SRC}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        gen = doc.get("generation_id") or doc.get("collected_at")
        if not gen or gen in seen:
            continue
        seen.add(gen)
        for r in doc.get("rows") or []:
            if r.get("in_stock") not in (True, False):
                continue
            k = (r["vendor"], r["gpu"], r.get("vram_gb"), r["tier"])
            c = counts.setdefault(k, [0, 0])
            c[0] += 1
            c[1] += r["in_stock"] is True
    rows = [{"vendor": v, "gpu": g, "vram_gb": m, "tier": t, "checks": n, "in_stock_checks": s, "rate": round(s / n, 4)}
            for (v, g, m, t), (n, s) in sorted(counts.items(), key=str)]
    OUT.write_text(json.dumps({"schema": "lantern-works-availability-rate/1", "window_days": days,
                               "window_start": since.isoformat(), "window_end": now.isoformat(),
                               "generations": len(seen), "rows": rows}, indent=1) + "\n", encoding="utf-8")
    print(f"{len(seen)} Scout generations in {days}d; {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
