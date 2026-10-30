#!/usr/bin/env python3
"""Gauge re21 live check: every repo raw data path must 404 on the site, or have no stock claim/availability
fields; /data/gpu_availability/latest.json must 404."""
import json, os, sys, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(__file__))
from guard_site_raw_data import has_avail, ALLOW, RAW_DIRS
BASE = os.environ.get("LW_SITE", "https://thelanternworks.com")
def get(path):
    try:
        r = urllib.request.urlopen(urllib.request.Request(f"{BASE}/{path}?cb={os.getpid()}", headers={"User-Agent": "lw-ci"}), timeout=20)
        return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, b""
paths = sorted({os.path.join(r, f) for d in RAW_DIRS for r, _, fs in os.walk(d) for f in fs if f.endswith(".json")})
paths.append("data/gpu_availability/latest.json")
# re22 Q2: every root-level JSON in the repo that the site may serve is scanned too (deals.json, agent.json, ...)
ROOT_JSON = sorted(f for f in os.listdir(".") if f.endswith(".json"))
bad = []
for p in sorted(set(paths)):
    code, body = get(p)
    if p == "data/gpu_availability/latest.json" and code != 404: bad.append(f"{p}: {code}, expected 404")
    elif code == 200:
        try: o = json.loads(body)
        except Exception: o = None
        if p not in ALLOW: bad.append(f"{p}: served (200)")
        elif o is not None and has_avail(o): bad.append(f"{p}: availability fields")
for p in ROOT_JSON:
    code, body = get(p)
    if code != 200: continue
    try: o = json.loads(body)
    except Exception: continue
    if has_avail(o): bad.append(f"{p}: served root JSON with in_stock/availability fields")
print(f"sampled {len(set(paths))} raw paths + {len(ROOT_JSON)} root JSON")
if bad: print("PUBLIC_RAW_FAIL"); [print(" ", b) for b in bad]; sys.exit(1)
print("PUBLIC_RAW_OK")
