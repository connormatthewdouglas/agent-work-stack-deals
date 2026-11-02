"""Import a Clore.ai manual marketplace snapshot (Gauge/Scout JSON from GET https://api.clore.ai/v1/marketplace) into
data/gpu_pricing/clore.json. Same method as the 2026-10-29 / 2026-11-01 snapshots: available on-demand host listings
priced in USD, per GPU-hr = USD/day / 24 / gpu_count, spot/bid excluded; the published price is the median, with
min/max and listing count. Fewer than MIN_MACHINES available USD listings -> price withheld (null) and the row held
(stale) with N and the snapshot time. Only existing Clore records are updated; values come from the snapshot file,
never typed by hand. Clore never reaches /cost/ (core/compliance + cost page rules are unchanged).
Usage: import_clore_snapshot.py <snapshot.json> [--dry-run]"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "gpu_pricing" / "clore.json"
MIN_MACHINES = 5
# record gpu -> (snapshot summary key, listing gpu, accepted per-GPU VRAM values, label vram)
MAP = {"RTX 4090": ("RTX 4090", "RTX 4090", None), "RTX 5090": ("RTX 5090", "RTX 5090", None),
       "A100 SXM": ("A100", "A100", {40}), "H100 NVL": ("H100", "H100", {94}), "L40S": ("L40S", "L40S", None)}


def _ts(s: str) -> str:
    return s.replace("Z", "+00:00")


def apply(doc: dict, snap: dict) -> list[str]:
    at = _ts(snap["checked_at"])
    src = snap["source_url"]
    log = []
    for r in doc["records"]:
        if r["gpu"] not in MAP:
            continue
        key, lg, vr = MAP[r["gpu"]]
        s = snap["summary"].get(key) or {}
        av = [l for l in snap.get("listings", []) if l["gpu"] == lg and l["status"] == "available" and l["currency_usd_listed"]]
        if vr is not None:  # the summary key must cover only this form factor (A100 SXM 40GB, H100 NVL 94GB)
            bad = [l["gpu_string"] for l in av if l["vram_gb_per_gpu"] not in vr]
            assert not bad, f"{r['gpu']}: summary mixes other variants {bad}"
        n = s.get("available_with_usd_price") or 0
        vlabel = {"L40S": 45}.get(r["gpu"], r["vram_gb"])
        name = f"{r['gpu']} {vlabel}GB"
        if n >= MIN_MACHINES:
            med, (lo, hi) = s["median"], s["range_on_demand"]
            q = f"Clore.ai API: {n} available {name} host USD listings, range ${lo}-${hi}; per-GPU median ${med}/hr, min ${lo}/hr"
            r.update(price_usd=med, hourly_usd=med, lowest_offer_usd=lo, highest_offer_usd=hi, offer_count=n)
            r.pop("stale", None)
        else:
            if n:
                q = f"Clore.ai API: {n} available {name} host USD listings; price withheld (fewer than {MIN_MACHINES} distinct machines)"
            else:
                q = f"Clore.ai API: 0 available {name} host USD listings (no available listing); price withheld"
            r.update(price_usd=None, hourly_usd=None, lowest_offer_usd=None, highest_offer_usd=None, offer_count=n)
            r["stale"] = {"reason": f"fewer than {MIN_MACHINES} distinct Clore machines (N={n}) at {snap['checked_at']}"
                                    + ("; no available listing" if not n else ""), "page_last_updated": None}
            if n:  # lowest seen is kept as evidence context only (never published while held)
                q += f"; lowest ${s['lowest_available_on_demand_usd_gpu_hr']}/hr"
        la = s.get("listings_available")
        if la is not None:  # Gauge rel053: stock from the same snapshot as the price (available listings, any currency)
            r["availability"] = {"in_stock": la > 0, "checked_at": at, "source": src, "same_capture_as_price": True,
                                 "stock_level": f"{la} available listings",
                                 "note": f"Clore.ai API snapshot: {la} available {name} listings (status available, any currency)"}
        r.update(quote=q, source_url=src, checked_at=at, verified_at=at,
                 evidence={"source_url": src, "quote": q, "checked_at": at})
        log.append(f"{r['gpu']}: N={n} " + (f"median ${r['price_usd']} low ${r['lowest_offer_usd']}" if r["price_usd"] else "held"))
    doc["checked_at"] = at
    for x in doc["extras"].values():
        x["checked_at"] = at
    doc["source_note"] = (f"Clore.ai marketplace snapshot {at} (public no-auth GET {src}; Gauge file; method identical to "
                          f"Gauge 2026-10-29 snapshot).")
    doc["manual_snapshot"] = {"reason": f"Clore.ai marketplace API returns 401 to CI runners; prices are a manual snapshot "
                                        f"(Gauge, {at}) and auto-hold after 7 days unless re-snapshotted."}
    return log


def main() -> int:
    snap = json.loads(Path(sys.argv[1]).read_text())
    doc = json.loads(PATH.read_text())
    print("\n".join(apply(doc, snap)))
    if "--dry-run" not in sys.argv:
        PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
