"""Lantern Scout collectors: region / in_stock / offer_count for H100, A100, RTX 4090.
Public no-auth endpoints only. Unknown stays null/'unknown'."""
import json, csv, sys, time, statistics, urllib.request, urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
UA = "LanternWorks-Scout/0.1 (+https://thelanternworks.com)"
NOW = lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
FIELDS = ["vendor","gpu_model","tier","region","in_stock","offer_count","stock_level","price_usd_hr","price_basis","source_url","collected_at","refresh_rate"]

def get(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r: return json.load(r)

VAST = {"H100 SXM": "H100 SXM", "H100 PCIe": "H100 PCIE", "A100 SXM": "A100 SXM4", "A100 PCIe": "A100 PCIE", "RTX 4090": "RTX 4090"}
def vast():
    rows = []
    for model, name in VAST.items():
        q = {"gpu_name": {"eq": name}, "rentable": {"eq": True}, "rented": {"eq": False}, "verified": {"eq": True}, "type": "on-demand", "limit": 1000}
        url = "https://console.vast.ai/api/v0/bundles/?q=" + urllib.parse.quote(json.dumps(q, separators=(",", ":")))
        offers = get(url).get("offers", []); ts = NOW()
        by = defaultdict(list)
        for o in offers:
            reg = (o.get("geolocation") or "").split(",")[-1].strip() or None
            if o.get("num_gpus"): by[reg].append(o["dph_total"] / o["num_gpus"])
        by["ALL"] = [p for k, v in list(by.items()) for p in v]
        for reg, ps in sorted(by.items(), key=lambda kv: str(kv[0])):
            rows.append(dict(vendor="Vast.ai", gpu_model=model, tier="Marketplace on-demand (verified)", region=reg if reg != "ALL" else "all",
                in_stock=bool(ps), offer_count=len(ps), stock_level=None,
                price_usd_hr=round(statistics.median(ps), 4) if ps else None, price_basis="median per-GPU dph_total" if ps else None,
                source_url=url, collected_at=ts, refresh_rate="4h (marketplace)"))
        time.sleep(2)
    return rows

RP = {"NVIDIA H100 80GB HBM3": "H100 SXM", "NVIDIA H100 PCIe": "H100 PCIe", "NVIDIA A100-SXM4-80GB": "A100 SXM", "NVIDIA A100 80GB PCIe": "A100 PCIe", "NVIDIA GeForce RTX 4090": "RTX 4090"}
STOCK = {"High": True, "Medium": True, "Low": True}
def runpod():
    url = "https://api.runpod.io/graphql"; rows = []
    q = "{ gpuTypes { id secure: lowestPrice(input:{gpuCount:1, secureCloud:true}){ stockStatus uninterruptablePrice } community: lowestPrice(input:{gpuCount:1, secureCloud:false}){ stockStatus uninterruptablePrice } } dataCenters { id location gpuAvailability { gpuTypeId stockStatus } } }"
    d = get(url, json.dumps({"query": q}).encode())["data"]; ts = NOW()
    for g in d["gpuTypes"]:
        if g["id"] not in RP: continue
        for tier in ("secure", "community"):
            lp = g[tier] or {}; s = lp.get("stockStatus")
            rows.append(dict(vendor="RunPod", gpu_model=RP[g["id"]], tier=f"On-demand ({tier.title()} Cloud)", region="all",
                in_stock=STOCK.get(s, "unknown"), offer_count=None, stock_level=s, price_usd_hr=lp.get("uninterruptablePrice"),
                price_basis="lowestPrice.uninterruptablePrice (1 GPU)" if lp.get("uninterruptablePrice") else None,
                source_url=url + " (public gpuTypes.lowestPrice)", collected_at=ts, refresh_rate="6h (stock signal)"))
    for dc in d["dataCenters"]:
        for a in dc.get("gpuAvailability") or []:
            if a["gpuTypeId"] not in RP: continue
            s = a.get("stockStatus")
            rows.append(dict(vendor="RunPod", gpu_model=RP[a["gpuTypeId"]], tier="Secure Cloud (per data center)", region=f'{dc["id"]} ({dc.get("location")})',
                in_stock=STOCK.get(s, "unknown"), offer_count=None, stock_level=s, price_usd_hr=None, price_basis=None,
                source_url=url + " (public dataCenters.gpuAvailability)", collected_at=ts, refresh_rate="6h (stock signal)"))
    return rows

if __name__ == "__main__":
    rows, errs = [], {}
    for name, fn in (("vast", vast), ("runpod", runpod)):
        try: r = fn(); rows += r; print(name, len(r))
        except Exception as e: errs[name] = repr(e); print(name, "ERROR", e, file=sys.stderr)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    for p in (f"out/availability_{stamp}.json", "out/availability_latest.json"):
        json.dump({"collected_at": NOW(), "errors": errs, "rows": rows}, open(p, "w"), indent=1)
    with open("out/availability_latest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS); w.writeheader(); w.writerows(rows)
