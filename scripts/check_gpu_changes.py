#!/usr/bin/env python3
"""CI gate: any GPU rate whose price changed vs the previous commit (--base, default HEAD~1) or vs the latest
dated snapshot must carry source_url + an evidence quote containing the new price + a newer evidence.checked_at.
Exit 1 on any unsupported change."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.gpu import load_vendor_files  # noqa: E402
from core import gpu_history as h  # noqa: E402


def docs_at(ref: str) -> list[dict] | None:
    try:
        names = subprocess.check_output(["git", "ls-tree", "--name-only", ref, "data/gpu_pricing/"], cwd=ROOT, text=True,
                                        stderr=subprocess.DEVNULL).split()
        return [json.loads(subprocess.check_output(["git", "show", f"{ref}:{n}"], cwd=ROOT, text=True))
                for n in names if n.endswith(".json")]
    except subprocess.CalledProcessError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD~1")
    a = ap.parse_args()
    docs = load_vendor_files()
    probs = []
    old = docs_at(a.base)
    if old is None:
        print(f"base {a.base} not available; skipping commit comparison")
    else:
        probs += h.change_problems(h.base_from_docs(old), docs, f"commit {a.base}")
    snaps = h.load_snapshots()
    if snaps:
        probs += h.change_problems(h.base_from_snapshot(snaps[-1]), docs, f"snapshot {snaps[-1]['date']}")
    for p in probs:
        print("UNSUPPORTED PRICE CHANGE:", p)
    print(f"gpu change check: {len(probs)} problem(s)")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
