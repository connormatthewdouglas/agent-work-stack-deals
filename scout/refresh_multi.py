"""v3.3 (STAGED, schema stays 3.2) multi-source fast refresh: re-reads RunPod (unchanged collector, per-DC two reads >=60s) AND the
1h region claims of Oblivus (public page, two reads), Verda (authenticated read-only GETs, two reads) and Lambda (read-only GET
/instance-types, two reads), each second read >= SECOND_READ_MIN_GAP (60s) after that source's own first read. Rows of the
refreshed vendors are replaced in out/availability_v2_latest.json and the matching enriched rows replaced in place; every other
vendor's rows are kept. Then expired claims are pruned / overall rows re-derived and all latest files written atomically
(scout_io.write_latest). Lambda is GET-only: no launch/terminate/any mutating endpoint is ever called.
A non-RunPod source that fails is reported in meta.multi_refresh_errors and its previous rows are kept (they expire normally);
a RunPod failure exits nonzero with files untouched (same as refresh_runpod.py)."""
import json, glob, sys, time, base64, urllib.request
from datetime import datetime, timezone
import collect_v2 as c, enrich_feed_v2 as e, scout_io
OUT = "out"
SOURCES = ("RunPod", "Vast.ai", "Oblivus", "Verda", "Lambda", "Clore.ai", "CloudRift", "Hyperstack", "Novita AI", "Thunder Compute")  # T73: Clore (1h-capped claims expired between 4h cycles) + CloudRift  # v3.5: Vast added (bundles by location, two reads)

_LAMBDA = {}
def lambda_first(path="secrets/lambda.env", fetch=None):
    """Same rows as collect_v2.lambda_ (unchanged), plus FIRST_READ['Lambda'] and a stashed read-only re-read for the second pass."""
    key = c._verda_env(path)["LAMBDA_API_KEY"]
    def read():  # read-only GET; key only in the Authorization header, never logged
        req = urllib.request.Request(c.LBASE, headers={"User-Agent": c.UA, "Authorization": "Basic " + base64.b64encode((key + ":").encode()).decode()})
        with urllib.request.urlopen(req, timeout=40) as r: return json.load(r)["data"]
    read = fetch or read
    rows = c.lambda_(path) if fetch is None else _map_lambda(read())
    c.FIRST_READ["Lambda"] = time.time(); _LAMBDA.clear(); _LAMBDA["read"] = read
    return rows
def _map_lambda(data):
    ts = c.NOW(); rows = []
    for it, (model, vram, n) in c.LAMBDA.items():
        v = data.get(it)
        if not v: continue
        t = v["instance_type"]; regs = sorted(r["name"] for r in v.get("regions_with_capacity_available") or [])
        base = dict(vendor="Lambda", source="authenticated vendor API (not publicly reproducible)", gpu_model=model, vram_gb=vram,
                    tier=f"On-demand instance ({n}x GPU)", offer_count=None, stock_level=None, price_usd_hr=round(t["price_cents_per_hour"] / 100 / n, 4),
                    price_basis="price_cents_per_hour / GPUs", source_url=c.LBASE + " regions_with_capacity_available", collected_at=ts,
                    price_refresh="daily", availability_refresh="4h", vram_note=None,
                    availability_note="offer_count not exposed by Lambda API; in_stock=false means no region listed capacity for this instance type")
        rows.append({**base, "region": "all", "in_stock": bool(regs), "observation": None if regs else "authenticated observation: sold out - regions_with_capacity_available empty at check time", "derived_from_regions": True})
        for reg in regs: rows.append({**base, "region": reg, "in_stock": True, "observation": None})
    return rows

def lambda_second(rows, sleep=time.sleep, clock=time.time):
    """Second read >= 60s after Lambda's first read; confirmed = region listed with capacity on both reads. Returns gap or None."""
    # v3.4: also re-read when every type is sold out (no region rows), so a zero-capacity result can be confirmed by two reads
    if not _LAMBDA.get("read") or not any(r["vendor"] == "Lambda" for r in rows): return None
    t0 = c.FIRST_READ.get("Lambda", clock()); w = c.SECOND_READ_MIN_GAP - (clock() - t0)
    if w > 0: sleep(w)
    data = _LAMBDA["read"](); ts = c.NOW(); gap = round(clock() - t0, 1)
    rev = {}
    for it, (model, vram, n) in c.LAMBDA.items():
        v = data.get(it)
        if v is not None: rev[(model, vram, f"On-demand instance ({n}x GPU)")] = {x["name"] for x in v.get("regions_with_capacity_available") or []}
    for r in rows:
        if r["vendor"] != "Lambda" or r["region"] == "all": continue
        have = rev.get((r["gpu_model"], r["vram_gb"], r["tier"]))
        in2 = None if have is None else r["region"] in have  # type missing on 2nd read -> unknown, not false
        r.update(confirmation="two_reads", confirmed=bool(r["in_stock"]) and in2 is True, second_read_in_stock=in2, second_read_at=ts, second_read_gap_s=gap)
    for o in rows:  # v3.4: overall row records whether BOTH reads listed the type with zero regions with capacity
        if o["vendor"] != "Lambda" or o["region"] != "all": continue
        have = rev.get((o["gpu_model"], o["vram_gb"], o["tier"]))
        o.update(confirmation="two_reads" if have is not None else "single_read", second_read_at=ts, second_read_gap_s=gap,
                 second_read_region_count=None if have is None else len(have),
                 zero_capacity_two_reads=(o["in_stock"] is False and have is not None and len(have) == 0))
    return gap

def collect(errs, meta):
    c.RP_LOG.clear(); c.QUERIED.clear()  # v3.5: this run's query times only
    rp, obs = c.runpod()  # raises -> nonzero exit, files untouched
    meta.update(runpod_stock_level_observed=obs, runpod_dc_query_log=list(c.RP_LOG))
    got = {"RunPod": rp}
    for name, fn in (("Vast.ai", c.vast), ("Oblivus", c.oblivus), ("Verda", c.verda), ("Lambda", lambda_first), ("Clore.ai", lambda: c.with_backoff("Clore.ai", c.clore)), ("CloudRift", lambda: c.with_backoff("CloudRift", c.cloudrift)), ("Hyperstack", lambda: c.with_backoff("Hyperstack", c.hyperstack)), ("Novita AI", lambda: c.with_backoff("Novita AI", c.novita)), ("Thunder Compute", lambda: c.with_backoff("Thunder Compute", c.thunder))):  # T73: backoff
        try: got[name] = fn()
        except Exception as ex: errs[name] = type(ex).__name__ + ": " + str(ex)[:200]  # never includes the key
    other = [r for n in ("Vast.ai", "Oblivus", "Verda", "Clore.ai", "CloudRift", "Hyperstack", "Novita AI", "Thunder Compute") if n in got for r in got[n]]
    meta["second_read_log"] = c.second_reads(other)  # v3.5: Vast H100 (VAST_CONFIRM) + Verda + Oblivus, per-source >=60s gap
    meta["second_read_gap_s"] = dict(c.SECOND_READ_GAPS)
    for x in meta["second_read_log"]:
        errs.setdefault(x["source"], "second read failed: " + x["error"])
    if "Lambda" in got:
        try: meta["second_read_gap_s"]["Lambda"] = lambda_second(got["Lambda"])
        except Exception as ex: errs["Lambda"] = "second read failed: " + type(ex).__name__
    for name in list(got):  # a source whose second read failed is not replaced (old rows kept, they expire on their own)
        if name != "RunPod" and name in errs: got.pop(name)
    for rows in got.values():
        for r in rows: r.setdefault("source", "public no-auth API"); r.setdefault("observation", None); r.pop("_loc", None)
        for r in rows: r["availability_refresh"] = "20m"  # covered by the 20-min multi refresh
        c.add_claim_fields(rows)
    # v3.5 (Gauge 4): fresh meta.queried for every refreshed source that records it (only Vast does: "Vast.ai|<model>")
    meta["_queried_fresh"] = {k: v for k, v in c.QUERIED.items() if k.split("|")[0] in got}
    if "Vast.ai" in got:  # v3.5: same MIN_MARKET_OFFERS hold as the 4h cycle (rule unchanged)
        mmo = c.feed_min_market_offers(); c.mark_vast_held(got["Vast.ai"], mmo); meta["feed_min_market_offers"] = mmo
    meta["runpod_second_read_gap_s"] = {"min": min(c.RP_GAPS, default=None), "max": max(c.RP_GAPS, default=None), "n": len(c.RP_GAPS)}
    return got

def merge_snapshot(snap, got, meta_upd, now):
    vend = set(got); keep = [r for r in snap["rows"] if r["vendor"] not in vend]
    snap = dict(snap, rows=keep + [r for v in SOURCES if v in got for r in got[v]], version="3.2")
    meta = dict(snap.get("meta") or {}); meta_upd = dict(meta_upd); fresh = meta_upd.pop("_queried_fresh", {})
    q = {k: v for k, v in (meta.get("queried") or {}).items() if k.split("|")[0] not in vend}; q.update(fresh)  # v3.5: refreshed sources' entries replaced
    meta.update(meta_upd); meta["queried"] = q; meta["runpod_refreshed_at"] = now
    meta["multi_refreshed_at"] = {v: now for v in got}; snap["meta"] = meta
    return snap

def merge_enriched(old, new_rows, vendors, live_ok=True):
    """Refreshed vendors' rows replaced in place; in_live_feed comes from this run's live-feed read (e.fetch_live_keys, same as the
    4h cycle), falling back to the last cycle's value if the live feed is unreadable. Rows new in the join are APPENDED only when
    the live feed was read (so in_live_feed is True/False, never None); if it was unreadable they are left out until the next cycle.
    Other vendors' rows are kept as the same objects. Refreshed rows with an availability join get availability_refresh='20m'."""
    k = lambda r: (e.norm_vendor(r["vendor"]), r["gpu"], r["vram_gb"], r["tier"])
    new = {k(r): r for r in new_rows if e.norm_vendor(r["vendor"]) in vendors}
    tag = lambda r: dict(r, availability_refresh="20m") if r.get("availability_source") else r
    flag = lambda n, o: n["in_live_feed"] if live_ok and n.get("in_live_feed") is not None else (o or {}).get("in_live_feed")
    rows = [tag(dict(new[k(r)], in_live_feed=flag(new[k(r)], r))) if e.norm_vendor(r["vendor"]) in vendors and k(r) in new else r for r in old["rows"]]
    have = {k(r) for r in old["rows"]}
    # v3.3: new rows only when the live feed was read (in_live_feed known); otherwise they wait for the next 4h cycle
    return rows + ([tag(r) for kk, r in new.items() if kk not in have and r.get("in_live_feed") is not None] if live_ok else [])

def main():
    t0 = time.time()
    snap = json.load(open(f"{OUT}/availability_v2_latest.json"))
    if snap.get("errors"): sys.exit("latest snapshot carries errors; refusing to merge")
    errs, meta = {}, {}
    got = collect(errs, meta); now = c.NOW()
    meta["multi_refresh_errors"] = errs or None
    snap2 = merge_snapshot(snap, got, meta, now)
    enr = json.load(open(f"{OUT}/feed_enriched_v2_latest.json"))
    files = [json.load(open(f)) for f in sorted(glob.glob(e.SRC + "/data/gpu_pricing/*.json"))]
    live_keys, live_updated = e.fetch_live_keys()  # same public read-only GET as the 4h cycle
    new_rows, _ = e.enrich(files, snap2, live_keys)
    rows = merge_enriched(enr, new_rows, set(got), live_ok=live_keys is not None)
    enr2 = dict(enr, rows=rows, stats=dict(enr["stats"], runpod_refreshed_at=now))
    snap2, enr2, n_drop = scout_io.prune_and_rederive(snap2, enr2, files=files)
    enr2 = scout_io.restat(enr2); enr2["stats"].update(runpod_refreshed_at=now, expired_region_claims_dropped=n_drop, multi_refreshed_sources=sorted(got))
    snap2, enr2 = scout_io.stamp_freshness(snap2, enr2)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scout_io.write_latest(snap2, enr2, OUT, extra_snapshot_name=f"availability_v2_{stamp}_multi_refresh.json")
    print("refreshed:", sorted(got), "source errors:", errs or None, "dropped expired:", n_drop, "gaps:", meta.get("second_read_gap_s"), "rp:", meta.get("runpod_second_read_gap_s"))
    print(f"multi refresh {now} took {time.time() - t0:.0f}s")

if __name__ == "__main__": main()
