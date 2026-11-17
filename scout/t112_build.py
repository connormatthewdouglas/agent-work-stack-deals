"""T112 (Scout side): per vendor/model/tier observed in-stock share over trailing 7d of Scout snapshots. Read-only on history.
P38 (additive): never_ran_checks_7d / no_source_checks_7d split unknown checks by each check's recorded T113
availability_reason. Both are null when any unknown check in the window has no recorded reason (never a guessed split).
Counts use only real snapshot files present in the window (snapshots_used / first_check_at / last_check_at); nothing is padded.

Snapshots come from out/availability_v2_*.json and, when present, the P42 probe archive
(out/probe_archive/*.jsonl.gz) and scout-data history/probes (same jsonl.gz layout). The same
captured check is counted once (deduped by source_file, else by collected_at). No backfill
or interpolation. LW_AVAIL_NOW pins the window clock.
"""
import json, glob, collections, os, sys, gzip
from datetime import datetime, timezone, timedelta

# Same T113 split as scripts/availability_rate_7d.py (#199): failed/stale = never ran; no_source = probe ran, no signal.
UNKNOWN_SPLIT = {"check_failed_timeout": "never_ran_checks_7d", "check_failed_http": "never_ran_checks_7d",
                 "stale": "never_ran_checks_7d", "no_source": "no_source_checks_7d"}


def _now_utc(now=None):
    """Window/generated_at clock: explicit now, else LW_AVAIL_NOW, else wall clock."""
    if now is not None:
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    v = os.environ.get("LW_AVAIL_NOW")
    if v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            d = None
        if d is not None:
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _parse_ts(ts):
    if not isinstance(ts, str) or not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _check_key(source_file, collected_at):
    """Identity of one captured check: the availability_v2 source filename, else collected_at."""
    name = os.path.basename(source_file or "")
    if name.startswith("availability_v2_") and name.endswith(".json"):
        return "file:" + name
    if collected_at:
        return "at:" + collected_at
    return None


def _rejected_name(name):
    return any(tag in (name or "") for tag in ("FAILED", "BROKEN", "REJECTED", "SKIPPED"))


def _snapshot(d, source_file=None):
    """A real captured check: parseable collected_at and a rows list. None if unusable."""
    if not isinstance(d, dict):
        return None
    if d.get("ok") is False:
        return None
    src = source_file or d.get("source_file") or ""
    if _rejected_name(src) or _rejected_name(os.path.basename(src)):
        return None
    t = _parse_ts(d.get("collected_at"))
    if t is None or not isinstance(d.get("rows"), list):
        return None
    key = _check_key(src, d["collected_at"])
    if not key:
        return None
    return {"key": key, "collected_at": t, "ts": d["collected_at"], "generation_id": d.get("generation_id"),
            "rows": d["rows"], "source_file": src}


def _reason_index(src):
    """Recorded reasons from dated enriched archives and latest, keyed by generation_id then collected_at."""
    by_gid, by_collected = {}, {}
    paths = glob.glob(src+"/feed_enriched_v2_2026*.json") + glob.glob(src+"/feed_enriched_v2_latest.json")
    for f in paths:
        if _rejected_name(f):
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        idx = {}
        for r in d.get("rows") or []:
            reason = r.get("availability_reason")
            if not reason:
                continue
            idx[(r.get("vendor"), r.get("gpu") or r.get("gpu_model"), r.get("vram_gb"), r.get("tier"))] = reason
        if not idx:
            continue
        gid, collected = d.get("generation_id"), d.get("snapshot_collected_at") or d.get("collected_at")
        if gid:
            by_gid[gid] = idx
        if collected:
            by_collected[collected] = idx
    return by_gid, by_collected


def _reason_for(r, snap, by_gid, by_collected):
    if r.get("availability_reason"):
        return r.get("availability_reason")
    idx = by_gid.get(snap.get("generation_id")) or by_collected.get(snap["ts"] if isinstance(snap, dict) and "ts" in snap else snap.get("collected_at")) or {}
    return idx.get((r.get("vendor"), r.get("gpu_model") or r.get("gpu"), r.get("vram_gb"), r.get("tier")))


def _archive_latest_enriched(src):
    """Copy feed_enriched_v2_latest.json to feed_enriched_v2_<generation_id>.json so T113 reasons survive the next enrich. Never overwrites."""
    latest = os.path.join(src, "feed_enriched_v2_latest.json")
    if not os.path.isfile(latest):
        return
    try:
        d = json.load(open(latest))
    except Exception:
        return
    gid = d.get("generation_id")
    if not gid or any(x in str(gid) for x in ("FAILED", "BROKEN", "/", "..")):
        return
    dest = os.path.join(src, f"feed_enriched_v2_{gid}.json")
    if os.path.exists(dest):
        return
    tmp = dest + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dest)


def _archive_dirs(src):
    """P42 probe_archive and scout-data history/probes, plus SCOUT_PROBE_ARCHIVE if set."""
    parent = os.path.dirname(os.path.abspath(src))
    dirs = [
        os.path.join(src, "probe_archive"),
        os.path.join(src, "history", "probes"),
        os.path.join(parent, "history", "probes"),
        os.path.join(parent, "probe_archive"),
    ]
    extra = os.environ.get("SCOUT_PROBE_ARCHIVE")
    if extra:
        dirs.append(extra)
    seen, out = set(), []
    for d in dirs:
        ap = os.path.abspath(d)
        if ap not in seen and os.path.isdir(d):
            seen.add(ap)
            out.append(d)
    return out


def _load_snapshots(src):
    """Unique real captured checks from out/ JSON and any present probe archives."""
    found = {}
    for f in sorted(glob.glob(src + "/availability_v2_2026*.json")):
        if _rejected_name(os.path.basename(f)):
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        snap = _snapshot(d, source_file=os.path.basename(f))
        if snap:
            found.setdefault(snap["key"], snap)
    for archive in _archive_dirs(src):
        for f in sorted(glob.glob(archive + "/*.jsonl.gz") + glob.glob(archive + "/*.jsonl")):
            if _rejected_name(os.path.basename(f)):
                continue
            opener = gzip.open if f.endswith(".gz") else open
            try:
                fh = opener(f, "rt")
            except Exception:
                continue
            with fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    snap = _snapshot(d, source_file=d.get("source_file") if isinstance(d, dict) else None)
                    if snap:
                        found.setdefault(snap["key"], snap)
    return sorted(found.values(), key=lambda s: (s["collected_at"], s["key"]))


def build(src=None, days=7, now=None):
    src = src or os.path.join(os.environ.get("SCOUT_DIR") or os.path.dirname(os.path.abspath(__file__)), "out")
    now = _now_utc(now)
    cut = now - timedelta(days=days)
    by_gid, by_collected = _reason_index(src)
    agg = collections.defaultdict(lambda: {"checks": 0, "in_stock": 0, "out_of_stock": 0, "unknown": 0,
        "never_ran_checks_7d": 0, "no_source_checks_7d": 0, "_unclassified": 0, "first": None, "last": None, "last_known": None})
    n = 0
    for snap in _load_snapshots(src):
        if snap["collected_at"] < cut:
            continue
        n += 1
        for r in snap["rows"]:
            if r.get("region") != "all":
                continue
            a = agg[(r["vendor"], r["gpu_model"], r["vram_gb"], r["tier"])]
            a["checks"] += 1
            s = r.get("in_stock")
            a["in_stock" if s is True else "out_of_stock" if s is False else "unknown"] += 1
            if s is None:
                bucket = UNKNOWN_SPLIT.get(_reason_for(r, snap, by_gid, by_collected))
                a[bucket if bucket else "_unclassified"] += 1
            ts = r.get("collected_at") or snap["ts"]
            a["first"] = a["first"] or ts
            a["last"] = ts
            if s is not None:
                a["last_known"] = ts
    rows = []
    for k, a in sorted(agg.items(), key=lambda x: tuple(str(v) for v in x[0])):
        known = a["in_stock"] + a["out_of_stock"]
        if a["_unclassified"]:
            never_ran = no_source = None  # cannot split without a reason on every unknown check
        else:
            never_ran, no_source = a["never_ran_checks_7d"], a["no_source_checks_7d"]
        rows.append(dict(zip(("vendor", "gpu_model", "vram_gb", "tier"), k), checks_7d=a["checks"], known_checks_7d=known,
            in_stock_checks_7d=a["in_stock"],
            availability_rate_7d=round(a["in_stock"] / known, 3) if known else None, known_share_7d=round(known / a["checks"], 3),
            first_check_at=a["first"], last_check_at=a["last"], last_known_at=a["last_known"], sufficient_sample=known >= 12,
            never_ran_checks_7d=never_ran, no_source_checks_7d=no_source))
    _archive_latest_enriched(src)
    return {"version": "3.2", "kind": "t112_availability_rate_inputs", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": f"trailing {days}d of Scout snapshots (overall region='all' rows; 4h cycles + multi refreshes; unknown checks excluded from the rate)",
        "snapshots_used": n, "join_key": "vendor, gpu_model, vram_gb, tier (snapshot keys; feed join via enrich_feed_v2.key())", "rows": rows}


if __name__ == "__main__":
    doc = build()
    json.dump(doc, open(sys.argv[1] if len(sys.argv) > 1 else "out/t112_availability_rate_7d.json", "w"), indent=1)
    rs = doc["rows"]
    print(doc["snapshots_used"], len(rs), sum(r["availability_rate_7d"] is not None for r in rs), sum(r["sufficient_sample"] for r in rs))
