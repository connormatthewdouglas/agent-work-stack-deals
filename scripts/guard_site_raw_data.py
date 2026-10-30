#!/usr/bin/env python3
"""Gauge re21 P1: raw repo data (data/, snapshots/) is not published. Only allowlisted public files stay,
with any availability fields stripped. With --check, nothing is changed; the run fails if raw data is in the site dir."""
import json, os, sys, shutil
AVAIL_KEYS = {"in_stock", "availability", "available_regions", "available_regions_detail", "available_regions_label",
              "stock_level", "checked_at", "availability_expires_at", "regions_expires_at", "derived_from_regions",
              "feed_status", "feed_min_offers", "availability_source"}
ALLOW = {"data/deal_gotchas.json"}  # linked from /changelog/; curated notes, no stock fields
RAW_DIRS = ("data", "snapshots")

def strip(o):
    if isinstance(o, dict): return {k: strip(v) for k, v in o.items() if k not in AVAIL_KEYS}
    if isinstance(o, list): return [strip(v) for v in o]
    return o

def has_avail(o):
    if isinstance(o, dict): return any(k in AVAIL_KEYS for k in o) or any(has_avail(v) for v in o.values())
    if isinstance(o, list): return any(has_avail(v) for v in o)
    return False

def files(site):
    for d in RAW_DIRS:
        for root, _, fs in os.walk(os.path.join(site, d)):
            for f in fs: yield os.path.relpath(os.path.join(root, f), site)

SKIP_TOP = ("api/v1/",)  # guarded feeds: availability fields are allowed there (they are expiry-checked)

def served_json(site):
    """re23 Q2: every .json the site serves outside api/v1 (any folder)."""
    for root, dirs, fs in os.walk(site):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_")) and d != "node_modules"]
        for f in fs:
            rel = os.path.relpath(os.path.join(root, f), site).replace(os.sep, "/")
            if f.endswith(".json") and not rel.startswith(SKIP_TOP):
                yield rel

def main():
    check = "--check" in sys.argv
    site = [a for a in sys.argv[1:] if not a.startswith("-")][0] if len(sys.argv) > 1 else "_site"
    bad = []
    for rel in sorted(files(site)):
        p = os.path.join(site, rel)
        if rel not in ALLOW:
            if check: bad.append(rel + " (raw data published)")
            else: os.remove(p)
            continue
        o = json.load(open(p))
        if has_avail(o):
            if check: bad.append(rel + " (availability fields)")
            else: json.dump(strip(o), open(p, "w"), indent=1)
    if not check:
        for d in RAW_DIRS:
            for root, dirs, fs in sorted(os.walk(os.path.join(site, d)), reverse=True):
                if not os.listdir(root): os.rmdir(root)
    for rel in sorted(served_json(site)):  # any other served JSON must carry no stock claim / availability fields
        try: o = json.load(open(os.path.join(site, rel)))
        except Exception: continue
        if has_avail(o): bad.append(rel + " (served JSON with availability fields)")
    if bad:
        print("RAW_DATA_FAIL"); [print(" ", b) for b in bad]; sys.exit(1)
    print("RAW_DATA_OK", "checked" if check else "cleaned", site)
if __name__ == "__main__": main()
