"""Regenerate the site at the committed feed's clock and fail if any committed file changes.

The validate workflow allows HTML to drift after an unpinned generate (freshness dates).
This check pins LW_AVAIL_NOW to api/v1/gpu-prices.json feed_updated_at, the same clock
test_live_count_matches_api uses, then runs scripts/generate_seo_pages.py. A stale
rental page or model JSON file fails the diff. It does not relax the workflow's
existing deals.json / sitemap / schema diff.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    feed = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    stamp = feed.get("feed_updated_at")
    if not stamp:
        print("gpu-prices.json has no feed_updated_at", file=sys.stderr)
        return 2
    env = os.environ.copy()
    env["LW_AVAIL_NOW"] = stamp
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "generate_seo_pages.py")], cwd=ROOT, env=env)
    diff = subprocess.run(["git", "diff", "--stat"], cwd=ROOT, capture_output=True, text=True)
    if diff.stdout.strip():
        print(diff.stdout)
        named = subprocess.run(["git", "diff", "--name-only"], cwd=ROOT, capture_output=True, text=True)
        print("generated pages differ from the commit:", file=sys.stderr)
        print(named.stdout, file=sys.stderr)
        return 1
    print("generated pages match the commit at", stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
