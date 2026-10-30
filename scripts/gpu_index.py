#!/usr/bin/env python3
"""Lantern Works GPU Price Index (LWGPI) - reproducible computation.

Inputs (all public, in the repo connormatthewdouglas/agent-work-stack-deals):
  data/gpu_pricing/snapshots/YYYY-MM-DD.json   daily history (starts 2026-10-27)
  api/v1/gpu-prices.json at the last git commit of each snapshot date (for tier_class
  and marketplace listing counts, which snapshots do not carry)
Usage: python3 scripts/gpu_index.py <repo_dir> <out_dir>   (also run by scripts/generate_seo_pages.py)
Copied from Gauge's reference (T21). Mart's changes: published days are frozen (a day whose snapshot SHA-256 is
unchanged is reused from the committed api/v1/gpu-price-index.json, so shallow CI clones without git history give
the same output); the newest day falls back to the working-tree feed; public rows trimmed to key + reason.
No prices are typed in here; every number is read from those files.
"""
import json, os, re, subprocess, sys, statistics, csv, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from core.data_license import DATA_LICENSE  # noqa: E402

INDEX_GPUS = {  # series -> (accepted feed gpu names, vram_gb)
    "H100": ({"H100", "H100 SXM", "H100 PCIe", "H100 NVLink"}, 80),
    "A100": ({"A100", "A100 SXM", "A100 PCIe", "A100 NVLink"}, 80),
    "H200": ({"H200", "H200 SXM"}, 141),
    "L40S": ({"L40S"}, 48),
    "RTX 4090": ({"RTX 4090"}, 24),
    "RTX 5090": ({"RTX 5090"}, 32),
}
HOURS_PER_MONTH = 730
MIN_MARKETPLACE_LISTINGS = 5

EXCL_SPOT = re.compile(r"spot|interruptible|preempt|bid|batch|serverless", re.I)
EXCL_RESERVED = re.compile(r"reserv|month|dedicated|commit|\b\d+\s*mo\b", re.I)
MARKET = re.compile(r"marketplace|aggregator", re.I)

def classify(tier):
    if EXCL_SPOT.search(tier): return "spot/interruptible"
    if EXCL_RESERVED.search(tier): return "reserved/committed"
    if MARKET.search(tier): return "marketplace"
    return "on-demand"

def feed_at_date(repo, date):
    """api/v1/gpu-prices.json as of the last commit on <date> (ET), or None."""
    sha = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%H",
        f"--before={date} 23:59:59 -0400", "--", "api/v1/gpu-prices.json"],
        capture_output=True, text=True).stdout.strip()
    if not sha:
        p = os.path.join(repo, "api/v1/gpu-prices.json")
        return (json.load(open(p)), _head(repo)) if os.path.exists(p) else (None, None)
    blob = subprocess.run(["git", "-C", repo, "show", f"{sha}:api/v1/gpu-prices.json"],
        capture_output=True, text=True).stdout
    return json.loads(blob), sha

def _head(repo):
    """Sha of the last commit that touched api/v1/gpu-prices.json, if the working-tree feed is that exact blob (audit E9:
    a real, reproducible commit instead of 'working-tree'; independent of HEAD so the committed output stays stable)."""
    run = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True).stdout.strip()
    sha = run("log", "-1", "--format=%H", "--", "api/v1/gpu-prices.json")
    if sha and run("rev-parse", f"{sha}:api/v1/gpu-prices.json") == run("hash-object", "api/v1/gpu-prices.json"):
        return sha
    return "uncommitted"

def listing_counts(feed):
    out = {}
    for r in (feed or {}).get("rates", []):
        if r.get("offer_count") is not None:
            out[(r["advertiser"], r["gpu"], r.get("vram_gb"))] = r["offer_count"]
    return out

def series_of(row):
    for s, (names, vram) in INDEX_GPUS.items():
        if row["gpu"] in names and row.get("vram_gb") == vram: return s
    return None

def compute_day(repo, path, worktree=False):
    snap = json.load(open(path)); date = snap["date"]
    feed, sha = feed_at_date(repo, date) if not worktree else (json.load(open(os.path.join(repo, "api/v1/gpu-prices.json"))), _head(repo)); counts = listing_counts(feed)
    included, excluded = [], []
    for r in snap["rows"]:
        s = series_of(r)
        if not s: continue
        why = None
        if r["status"] != "ranked": why = "held"
        elif r.get("hourly_usd") is None: why = "no hourly price"
        else:
            c = classify(r["tier"])
            if c in ("spot/interruptible", "reserved/committed"): why = c
            elif c == "marketplace":
                n = counts.get((r["vendor"], r["gpu"], r.get("vram_gb")))
                if n is None: why = "marketplace, listing count unknown"
                elif n < MIN_MARKETPLACE_LISTINGS: why = f"thin marketplace ({n} listings)"
        rec = {"series": s, "key": r["key"], "vendor": r["vendor"], "tier": r["tier"],
               "hourly_usd": r.get("hourly_usd"), "source_url": r["source_url"],
               "verified_at": r["verified_at"]}
        (excluded if why else included).append({**rec, **({"excluded_because": why} if why else {})})
    out = {}
    for s in INDEX_GPUS:
        best = {}  # one vote per vendor: its lowest qualifying per-GPU-hour rate
        for r in included:
            if r["series"] == s and (r["vendor"] not in best or r["hourly_usd"] < best[r["vendor"]]):
                best[r["vendor"]] = r["hourly_usd"]
        vals = sorted(best.values())
        med = round(statistics.median(vals), 4) if vals else None
        out[s] = {"median_usd_per_gpu_hour": med,
                  "monthly_basis_usd": round(med * HOURS_PER_MONTH, 2) if med is not None else None,
                  "min_usd_per_gpu_hour": vals[0] if vals else None,
                  "vendors": len(vals), "vendor_prices": dict(sorted(best.items())),
                  "low_coverage": len(vals) < 3}
    return {"date": date, "snapshot_file": os.path.relpath(path, repo),
            "snapshot_sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
            "feed_commit_for_listing_counts": sha, "series": out,
            "rows_included": included, "rows_excluded": excluded}

def matched_change(prev, cur):
    """Median of the SAME vendors on both days: separates price moves from composition."""
    res = {}
    for s in INDEX_GPUS:
        a, b = prev["series"][s]["vendor_prices"], cur["series"][s]["vendor_prices"]
        common = sorted(set(a) & set(b))
        if not common: res[s] = None; continue
        ma = statistics.median(a[v] for v in common); mb = statistics.median(b[v] for v in common)
        res[s] = {"matched_vendors": len(common), "matched_median_prev": round(ma, 4),
                  "matched_median_cur": round(mb, 4),
                  "matched_change_pct": round((mb - ma) / ma * 100, 2) if ma else None,
                  "vendors_added": sorted(set(b) - set(a)), "vendors_dropped": sorted(set(a) - set(b))}
    return res

def _trim(day):
    day["rows_included"] = [r["key"] for r in day["rows_included"]]
    day["rows_excluded"] = [{"key": r["key"], "excluded_because": r["excluded_because"]} for r in day["rows_excluded"]]
    return day

def build(repo, outdir):
    sd = os.path.join(repo, "data/gpu_pricing/snapshots")
    prev_path = os.path.join(outdir, "gpu-price-index.json")
    frozen = {}
    if os.path.exists(prev_path):
        for d in json.load(open(prev_path)).get("history", []):
            d = dict(d); d.pop("vs_previous_day_matched", None); frozen[d["date"]] = d
    files = sorted(f for f in os.listdir(sd) if f.endswith(".json"))
    days = []
    for i, f in enumerate(files):
        path = os.path.join(sd, f)
        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
        old = frozen.get(f[:-5])
        last = i == len(files) - 1
        days.append(old if old and old["snapshot_sha256"] == h and not last else _trim(compute_day(repo, path, worktree=last or not os.path.isdir(os.path.join(repo, ".git")))))
    for i in range(1, len(days)): days[i]["vs_previous_day_matched"] = matched_change(days[i-1], days[i])
    return days

def main():
    return main_args(sys.argv[1], sys.argv[2])

def main_args(repo, outdir):
    os.makedirs(outdir, exist_ok=True)
    days = build(repo, outdir)
    for i in range(1, len(days)): days[i]["vs_previous_day_matched"] = matched_change(days[i-1], days[i])
    meta = {"name": "Lantern Works GPU Price Index", "version": "1.0",
            "license": "CC-BY-4.0", "attribution": "Lantern Works GPU Price Index (https://thelanternworks.com), CC BY 4.0",
            "unit": "USD per GPU-hour, on-demand-class tiers, median across vendors (one rate per vendor)",
            "hours_per_month": HOURS_PER_MONTH, "min_marketplace_listings": MIN_MARKETPLACE_LISTINGS,
            "history_starts": days[0]["date"] if days else None, "days": len(days),
            "method": "https://thelanternworks.com/gpu/index/methodology/",
            "series_vram_gb": {s: v for s, (_, v) in INDEX_GPUS.items()},  # one memory size per series (A100 = 80 GB only; 40 GB never mixed)
            "license_terms": DATA_LICENSE}
    json.dump({**meta, "history": days}, open(os.path.join(outdir, "gpu-price-index.json"), "w"), indent=1)
    with open(os.path.join(outdir, "gpu-price-index.csv"), "w", newline="") as f:
        f.write(f"# {meta['attribution']}. Data license: {DATA_LICENSE['data_license_url']}. Methodology: {meta['method']}\n")
        w = csv.writer(f); w.writerow(["date", "gpu", "median_usd_per_gpu_hour", "monthly_basis_usd_730h",
                                       "min_usd_per_gpu_hour", "vendors", "low_coverage", "matched_change_pct_vs_prev_day", "matched_vendors"])
        for d in days:
            for s, v in d["series"].items():
                m = (d.get("vs_previous_day_matched") or {}).get(s) or {}
                w.writerow([d["date"], s, v["median_usd_per_gpu_hour"], v["monthly_basis_usd"], v["min_usd_per_gpu_hour"],
                            v["vendors"], v["low_coverage"], m.get("matched_change_pct"), m.get("matched_vendors")])
    return days

if __name__ == "__main__": main()
