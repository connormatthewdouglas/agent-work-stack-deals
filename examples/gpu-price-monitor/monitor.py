#!/usr/bin/env python3
"""Open-source GPU price monitor (MIT, no dependencies).

Reads the Lantern Works price history API (/api/v1/gpu-prices/history.json, built
from daily snapshots) and alerts when a tracked rate's latest ranked price is at
least --drop percent below its previous ranked price. It also keeps a local
baseline (~/.lantern_gpu_baseline.json) so drops between two runs on the same day
are caught too.

Usage: python monitor.py [--gpu H100] [--drop 10] [--history URL_OR_FILE] [--state PATH]
Exit code 2 when at least one alert fired (useful for cron/Actions), else 0.
"""
import argparse, json, os, sys, urllib.request

URL = "https://thelanternworks.com/api/v1/gpu-prices/history.json"


def load(src):
    if os.path.exists(src):
        return json.load(open(src))
    req = urllib.request.Request(src, headers={"User-Agent": "lantern-gpu-monitor/0.2"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", help="substring filter, e.g. H100")
    ap.add_argument("--drop", type=float, default=10.0, help="alert threshold in percent (default 10)")
    ap.add_argument("--history", default=URL, help="history URL or local JSON file")
    ap.add_argument("--state", default=os.path.expanduser("~/.lantern_gpu_baseline.json"))
    a = ap.parse_args(argv)

    h = load(a.history)
    base = json.load(open(a.state)) if os.path.exists(a.state) else {}
    alerts, cur = [], {}
    for s in h["series"]:
        if a.gpu and a.gpu.lower() not in s["gpu"].lower():
            continue
        pts = [p for p in s["points"] if p.get("status") == "ranked" and p.get("hourly_usd")]
        if not pts:
            continue
        last = pts[-1]
        cur[s["key"]] = last["hourly_usd"]
        prev = pts[-2]["hourly_usd"] if len(pts) > 1 else base.get(s["key"])
        pct = (prev - last["hourly_usd"]) / prev * 100 if prev else 0.0
        flag = "ALERT" if pct >= a.drop else ""
        if flag:
            alerts.append(s["key"])
        print(f"{last['hourly_usd']:>8.4f} $/hr  {s['key']}  prev={prev}  "
              f"change={(f'{-pct:+.1f}%' if prev else 'n/a (first reading)')}  verified_at={last.get('verified_at')}  {flag}".rstrip())
    json.dump(cur, open(a.state, "w"))
    print(f"snapshots {h['first_snapshot']}..{h['last_snapshot']} ({h['snapshot_count']}), "
          f"threshold {a.drop}%, alerts={len(alerts)}. Tracked providers only; "
          "confirm on the vendor page before spending.")
    return 2 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
