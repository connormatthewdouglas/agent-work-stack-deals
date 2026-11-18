#!/usr/bin/env python3
"""Dirty the working tree the way a collector does, without changing any data (Relay 2026-11-18).

The collector workflows (gpu-refresh, scout-import, lium-collect) run `pytest -q tests` after rewriting data/ and
api/v1 and before committing. PR CI ran on a clean checkout, so tests that silently needed `git status` to be clean
(e.g. a backup stamped with HEAD) passed on the PR and failed every collector run after merge (#276 -> 3a855913).
This appends one trailing newline to each tracked data/ JSON input below (generator outputs are byte-compared), so git sees modified files while
every JSON value stays identical, then CI reruns the suite. Prints the number of files touched. Never commits.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = ("data/gpu_pricing/*.json", "data/gpu_availability/*.json", "data/feed_state.json")  # inputs only; api/v1 outputs are byte-checked by pages-match


def main() -> int:
    tracked = set(subprocess.check_output(["git", "ls-files", "--", "data", "api/v1"], cwd=ROOT, text=True).split())
    n = 0
    for pat in PATTERNS:
        for p in sorted(ROOT.glob(pat)):
            rel = p.relative_to(ROOT).as_posix()
            if rel not in tracked:
                continue
            raw = p.read_text(encoding="utf-8")
            json.loads(raw)  # only valid JSON; whitespace after the value keeps it identical
            p.write_text(raw + "\n", encoding="utf-8")
            n += 1
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "data", "api/v1"], cwd=ROOT, text=True)
    print(f"dirtied {n} tracked JSON files ({len(dirty.splitlines())} modified per git status)")
    return 0 if n and dirty.strip() else 1


if __name__ == "__main__":
    sys.exit(main())
