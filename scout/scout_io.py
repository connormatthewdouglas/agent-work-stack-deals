"""v3.0 shared output helpers: expiry pruning, stats recompute, atomic writes of the latest pair (snapshot + enriched, json + csv).
Precedence: when snapshot `runpod_refreshed_at` is later than `collected_at`, RunPod rows are as of runpod_refreshed_at; all other
vendors are as of collected_at. Each claim's own checked_at / availability_expires_at always wins over either."""
import json, csv, os, glob, hashlib, uuid
from datetime import datetime, timezone
import collect_v2 as c, enrich_feed_v2 as e
OUT = "out"
FRESHNESS_NOTE = ("runpod_refreshed_at (when present and later than collected_at) takes precedence for RunPod rows; other vendors are as of "
                  "collected_at; per-claim checked_at/availability_expires_at take precedence over both.")
def _t(s): return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
def _exp(x, now): v = x.get("availability_expires_at"); return isinstance(v, str) and _t(v) <= now

def prune_expired(snap, enr, now=None):
    """Drop expired REGION claims: snapshot rows with region != 'all', and enriched available_regions_detail entries
    (+ their available_regions / region_conflicts entries). Overall rows are never dropped. Returns (snap, enr, dropped_count)."""
    now = now or datetime.now(timezone.utc); n = 0
    keep = []
    for r in snap["rows"]:
        if r.get("region") not in (None, "all") and _exp(r, now): n += 1; continue
        keep.append(r)
    snap = dict(snap, rows=keep)
    rows = []
    for r in enr["rows"]:
        det = r.get("available_regions_detail") or []
        alive = [x for x in det if not _exp(x, now)]
        conf = [x for x in (r.get("region_conflicts") or []) if not _exp(x, now)]
        if len(alive) != len(det) or len(conf) != len(r.get("region_conflicts") or []):
            n += (len(det) - len(alive)) + (len(r.get("region_conflicts") or []) - len(conf))
            names = {x["region"] for x in alive}
            ar = [x for x in (r.get("available_regions") or []) if x in names]
            r = dict(r, available_regions_detail=alive or None, available_regions=ar or None,
                     available_regions_label=r.get("available_regions_label") if alive else None, region_conflicts=conf or None)
        rows.append(r)
    enr = dict(enr, rows=rows)
    return snap, enr, n

def _grp(r): return (r.get("vendor"), r.get("gpu_model"), r.get("vram_gb"), r.get("tier"))
DERIVED_VENDORS = ("Lambda", "Verda", "Oblivus", "RunPod", "Vast.ai", "Clore.ai", "CloudRift", "Hyperstack")  # T73: CloudRift, Hyperstack  # v3.5e: Clore (overall = confirmed regions, <= 1h); v3.5 (Gauge a): Vast added; v3.3: overall rows kept from older collectors lack the flag
def _vend(o): return "Clore.ai" if e.is_clore(o.get("vendor")) else o.get("vendor")  # v3.5e: case-insensitive Clore
def _derived(o): return bool(o.get("derived_from_regions")) or _vend(o) in DERIVED_VENDORS
def _region_ok(r):  # v3.5e: Clore regions need the strict two-read check (enrich._clore_region_ok); others unchanged
    return e._clore_region_ok(r) if e.is_clore(r.get("vendor")) else (r.get("in_stock") is True and r.get("confirmed") is True)
def clear_unknown_claims(rows):
    """v3.5e: a row with in_stock null makes no claim: overall rows (enriched rows; snapshot region 'all') lose checked_at and
    availability_expires_at, so an expired expiry can never be published. Snapshot region rows keep theirs and are pruned on expiry."""
    n = 0
    for r in rows:
        if r.get("in_stock") is None and r.get("region") in (None, "all") and (r.get("availability_expires_at") is not None or r.get("checked_at") is not None):
            for k in ("checked_at", "availability_expires_at"):
                if k in r: r[k] = None  # never add fields (CSV writers use fixed columns)
            n += 1
    return n
def _cap(o):
    """Latest allowed expiry for a derived overall row: checked_at + 1h (15m Verda spot); None if the row makes no claim."""
    if _vend(o) not in DERIVED_VENDORS or not o.get("checked_at") or not isinstance(o.get("availability_expires_at"), str): return None
    ttl = c.SPOT_REGION_TTL if _vend(o) == "Verda" and "Spot" in (o.get("tier") or "") else c.REGION_TTL
    return _t(o["checked_at"]) + ttl
def _out_confirmed(r):
    """v3.4: region confirmed out of stock = in_stock False after two reads (collectors set confirmed=False for these) and the
    second read did not show stock (second-read value present and negative; missing/None second read -> not confirmed)."""
    if r.get("in_stock") is not False or r.get("confirmation") != "two_reads": return False
    if "second_read_in_stock" in r: return r["second_read_in_stock"] is False
    if "second_read_available_gpus" in r: return r["second_read_available_gpus"] == 0
    if "second_read_offer_count" in r: return r["second_read_offer_count"] == 0
    if "second_read_stock_level" in r:  # v3.5 (Gauge 4a): empty/None second-read level is NOT a confirmed out; need a real non-stock level
        lv = r["second_read_stock_level"]
        # v3.5 (Gauge 5): only a known RunPod out-of-stock level counts; 'low', 'HIGH', unknown strings, ""/None -> not confirmed
        return r.get("second_read_at") is not None and isinstance(lv, str) and lv in c.RUNPOD_OUT_LEVELS
    return False
def rederive_overall(snap, touched, now):
    """v3.2: recompute overall rows marked derived_from_regions whose group lost region claims (touched) or that have expired
    themselves, or (v3.4) that disagree with their regions: True only with a confirmed in-stock region, False only if all are
    confirmed out of stock, otherwise null (never invented).
    Claim fields follow the in-stock region with the latest expiry; with no claim they are cleared. Returns count recomputed."""
    rows = snap["rows"]; n = 0
    for o in rows:
        if o.get("region") != "all" or not _derived(o): continue
        g = _grp(o)
        # v3.3c: an overall row may not outlive checked_at + 1h (15m Verda spot); rows carried over with the old 8h expiry are
        # normalized to that cap first, then recomputed below once the cap has passed.
        cap = _cap(o)
        if cap and _t(o["availability_expires_at"]) > cap:
            o["availability_expires_at"] = cap.strftime("%Y-%m-%dT%H:%M:%SZ"); n += 1
        live = [r for r in rows if r.get("region") not in (None, "all") and _grp(r) == g and not _exp(r, now)]
        ins = [r for r in live if _region_ok(r)]
        outs = [r for r in live if _out_confirmed(r)]
        # v3.4: the overall row always agrees with its regions: true only with a confirmed in-stock region; false only if every
        # live region is confirmed out of stock; otherwise null (unknown). Checked on every pass, not only when touched/expired.
        want = True if ins else (False if live and len(outs) == len(live) else None)
        # v3.4: Lambda lists no region rows when sold out; its overall false stands while unexpired if both reads saw zero capacity
        # v3.5: same for a Vast model with zero offers on both reads (it has no region rows)
        if want is None and not live and o.get("zero_capacity_two_reads") is True and o.get("in_stock") is False and not _exp(o, now): want = False
        if g not in touched and not _exp(o, now) and o.get("in_stock") is want: continue
        o["in_stock"] = want
        if "available_gpus" in o: o["available_gpus"] = sum(r.get("available_gpus") or 0 for r in ins) if ins else (0 if want is False else None)
        if ins:
            best = max(ins, key=lambda r: r["availability_expires_at"])
            o["checked_at"], o["availability_expires_at"] = best["checked_at"], best["availability_expires_at"]
        elif want is False and outs:  # false holds only while every out-of-stock claim holds
            o["checked_at"] = max(r["checked_at"] for r in outs); o["availability_expires_at"] = min(r["availability_expires_at"] for r in outs)
        elif want is False: pass  # Lambda two-read zero capacity: keeps its own (capped) claim fields
        else:
            o["checked_at"] = o["availability_expires_at"] = None
        o["overall_recomputed_at"] = c.NOW()
        o["availability_note"] = ("recomputed from unexpired region claims at overall_recomputed_at: in stock (confirmed region claim)" if want is True else
                                  "recomputed from unexpired region claims at overall_recomputed_at: no capacity on both reads in every region" if want is False else
                                  "unknown: no confirmed region claim at overall_recomputed_at")  # v3.5 (Gauge 4b): no 'out of stock' wording on unknown rows
        n += 1
    return n

_OOS = ("out of stock", "sold out")
def scrub_unknown_notes(rows):
    """v3.5 (Gauge 4b): a row marked unknown (in_stock None) must not carry 'out of stock' / 'sold out' wording in its notes or
    observations; such text is replaced (it described an earlier, now superseded reading). Returns count scrubbed."""
    n = 0
    for r in rows:
        if r.get("in_stock") is not None: continue
        for k, v in list(r.items()):
            if (k.endswith("note") or k.endswith("observation")) and isinstance(v, str) and any(p in v.lower() for p in _OOS):
                r[k] = "unknown: no current confirmed claim (earlier reading superseded)" if k.endswith("note") else None; n += 1
    return n
LAST_CLEARED = [0]  # v3.5e: unknown rows whose claim fields the last prune_and_rederive cleared
def prune_and_rederive(snap, enr, now=None, files=None):
    """v3.2: drop expired region rows, recompute region-derived overall rows, re-join the enriched feed from the pruned snapshot
    (local feed-src; in_live_feed kept from the previous enriched rows), then prune enriched region detail. Returns (snap, enr, changes)."""
    now = now or datetime.now(timezone.utc); LAST_CLEARED[0] = 0
    touched = {_grp(r) for r in snap["rows"] if r.get("region") not in (None, "all") and _exp(r, now)}
    snap = dict(snap, rows=[dict(r) for r in snap["rows"]])
    nre = rederive_overall(snap, touched, now)
    if files is None:
        src = e.SRC + "/data/gpu_pricing"
        files = [json.load(open(f)) for f in sorted(glob.glob(src + "/*.json"))] if os.path.isdir(src) else None
    new_rows = None
    if (touched or nre) and files and enr.get("rows"):
        try: new_rows, _ = e.enrich(files, snap, None)
        except Exception as ex:  # can't re-join (e.g. incomplete rows): keep old enriched rows; expiry checks still guard the push
            new_rows = None; enr = dict(enr, rejoin_error=f"{type(ex).__name__}: {ex}")
    if (touched or nre) and files and enr.get("rows") and new_rows is not None:
        k = lambda r: (r.get("vendor"), r.get("gpu"), r.get("vram_gb"), r.get("tier"))
        live = {k(r): r.get("in_live_feed") for r in enr["rows"]}
        old_keys = set(live)
        rows = [dict(r, in_live_feed=live.get(k(r))) for r in new_rows if k(r) in old_keys]
        enr = dict(enr, rows=rows)
    snap, enr, n = prune_expired(snap, enr, now)
    snap = dict(snap, rows=[dict(r) for r in snap["rows"]]); enr = dict(enr, rows=[dict(r) for r in enr.get("rows") or []])
    ns = scrub_unknown_notes(snap["rows"]) + scrub_unknown_notes(enr["rows"])  # v3.5 (Gauge 4b)
    LAST_CLEARED[0] = clear_unknown_claims(snap["rows"]) + clear_unknown_claims(enr["rows"])  # v3.5e (not counted as dropped claims)
    return snap, enr, n + nre + ns

def restat(enr):
    """Recompute stats (incl. region_conflicts) from the enriched rows; keep provenance keys from the previous stats."""
    old = enr.get("stats") or {}
    conflicts = [{"vendor": r["vendor"], "gpu": r["gpu"], "tier": r["tier"], "regions": r["region_conflicts"]} for r in enr["rows"] if r.get("region_conflicts")]
    st = e.compute_stats(enr["rows"], old.get("dropped_stale", []), conflicts)
    keep = {k: old[k] for k in ("feed_source", "live_feed_source", "live_feed_updated_at") if k in old}
    return dict(enr, stats={**keep, **st, "stats_recomputed_at": c.NOW()})

def stamp_freshness(snap, enr):
    rp = (snap.get("meta") or {}).get("runpod_refreshed_at")
    snap = dict(snap, runpod_refreshed_at=rp, freshness_note=FRESHNESS_NOTE)
    enr = dict(enr, snapshot_collected_at=snap.get("collected_at"), runpod_refreshed_at=rp, freshness_note=FRESHNESS_NOTE)
    return snap, enr

def expired_left(snap, enr, now=None):
    now = now or datetime.now(timezone.utc); bad = []
    def walk(x, path):
        if isinstance(x, dict):
            if _exp(x, now): bad.append((path, x["availability_expires_at"]))
            for k, y in x.items(): walk(y, f"{path}.{k}")
        elif isinstance(x, list):
            for i, y in enumerate(x): walk(y, f"{path}[{i}]")
    walk(snap, "availability_v2_latest.json$"); walk(enr, "feed_enriched_v2_latest.json$")
    return bad

def _csv_cell(v):
    if v is None: return ""
    if isinstance(v, bool): return str(v).lower()
    if isinstance(v, list): return ";".join(x if isinstance(x, str) else f"{x['region']}:{x['stock_level']}{'' if x.get('confirmed') else '?'}" for x in v)
    return v
MANIFEST = "latest_manifest.json"
LATEST = ("availability_v2_latest.json", "availability_v2_latest.csv", "feed_enriched_v2_latest.json", "feed_enriched_v2_latest.csv")
OPTIONAL = ("wider_gpu_prices_latest.json",)  # wider-gpu: optional extra file; listed in the manifest only when present and registered
def new_generation_id(): return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
def _sha(p):
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()
def sweep_tmp(out=OUT):
    """v3.1: remove stray temp files left by a killed writer (callers hold out/.scout.lock, so no live writer owns them)."""
    gone = []
    for p in glob.glob(os.path.join(out, ".*.tmp*")): os.remove(p); gone.append(os.path.basename(p))
    return gone
def write_latest(snap, enr, out=OUT, extra_snapshot_name=None, generation_id=None):
    """Write all four files + manifest to temp names, then rename (manifest last). Latest pair is only replaced after every
    temp file is complete; on any failure all temp files are removed. v3.1: both files and the manifest share generation_id."""
    gid = generation_id or new_generation_id()
    snap = dict(snap, generation_id=gid); enr = dict(enr, generation_id=gid)
    tmp = {}
    try:
        _write_all(snap, enr, out, extra_snapshot_name, tmp, gid)
    except BaseException:
        for p in tmp.values():
            if os.path.exists(p): os.remove(p)
        raise
    for name, p in tmp.items():
        if name != MANIFEST: os.replace(p, os.path.join(out, name))
    os.replace(tmp[MANIFEST], os.path.join(out, MANIFEST))
    return gid
def _write_all(snap, enr, out, extra_snapshot_name, tmp, gid):
    def put(name, writer):
        p = os.path.join(out, f".{name}.tmp.{os.getpid()}"); tmp[name] = p  # tracked before writing so a failed write is cleaned up
        with open(p, "w", newline="") as f: writer(f); f.flush(); os.fsync(f.fileno())
        tmp[name] = p
    put("availability_v2_latest.json", lambda f: json.dump(snap, f, indent=1))
    def snap_csv(f):
        w = csv.DictWriter(f, c.FIELDS); w.writeheader()
        for r in snap["rows"]: w.writerow({k: ("" if r.get(k) is None else str(r[k]).lower() if isinstance(r[k], bool) else r[k]) for k in c.FIELDS})
    put("availability_v2_latest.csv", snap_csv)
    put("feed_enriched_v2_latest.json", lambda f: json.dump(enr, f, indent=1))
    def enr_csv(f):
        rows = enr["rows"]; cols = list(dict.fromkeys(k for r in rows for k in r))  # T113: union of keys (old rows may lack additive fields)
        w = csv.DictWriter(f, cols, restval=""); w.writeheader()
        for r in rows: w.writerow({k: _csv_cell(v) for k, v in r.items()})
    put("feed_enriched_v2_latest.csv", enr_csv)
    if extra_snapshot_name: put(extra_snapshot_name, lambda f: json.dump(snap, f, indent=1))
    man = {"generation_id": gid, "written_at": c.NOW(), "collected_at": snap.get("collected_at"), "runpod_refreshed_at": snap.get("runpod_refreshed_at"),
           "files": {n: {"sha256": _sha(tmp[n])} for n in LATEST}}
    man["files"].update(_carry_optional(out))
    put(MANIFEST, lambda f: json.dump(man, f, indent=1))

def _carry_optional(out):
    """wider-gpu: keep an optional file's manifest entry only if the file is present AND still matches the sha registered before
    (never re-hash an unregistered/changed file here, that would launder it)."""
    keep = {}
    try: old = json.load(open(os.path.join(out, MANIFEST))).get("files", {})
    except (OSError, ValueError): old = {}
    for n in OPTIONAL:
        p = os.path.join(out, n); h = (old.get(n) or {}).get("sha256")
        if h and os.path.exists(p) and _sha(p) == h: keep[n] = {"sha256": h, "optional": True}
    return keep
def register_optional(name, out=OUT):
    """wider-gpu: called by wider_gpu.py right after it writes <name>; adds its sha256 to the manifest (atomic rename).
    generation_id and the four LATEST entries are left unchanged."""
    assert name in OPTIONAL, name
    mp = os.path.join(out, MANIFEST); man = json.load(open(mp))
    man.setdefault("files", {})[name] = {"sha256": _sha(os.path.join(out, name)), "optional": True}
    tmp = os.path.join(out, f".{MANIFEST}.tmp.{os.getpid()}")
    with open(tmp, "w") as f: json.dump(man, f, indent=1); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, mp)
def verify_generation(out=OUT):
    """v3.1: [] if both latest JSONs and the manifest carry the same generation_id and all four file hashes match the manifest."""
    probs = []
    mp = os.path.join(out, MANIFEST)
    if not os.path.exists(mp): return ["manifest missing"]
    man = json.load(open(mp)); gid = man.get("generation_id")
    for n in ("availability_v2_latest.json", "feed_enriched_v2_latest.json"):
        g = json.load(open(os.path.join(out, n))).get("generation_id")
        if g != gid: probs.append(f"{n} generation_id {g} != manifest {gid}")
    for n in LATEST:
        p = os.path.join(out, n)
        if not os.path.exists(p): probs.append(f"{n} missing")
        elif _sha(p) != (man.get("files", {}).get(n) or {}).get("sha256"): probs.append(f"{n} sha256 differs from manifest")
    for n in OPTIONAL:  # wider-gpu: missing = simply left out (no problem); present must be listed and match
        p = os.path.join(out, n); h = (man.get("files", {}).get(n) or {}).get("sha256")
        if not os.path.exists(p) or not h: continue  # rev 4: missing or unregistered -> not a problem here; screen_optional() sets it aside
        if _sha(p) != h: probs.append(f"{n} sha256 differs from manifest")  # registered but changed -> refuse (exit 3)
    return probs
OPTIONAL_MAX_AGE_H = 6
_SEQ = [0]
def _next(): _SEQ[0] += 1; return _SEQ[0]
def _tz(s):  # accepts ...Z and ...+00:00
    d = datetime.fromisoformat(s.replace("Z", "+00:00")); return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
def screen_optional(out=OUT, now=None):
    """rev 4: an optional file that is unregistered, unreadable, or whose verified_at/collected_at is older than OPTIONAL_MAX_AGE_H
    is renamed aside (never deleted) so the push leaves it out. Returns log lines. Registered+mismatched files are NOT handled here
    (verify_generation refuses them first)."""
    now = now or datetime.now(timezone.utc); logs = []
    try: files = json.load(open(os.path.join(out, MANIFEST))).get("files", {})
    except (OSError, ValueError): files = {}
    for n in OPTIONAL:
        p = os.path.join(out, n)
        if not os.path.exists(p): continue
        why = None
        if not (files.get(n) or {}).get("sha256"): why = "unregistered (not in manifest)"
        else:
            try:
                d = json.load(open(p)); ts = d.get("collected_at") or min(r["verified_at"] for r in d["rows"])
                age = (now - _tz(ts)).total_seconds() / 3600
                if age > OPTIONAL_MAX_AGE_H: why = f"older than {OPTIONAL_MAX_AGE_H}h ({age:.1f}h)"
            except Exception as ex: why = f"unreadable ({type(ex).__name__})"
        if why:
            dst = os.path.join(out, n.replace("_latest.json", "") + f"_SKIPPED_{now.strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}-{_next()}.json")
            os.replace(p, dst); logs.append(f"skip optional {n}: {why}; moved aside -> {os.path.basename(dst)}")
    return logs

def prepush(out=OUT, now=None):
    """Called by push_hook.sh on every push path. Prunes expired region claims, recomputes stats, rewrites atomically,
    then returns the list of expired claims still present (non-empty -> refuse)."""
    now = now or datetime.now(timezone.utc)
    sweep_tmp(out)
    def load(n):
        p = os.path.join(out, n); return json.load(open(p)) if os.path.exists(p) else None
    snap, enr = load("availability_v2_latest.json"), load("feed_enriched_v2_latest.json")
    both = snap is not None and enr is not None
    snap, enr = snap or {"rows": []}, enr or {"rows": []}
    snap, enr, n = prune_and_rederive(snap, enr, now) if both else prune_expired(snap, enr, now)
    if (n or (both and LAST_CLEARED[0])) and both:  # v3.5e: a cleared unknown-row expiry is also written back
        enr = restat(enr); snap, enr = stamp_freshness(snap, enr); write_latest(snap, enr, out)
    return n, expired_left(snap, enr, now)

if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else OUT
    # v3.3d: verify the matched set BEFORE prepush prunes/rewrites (a rewrite re-hashes the files and would launder a tampered one)
    try: probs = verify_generation(out)
    except Exception as ex: probs = [f"verify failed ({type(ex).__name__}: {ex})"]
    if probs:
        print("refuse push: latest files are not a matched set: " + "; ".join(probs)); sys.exit(3)
    for line in screen_optional(out): print(line)  # rev 4: unregistered/stale optional file is left out, the snapshot still pushes
    try: n, bad = prepush(out)
    except Exception as ex: print(f"refuse push: prepush failed ({type(ex).__name__}: {ex})"); sys.exit(3)
    if n: print(f"prepush: dropped {n} expired region claim(s), stats recomputed")
    probs = verify_generation(out)
    if probs:
        print("refuse push: latest files are not a matched set: " + "; ".join(probs)); sys.exit(3)
    if bad:
        print(f"refuse push: {len(bad)} availability_expires_at already in the past / availability_expires_at remain after pruning region claims (earliest {min(b[1] for b in bad)} at {min(bad, key=lambda b: b[1])[0]}); run a fresh cycle first")
        sys.exit(3)
    print(f"prepush ok: no expired claims; generation {json.load(open(os.path.join(out, MANIFEST)))['generation_id']} matched")
