"""v3.0: Oblivus joined (per-location available_gpus); Vast/Oblivus detail carries offer/GPU counts from both reads.
v2.9: available_regions = regions confirmed by two reads only; detail lists all in-stock regions with confirmation (two_reads/single_read).
v2.8: per-region checked_at/expires(+1h)/confirmed in available_regions_detail, region conflicts recorded, stock_level_scope.
v2.7: checked_at/source/availability_expires_at passed through; available_regions only when in_stock non-null; available_regions_detail.
v2.6: RunPod per-data-center, cloud-typed in-stock regions now fill available_regions.
v2.5: add availability to current feed rows (H100/A100/RTX 4090). Repo untouched; stale vendors dropped.
Join key: (vendor, gpu exact, vram_gb, cloud tier for RunPod / Verda spot / Lambda GPU count, region='all').
Clore.ai: the collector's unrented_servers is copied to `unrented_servers` only, never to offer_count (feed offer_count = USD listings).
Each row is tagged in_live_feed: present in the published https://thelanternworks.com/api/v1/gpu-prices.json `rates`, or repo-only."""
import json, glob, csv, os, subprocess, sys, urllib.request
from datetime import datetime, timezone, timedelta
SRC = os.path.join(os.environ.get("SCOUT_DIR") or os.path.dirname(os.path.abspath(__file__)), "feed-src")  # v3.1
REPO = "https://github.com/connormatthewdouglas/agent-work-stack-deals.git"
LIVE = "https://thelanternworks.com/api/v1/gpu-prices.json"  # public, read-only GET
GPUS = ("H100", "A100", "4090")

def norm_vendor(v): return "Verda" if v.startswith("Verda") else v
def key(vendor, gpu, vram, tier):
    vendor = norm_vendor(vendor)
    t = ("Secure" if "Secure" in tier else "Community" if "Community" in tier else None) if vendor == "RunPod" else ("Spot" if "Spot" in tier else "On-demand") if vendor == "Verda" \
        else (tier.split("(")[-1].split("x")[0] if "x GPU)" in tier else "?") if vendor == "Lambda" \
        else (tier if tier == "On-demand" else "?" + tier) if vendor == "CloudRift" \
        else (tier if tier in ("On-demand", "Spot VM") else "?" + tier) if vendor == "Hyperstack" \
        else (tier if tier == "On-demand" else "?" + tier) if vendor == "Novita AI" \
        else (tier if tier == "On-demand" else "?" + tier) if vendor == "Thunder Compute" else None  # Lambda: GPU count; T73 CloudRift: on-demand only (commitment tiers never joined)
    return (vendor, gpu, vram, t)
PRICE_GATED = ("Hyperstack", "Novita AI", "Thunder Compute")
def price_gate_ok(feed, snap):
    """T73 rev4: claim attaches only if the snapshot carries an API price within $0.005 of the feed price and VRAM matches exactly."""
    fp, sp = feed.get("hourly_usd"), snap.get("price_usd_hr")
    return (feed.get("vram_gb") is not None and feed.get("vram_gb") == snap.get("vram_gb")
            and isinstance(fp, (int, float)) and isinstance(sp, (int, float)) and abs(sp - fp) < 0.005)
def live_key(vendor, gpu, vram, tier): return (norm_vendor(vendor), gpu, vram, tier)

def fetch_live_keys(url=LIVE):
    """Set of live_key for every published rate, or None if the live feed can't be read (then rows are 'unknown')."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LanternWorks-Scout/0.2 (+https://thelanternworks.com)"})
        with urllib.request.urlopen(req, timeout=40) as r: d = json.load(r)
        return {live_key(x.get("advertiser") or "", x.get("gpu"), x.get("vram_gb"), x.get("tier") or "") for x in d["rates"]}, d.get("feed_updated_at")
    except Exception as e:
        print("live feed unreadable:", type(e).__name__, file=sys.stderr); return None, None

def compute_stats(out, dropped, conflicts):
    """v3.0: stats from enriched rows alone, so a refresh/prune can recompute them."""
    def split(rows):
        return {"live_feed": sum(1 for r in rows if r.get("in_live_feed") is True), "repo_only": sum(1 for r in rows if r.get("in_live_feed") is False),
                "live_feed_unknown": sum(1 for r in rows if r.get("in_live_feed") is None)}
    wa = [r for r in out if r.get("availability_source")]
    stats = {"region_conflicts": conflicts, "current_rows": len(out), "current_rows_split": split(out), "dropped_stale": dropped,
             "with_availability": len(wa), "with_availability_split": split(wa),
             "in_stock_true": sum(1 for r in out if r.get("in_stock") is True), "in_stock_true_split": split([r for r in out if r.get("in_stock") is True]),
             "in_stock_false": sum(1 for r in out if r.get("in_stock") is False), "in_stock_false_split": split([r for r in out if r.get("in_stock") is False]),
             "repo_only_rows": [f"{r.get('vendor')} {r.get('gpu')} {r.get('vram_gb')}GB | {r.get('tier')}" for r in out if r.get("in_live_feed") is False]}
    return stats

REGIONS_LABEL = ("seen in stock at check time; available_regions lists only regions confirmed in stock by two reads; "
                 "available_regions_detail also lists single-read and unconfirmed regions (see confirmation/confirmed)")
REGION_TTL = timedelta(hours=1)  # region readings flip minute to minute; row-level claims keep 8h (v3.5c: never for Clore, Vast: 1h)
def _plus(ts, td):
    return None if not ts else (datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") + td).strftime("%Y-%m-%dT%H:%M:%SZ")
def is_clore(v):
    """v3.5e (Gauge): vendor match is case-insensitive ('Clore.ai', 'clore', 'CLORE.AI')."""
    return isinstance(v, str) and v.strip().lower() in ("clore", "clore.ai")
def _clore_region_ok(x):
    """v3.5d (Gauge re34 tamper): a Clore region counts only if confirmed is True, confirmation == 'two_reads',
    second_read_unrented_servers > 0 and second_read_at - collected_at >= 60s. Anything else -> unconfirmed (in_stock null).
    Clore-only: other vendors carry no second_read_unrented_servers, so applying it to them would change their live output."""
    try:
        return (x.get("in_stock") is True and x.get("confirmed") is True and x.get("confirmation") == "two_reads"
                and type(x.get("second_read_unrented_servers")) is int and x["second_read_unrented_servers"] > 0  # v3.5e: bool True is not a count
                and (datetime.strptime(x["second_read_at"], "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(x["collected_at"], "%Y-%m-%dT%H:%M:%SZ")).total_seconds() >= 60)
    except (KeyError, TypeError, ValueError):
        return False
# T113 (additive, schema stays 3.2): machine-readable reason beside availability. availability_reason uses the canonical Brain
# enum (in_stock / out_of_stock / check_failed_timeout / check_failed_http / stale / no_source); availability_reason_detail is finer
# (ssl_error, http_403, http_<code>, timeout, network_error, backoff, second_read_failed, price_gate_mismatch, api_null_signal,
# unconfirmed_two_reads, no_matching_api_row, no_api, collector_error). Reasons never change in_stock: every non-stock reason is still unknown (T66 rule).
REASONS = ("in_stock", "out_of_stock", "check_failed_timeout", "check_failed_http", "stale", "no_source")
COLLECTED = {"Vast.ai": "vast", "RunPod": "runpod", "Verda": "verda", "Clore.ai": "clore", "Lambda": "lambda", "Oblivus": "oblivus",
             "CloudRift": "CloudRift", "Hyperstack": "Hyperstack", "Novita AI": "Novita AI", "Thunder Compute": "Thunder Compute"}
def classify_error(msg):
    m = (msg or "").lower()
    if "backoff" in m: return "stale", "backoff"
    if "second read failed" in m: return "check_failed_http", "second_read_failed"
    if "ssl" in m: return "check_failed_http", "ssl_error"
    if "timeout" in m or "timed out" in m: return "check_failed_timeout", "timeout"
    import re
    x = re.search(r"(?:http error |http |code[= ]?|\b)([45]\d\d)\b", m)
    if x: return "check_failed_http", "http_" + x.group(1)
    if "urlerror" in m or "connection" in m or "remotedisconnected" in m: return "check_failed_http", "network_error"
    return "check_failed_http", "collector_error"
def availability_reason(row, vendor, snap, matched=True, gate=None, now=None, snap_row=None):
    if row.get("in_stock") is True or row.get("in_stock") is False:
        exp = row.get("availability_expires_at"); now = now or datetime.now(timezone.utc)
        if isinstance(exp, str) and datetime.strptime(exp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= now: return "stale", "claim_expired"
        return ("in_stock", None) if row["in_stock"] else ("out_of_stock", None)
    v = "Clore.ai" if is_clore(vendor) else norm_vendor(vendor)
    if v not in COLLECTED: return "no_source", "no_api"
    meta = snap.get("meta") or {}; ek = COLLECTED[v]
    E, N = snap.get("errors") or {}, meta.get("nonfatal_errors") or {}
    err = E.get(ek) or E.get(v) or N.get(ek) or N.get(v)
    if err: return classify_error(err)
    if any(x.get("source") == v for x in meta.get("second_read_log") or []): return "check_failed_http", "second_read_failed"
    if gate: return "no_source", gate
    if matched and (snap_row or {}).get("overall_recomputed_at"): return "no_source", "unconfirmed_two_reads"  # nulled: no two-read confirmation
    if matched: return "no_source", "api_null_signal"  # vendor API answered but gave no stock status (or reads disagreed)
    return "no_source", "no_matching_api_row"
def enrich(vendor_files, snap, live_keys):
    """vendor_files: list of feed vendor dicts (data/gpu_pricing/*.json). Pure: no I/O."""
    av = snap["rows"]; QUERIED = snap.get("meta", {}).get("queried", {})
    agg = {key(a["vendor"], a["gpu_model"], a["vram_gb"], a["tier"]): a for a in av if a["region"] == "all"}
    out, dropped = [], []; CONFLICTS = []
    import vendor_overrides as _vo; _OV = _vo.load_vendor_overrides()
    for d in vendor_files:
        for r in d["records"]:
            if not any(k in r["gpu"] for k in GPUS): continue
            if d.get("stale"): dropped.append(f"{d['vendor']} {r['gpu']}"); continue
            mk = r.get("price_status") == "marketplace" or any(w in r["tier"] for w in ("Spot", "Marketplace", "preemptible", "interruptible"))
            a = agg.get(key(d["vendor"], r["gpu"], r.get("vram_gb"), r["tier"])); _gate = None  # T113
            if a and norm_vendor(d["vendor"]) == "CloudRift" and not (r.get("vram_gb") == 80 and a.get("vram_gb") == 80 and a.get("price_usd_hr") is not None
                                                                and abs(a["price_usd_hr"] - (r.get("hourly_usd") or -1)) < 0.005):
                a, _gate = None, "price_gate_mismatch"  # T73 (Gauge fix 3): tier is inferred; attach only if API cost_per_hour/100 == feed price and VRAM 80 GB
            if a and norm_vendor(d["vendor"]) in PRICE_GATED and not price_gate_ok(r, a):
                a, _gate = None, "price_gate_mismatch"  # T73 rev4: Hyperstack (pricebook), Novita, Thunder: API price within $0.005 of feed price AND exact VRAM match
            lk = live_key(d["vendor"], r["gpu"], r.get("vram_gb"), r["tier"])
            row = {"vendor": d["vendor"], "gpu": r["gpu"], "vram_gb": r.get("vram_gb"), "tier": r["tier"], "hourly_usd": r["hourly_usd"],
                   "price_source_url": r["source_url"], "price_checked_at": r.get("checked_at"),
                   "in_live_feed": None if live_keys is None else lk in live_keys,
                   "region": None, "available_regions": None, "in_stock": None, "offer_count": None, "unrented_servers": None, "stock_level": None,
                   "availability_snapshot_price_usd": None, "availability_source": None, "availability_checked_at": None,
                   "price_refresh": "4h" if mk else "daily", "availability_refresh": "4h", "vram_note": None, "availability_note": None, "availability_source_type": None, "availability_observation": None,
                   "available_gpus": None, "available_regions_detail": None, "available_regions_label": None, "region_conflicts": None, "stock_level_scope": None, "checked_at": None, "source": None, "availability_expires_at": None}
            if a:
                regx = sorted((x for x in av if x["vendor"] == a["vendor"] and (a["vendor"] in ("Vast.ai", "Verda", "Lambda", "Clore.ai", "RunPod", "Oblivus", "CloudRift", "Hyperstack", "Novita AI", "Thunder Compute") or is_clore(a["vendor"])) and x["tier"] == a["tier"] and x.get("in_stock") is True and x["region"] is not None and x["gpu_model"] == a["gpu_model"]
                              and x["vram_gb"] == a["vram_gb"] and x["region"] != "all"), key=lambda x: x["region"])
                if is_clore(a["vendor"]): regx = [x for x in regx if _clore_region_ok(x)]  # v3.5d: failing regions are unconfirmed -> not listed
                det = [{"region": x["region"], "stock_level": x.get("stock_level"), "checked_at": x.get("collected_at"),
                        "availability_expires_at": x.get("availability_expires_at") or _plus(x.get("collected_at"), REGION_TTL), "confirmed": x.get("confirmed"),
                        "confirmation": x.get("confirmation") or "single_read", "second_read_stock_level": x.get("second_read_stock_level"),
                        **{k_: x[k_] for k_ in ("offer_count", "available_gpus", "second_read_offer_count", "second_read_available_gpus") if x.get(k_) is not None}} for x in regx]
                if a["in_stock"] is None and det:  # v2.8: overall unknown but a region reads in stock -> conflict, recorded not dropped
                    row["region_conflicts"] = [dict(d_, conflict=True, aggregate_in_stock=None) for d_ in det]
                    CONFLICTS.append({"vendor": d["vendor"], "gpu": r["gpu"], "tier": r["tier"], "regions": row["region_conflicts"]})
                    det = []  # v2.7 rule: no region list under an unknown overall in_stock
                regs = [x_["region"] for x_ in det if x_["confirmed"] is True]  # v2.9: only two-read confirmed regions
                row.update(available_regions_detail=det or None, available_regions_label=REGIONS_LABEL if det else None,
                           stock_level_scope="aggregate" if a.get("stock_level") is not None else None,
                           checked_at=a.get("checked_at"), source=a.get("source"), availability_expires_at=a.get("availability_expires_at"))
                clore = is_clore(a["vendor"])
                row.update(region="all", available_regions=regs or None, in_stock=a["in_stock"],
                           offer_count=None if clore else a.get("offer_count"),  # never copy a Clore count into offer_count
                           unrented_servers=a.get("unrented_servers") if clore else None, available_gpus=a.get("available_gpus"), stock_level=a["stock_level"],
                           availability_snapshot_price_usd=a["price_usd_hr"], availability_source=a["source_url"], availability_checked_at=a["collected_at"], availability_refresh=a.get("availability_refresh") or "4h", availability_note=a.get("availability_note"), availability_source_type=a.get("source"), availability_observation=a.get("observation"))
                if clore:  # v3.5c (Gauge QA 20261030T222314Z): no in_stock=True without a two-read confirmed region; claim <= checked_at + 1h (was +8h)
                    if row["in_stock"] is True and not regs:
                        row.update(in_stock=None, available_regions_detail=None, available_regions_label=None, availability_observation="no host region confirmed in stock on two reads; in_stock unknown")  # v2.7 rule: no region list under unknown in_stock
                    cap = _plus(row["checked_at"] or a.get("collected_at"), REGION_TTL)
                    if cap and (not row["availability_expires_at"] or row["availability_expires_at"] > cap): row["availability_expires_at"] = cap
                    for d_ in row["available_regions_detail"] or []:  # v3.5d: each region claim <= its checked_at + 1h, and never past the row's cap
                        rc = min(x_ for x_ in (_plus(d_.get("checked_at"), REGION_TTL), cap) if x_) if (d_.get("checked_at") or cap) else None
                        if rc and (not d_.get("availability_expires_at") or d_["availability_expires_at"] > rc): d_["availability_expires_at"] = rc
                if row["in_stock"] is None:  # v3.5e: unknown makes no claim -> no checked_at/expiry (same as derived rows), so none can expire unseen
                    row.update(checked_at=None, availability_expires_at=None)
            q = QUERIED.get(f"{d['vendor']}|{r['gpu']}")
            if not a and d["vendor"] == "Vast.ai" and q and not snap.get("errors"):  # observed zero at this VRAM
                row.update(region="all", in_stock=False, offer_count=0, availability_source=q["source_url"], availability_checked_at=q["queried_at"],
                           availability_note=f"0 verified rentable offers at {r.get('vram_gb')} GB in this snapshot",
                           checked_at=q["queried_at"], source="public no-auth API", availability_expires_at=(datetime.strptime(q["queried_at"], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))  # v3.5 (Gauge 3): 1h, like other Vast overall claims
            _vo.apply_vendor_overrides(row, _OV)  # CloudRift 2026-11-04: vendor_overrides.json (additive; may null hourly_usd)
            row.update(zip(("availability_reason", "availability_reason_detail"), availability_reason(row, d["vendor"], snap, matched=a is not None, gate=_gate, snap_row=a)))  # T113 (additive)
            row["availability_status"] = "in_stock" if row["in_stock"] is True else "out_of_stock" if row["in_stock"] is False else "unknown"  # T112 ask (a): tri-state, failed check = unknown
            out.append(row)
    stats = compute_stats(out, dropped, CONFLICTS)
    return out, stats

if __name__ == "__main__":
    if os.path.isdir(SRC + "/.git"):
        subprocess.run(["git", "-C", SRC, "fetch", "--depth", "1", "-q", "origin", "main"], check=True)
        subprocess.run(["git", "-C", SRC, "reset", "--hard", "-q", "origin/main"], check=True)  # scratch clone only
    else:
        subprocess.run(["git", "clone", "--depth", "1", "-q", REPO, SRC], check=True)
    FEED_COMMIT = subprocess.run(["git", "-C", SRC, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    SNAP_PATH = "out/availability_v2_staged.json" if os.path.exists("out/availability_v2_staged.json") else "out/availability_v2_latest.json"
    SNAP = json.load(open(SNAP_PATH))
    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(SNAP["collected_at"].replace("Z", "+00:00"))).total_seconds() / 3600
    if age_h > 8: sys.exit(f"snapshot is {age_h:.1f}h old (>8h = 2x cadence); refusing to enrich")
    files = [json.load(open(f)) for f in sorted(glob.glob(SRC + "/data/gpu_pricing/*.json"))]
    live_keys, live_updated = fetch_live_keys()
    out, stats = enrich(files, SNAP, live_keys)
    stats = {"feed_source": f"{REPO}@{FEED_COMMIT}", "live_feed_source": LIVE, "live_feed_updated_at": live_updated, **stats}
    import scout_io
    snap_o, enr_o = scout_io.stamp_freshness(SNAP, {"version": "3.2", "stats": stats, "rows": out})
    scout_io.write_latest(snap_o, enr_o)  # v3.0: all four latest files via temp + rename, after all are written
    if SNAP_PATH.endswith("_staged.json"): os.remove(SNAP_PATH)
    print(json.dumps(stats, indent=1))
