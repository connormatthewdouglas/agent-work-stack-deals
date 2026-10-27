#!/usr/bin/env python3
"""Open-source GPU price monitor (MIT). Polls Lantern Works /api/v1/gpu-prices.json,
diffs against last snapshot, prints changes. No deps. Usage: python monitor.py [--gpu H100] [--max 2.0]"""
import argparse, json, os, sys, urllib.request
URL = "https://thelanternworks.com/api/v1/gpu-prices.json"
STATE = os.path.expanduser("~/.lantern_gpu_snapshot.json")
ap = argparse.ArgumentParser(); ap.add_argument("--gpu"); ap.add_argument("--max", type=float)
a = ap.parse_args()
req = urllib.request.Request(URL, headers={"User-Agent": "lantern-gpu-monitor/0.1"})
data = json.load(urllib.request.urlopen(req, timeout=20))
rates = [r for r in data["rates"] if (not a.gpu or a.gpu.lower() in r["gpu"].lower())
         and (a.max is None or (r.get("hourly_equiv_usd") or 1e9) <= a.max)]
cur = {f'{r["deal_id"]}|{r["gpu"]}': r.get("hourly_equiv_usd") for r in rates}
old = json.load(open(STATE)) if os.path.exists(STATE) else {}
for k, v in sorted(cur.items(), key=lambda x: x[1] or 1e9):
    tag = "NEW" if k not in old else ("CHANGED %s->%s" % (old[k], v) if old[k] != v else "")
    print(f"{v!s:>7} $/hr  {k}  {tag}")
for k in old.keys() - cur.keys(): print(f"REMOVED {k}")
json.dump(cur, open(STATE, "w"))
print(f"feed_updated_at={data['feed_updated_at']} (confirm price on vendor page before spending)")
