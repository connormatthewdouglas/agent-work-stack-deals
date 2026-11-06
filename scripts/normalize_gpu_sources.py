#!/usr/bin/env python3
"""T117 import boundary: split known API suffixes into evidence; validate all citations before writing.
Run after wider imports, before generating public feeds. --check validates without modifying any file.
"""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.source_urls import citation_problems, normalize_doc


def main():
    pending, total = [], 0
    for path in sorted((ROOT / "data/gpu_pricing").glob("*.json")):
        old = json.loads(path.read_text())
        if "--check" in sys.argv:
            probs = citation_problems(old)
            if probs:
                raise SystemExit("\n".join(probs))
            continue
        doc, n = normalize_doc(old)
        if n:
            pending.append((path, doc)); total += n
    # All inputs validate before any mutation (do not leave a half-repaired import).
    for path, doc in pending:
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"citation URLs valid; normalized {total} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
