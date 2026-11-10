"""Add region/in_stock/offer_count/refresh_rate to existing feed rows (H100/A100/RTX 4090). Writes a copy; repo untouched."""
import json, glob, os
FEED = "/workspace/agent-deals-feed/repo/data/gpu_pricing"
av = json.load(open("out/availability_latest.json"))["rows"]
def match(vendor, gpu, tier):
    for a in av:
        if a["vendor"] != vendor or a["region"] != "all": continue
        g = a["gpu_model"]
        if not (gpu == g or (gpu in ("H100", "A100") and g.startswith(gpu + " SXM")) ): continue
        if vendor == "RunPod" and a["tier"].split("(")[1].split()[0] not in tier: continue
        return a
out, stats = [], {"rows": 0, "enriched": 0}
for f in sorted(glob.glob(FEED + "/*.json")):
    d = json.load(open(f))
    for r in d["records"]:
        if not any(k in r["gpu"] for k in ("H100", "A100", "4090")): continue
        stats["rows"] += 1
        a = match(d["vendor"], r["gpu"], r["tier"]) if r.get("vram_gb", 80) in (80, 24, None) else None
        marketplace = r.get("price_status") == "marketplace" or "Spot" in r["tier"] or "Marketplace" in r["tier"]
        e = dict(region=None, region_note="not published by this source / not collected", in_stock="unknown", offer_count=None,
                 stock_level=None, availability_source=None, availability_checked_at=None,
                 refresh_rate="4h (marketplace/spot)" if marketplace else "daily (list price)")
        if a:
            stats["enriched"] += 1
            regs = sorted({x["region"] for x in av if x["vendor"] == a["vendor"] and x["gpu_model"] == a["gpu_model"] and x["region"] != "all" and x["in_stock"] is True})
            e.update(region="multi", region_note=("in-stock Secure Cloud DCs: " if a["vendor"]=="RunPod" else "in-stock regions: ") + (", ".join(map(str, regs)) or "none"), in_stock=a["in_stock"],
                     offer_count=a["offer_count"], stock_level=a["stock_level"], availability_source=a["source_url"], availability_checked_at=a["collected_at"])
        out.append({"vendor": d["vendor"], "gpu": r["gpu"], "tier": r["tier"], "hourly_usd": r["hourly_usd"], "price_source_url": r["source_url"], **e})
json.dump({"stats": stats, "rows": out}, open("out/feed_enriched_latest.json", "w"), indent=1)
print(stats)
