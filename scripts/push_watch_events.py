"""Daily (GitHub Actions, after the GPU refresh): compute price-watch candidate events from the committed feeds and
push them in small signed batches to the hosted Worker, which only matches, signs and sends the webhooks (the Worker
never parses the big feeds on this path, keeping each invocation inside the free plan's CPU limit).

Env: WATCH_PUSH_SECRET (GitHub secret, same value as the Worker secret). Prints counts only, never the secret.
Usage: python3 scripts/push_watch_events.py [--dry-run] [--endpoint URL]"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "hosted" / "src")]
import watch as W  # noqa: E402

ENDPOINT = "https://lantern-works-mcp.lantern-works.workers.dev/internal/watch-events"
BATCH = 10


def batches(today: str | None = None) -> list[dict]:
    prices = json.loads((ROOT / "api/v1/gpu-prices.json").read_text(encoding="utf-8"))
    history = json.loads((ROOT / "api/v1/gpu-prices/history.json").read_text(encoding="utf-8"))
    changes = json.loads((ROOT / "api/v1/gpu-price-changes.json").read_text(encoding="utf-8"))
    today = today or datetime.now(timezone.utc).date().isoformat()
    events = [{k: e.get(k) for k in W.PUSH_EVENT_KEYS} for e in W.candidate_events(changes, history, today)]
    facts = W.rate_facts(prices)  # T47: eligibility facts (vram, tier class, guarded stock, regions) per rate
    out = []
    for i in range(0, len(events), BATCH):
        chunk = events[i:i + BATCH]
        reg = {e["rate_id"]: facts[e["rate_id"]]["regions"] for e in chunk if (facts.get(e.get("rate_id")) or {}).get("regions")}
        fx = {e["rate_id"]: {k: facts[e["rate_id"]].get(k) for k in W.FACT_KEYS} for e in chunk if e.get("rate_id") in facts}
        out.append({"events": chunk, "regions": reg, "facts": fx})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--endpoint", default=ENDPOINT)
    a = ap.parse_args()
    bs = batches()
    print(f"watch events: {sum(len(b['events']) for b in bs)} in {len(bs)} batches")
    if a.dry_run:
        return 0
    secret = os.environ.get("WATCH_PUSH_SECRET")
    if not secret:
        print("WATCH_PUSH_SECRET not set; skipping push")
        return 0
    tot, bad, problems = {"sent": 0, "failed": 0, "blocked_private": 0, "backlog": 0}, 0, []
    for b in bs:
        body = json.dumps(b, separators=(",", ":"), sort_keys=True)
        ts = int(time.time())
        req = urllib.request.Request(a.endpoint, data=body.encode(), method="POST", headers={
            "content-type": "application/json", "user-agent": "LanternWorks-WatchPush/1",
            "x-lantern-push-signature": W.sign(secret, ts, body)})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read())
            for k in tot:
                tot[k] += int(res.get(k) or 0)
            # T49: a 200 with ok:false, a persistence error or failed deliveries is a failed push, not a success
            if res.get("ok") is not True:
                problems.append(f"ok={res.get('ok')!r} error={res.get('error')!r}")
            if res.get("persist_error"):
                problems.append(f"persist_error={res['persist_error']}")
        except Exception as e:  # report status only
            bad += 1
            print(f"batch failed: {getattr(e, 'code', type(e).__name__)}")
    print(f"pushed {len(bs) - bad}/{len(bs)} batches: " + ", ".join(f"{k}={v}" for k, v in tot.items()))
    if tot["failed"]:
        problems.append(f"{tot['failed']} delivery attempt(s) failed (retried with backoff by later pushes; see stats.delivery)")
    for p in problems:
        print(f"::error::{p}" if os.environ.get("GITHUB_ACTIONS") else f"error: {p}")
    return 1 if bad or problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
