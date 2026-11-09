"""v3.0 RunPod-only hourly refresh: re-reads RunPod (aggregate + per-DC two reads, v2.9 rules), replaces ONLY RunPod rows in
out/availability_v2_latest.{json,csv} and out/feed_enriched_v2_latest.{json,csv}; other vendors' rows are kept byte-for-byte."""
import json, csv, glob, sys
from datetime import datetime, timezone
import collect_v2 as c, enrich_feed_v2 as e
OUT = "out"

def merge_snapshot(snap, rp_rows, rp_log, obs, now):
    keep = [r for r in snap["rows"] if r["vendor"] != "RunPod"]
    snap = dict(snap, rows=keep + rp_rows, version="3.2")
    meta = dict(snap.get("meta") or {}); meta["runpod_dc_query_log"] = rp_log; meta["runpod_stock_level_observed"] = obs
    meta["runpod_refreshed_at"] = now; snap["meta"] = meta
    return snap

def merge_enriched(old, new_rows):
    """Replace RunPod rows in place (same position), keep every other row object unchanged."""
    newrp = {(r["vendor"], r["gpu"], r["vram_gb"], r["tier"]): r for r in new_rows if r["vendor"] == "RunPod"}
    rows = []
    for r in old["rows"]:
        n = newrp.get((r["vendor"], r["gpu"], r["vram_gb"], r["tier"])) if r["vendor"] == "RunPod" else None
        rows.append(r if n is None else dict(n, in_live_feed=r["in_live_feed"]))  # live-feed flag not re-read hourly: keep last cycle's
    return rows

def main():
    snap = json.load(open(f"{OUT}/availability_v2_latest.json"))
    if snap.get("errors"): sys.exit("latest snapshot carries errors; refusing to merge")
    c.RP_LOG.clear()
    rp, obs = c.runpod()  # raises on failure -> nonzero exit, files untouched
    for r in rp: r.setdefault("source", "public no-auth API"); r.setdefault("observation", None)
    c.add_claim_fields(rp)
    now = c.NOW()
    snap2 = merge_snapshot(snap, rp, list(c.RP_LOG), obs, now)
    enr = json.load(open(f"{OUT}/feed_enriched_v2_latest.json"))
    files = [json.load(open(f)) for f in sorted(glob.glob(e.SRC + "/data/gpu_pricing/*.json"))]  # same local feed-src as last cycle (no fetch)
    new_rows, _ = e.enrich(files, snap2, None)
    rows = merge_enriched(enr, new_rows)
    # v3.0: non-RunPod 1h region claims (Vast/Verda/Oblivus) are not re-read here; expired ones are dropped (rows + detail),
    # then stats (incl. region_conflicts) are recomputed and all four latest files are replaced atomically.
    import scout_io
    enr2 = dict(enr, rows=rows, stats=dict(enr["stats"], runpod_refreshed_at=now))
    snap2, enr2, n_drop = scout_io.prune_and_rederive(snap2, enr2, files=files)  # v3.2: derived overall rows recomputed
    enr2 = scout_io.restat(enr2); enr2["stats"]["runpod_refreshed_at"] = now; enr2["stats"]["expired_region_claims_dropped"] = n_drop
    snap2, enr2 = scout_io.stamp_freshness(snap2, enr2)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scout_io.write_latest(snap2, enr2, OUT, extra_snapshot_name=f"availability_v2_{stamp}_runpod_refresh.json")
    print("dropped expired non-refreshed region claims:", n_drop)
    print("runpod refresh", now, "rows", len(rp), "observed", obs)

if __name__ == "__main__": main()
