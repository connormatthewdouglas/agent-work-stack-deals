"""GPU cost calculator core: structured GPU rates extracted from deals.json pricing notes.

Every rate is tied to a deal id and a quote that must appear verbatim in that deal's public
pricing_note, and the deal must have verified_at set. Anything else is reported as unpriced.
Ranking is by estimated cost for the user's hours, never by affiliate status or commission.
"""
from __future__ import annotations

import math

HOURS_PER_MONTH = 730  # 24 * 365 / 12

# (deal_id, gpu, vram_gb, price_usd, unit, quote, tier) — quote must be a substring of pricing_note.
RATE_SPECS = [
    ("deal-thundercompute-001", "RTX A6000", 48, 0.35, "hour", "RTX A6000 48GB $0.35/hr", "on-demand"),
    ("deal-thundercompute-001", "L40", 48, 0.79, "hour", "L40 48GB $0.79/hr", "on-demand"),
    ("deal-thundercompute-001", "A100", 80, 1.09, "hour", "A100 80GB $1.09/hr", "on-demand"),
    ("deal-thundercompute-001", "H100 SXM", 80, 3.20, "hour", "H100 SXM 80GB $3.20/hr", "on-demand"),
    ("deal-99stack-001", "H100", 80, 2.8767, "hour", "NVIDIA H100 (12 vCPU/240 GB RAM) $2.8767/hr", "on-demand"),
    ("deal-ucartz-001", "Radeon 780M", None, 382.72, "month", "from $382.72/mo (Radeon 780M)", "dedicated server"),
    ("deal-ucartz-001", "RTX 4090", 24, 798.72, "month", "RTX 4090 from $798.72/mo", "dedicated server"),
    ("deal-ucartz-001", "RTX A5000", 24, 819.52, "month", "RTX A5000 from $819.52/mo", "dedicated server"),
    ("deal-ucartz-001", "RTX 5090", 32, 1256.32, "month", "RTX 5090 from $1,256.32/mo", "dedicated server"),
    ("deal-ucartz-001", "A100", 80, 3128.32, "month", "A100 80GB from $3,128.32/mo", "dedicated server"),
]
_RP = "deal-runpod-001"
for _gpu, _vram, _price, _q, _tier in [
    ("H100 SXM", 80, 3.99, "H100 SXM 80GB $3.99/hr", "Secure Cloud"),
    ("H100 PCIe", 80, 2.89, "H100 PCIe 80GB $2.89/hr", "Secure Cloud"),
    ("A100 SXM", 80, 1.79, "A100 SXM 80GB $1.79/hr", "Secure Cloud"),
    ("A100 PCIe", 80, 1.79, "A100 PCIe 80GB $1.79/hr", "Secure Cloud"),
    ("L40S", 48, 1.09, "L40S 48GB $1.09/hr", "Secure Cloud"),
    ("L40", 48, 0.82, "L40 48GB $0.82/hr", "Secure Cloud"),
    ("RTX A6000", 48, 0.59, "RTX A6000 48GB $0.59/hr", "Secure Cloud"),
    ("RTX 5090", 32, 1.19, "RTX 5090 32GB $1.19/hr", "Secure Cloud"),
    ("RTX 4090", 24, 0.89, "RTX 4090 24GB $0.89/hr", "Secure Cloud"),
    ("RTX 3090", 24, 0.50, "RTX 3090 24GB $0.50/hr", "Secure Cloud"),
    ("RTX A5000", 24, 0.27, "RTX A5000 24GB $0.27/hr", "Secure Cloud"),
    ("H100 SXM", 80, 2.69, "H100 SXM $2.69/hr", "Community Cloud"),
    ("H100 PCIe", 80, 1.99, "H100 PCIe $1.99/hr", "Community Cloud"),
    ("A100 SXM", 80, 1.39, "A100 SXM $1.39/hr", "Community Cloud"),
    ("A100 PCIe", 80, 1.19, "A100 PCIe $1.19/hr", "Community Cloud"),
    ("RTX 4090", 24, 0.34, "RTX 4090 $0.34/hr", "Community Cloud"),
    ("RTX 3090", 24, 0.22, "RTX 3090 $0.22/hr", "Community Cloud"),
]:
    RATE_SPECS.append((_RP, _gpu, _vram, _price, "hour", _q, _tier))

# Model families for landing pages: rates whose gpu starts with the family name.
FAMILIES = {"h100": "H100", "a100": "A100", "rtx-4090": "RTX 4090", "rtx-5090": "RTX 5090",
            "l40": "L40", "rtx-a6000": "RTX A6000", "rtx-3090": "RTX 3090", "rtx-a5000": "RTX A5000"}
MIN_OFFERS, MIN_VENDORS = 3, 2  # below this a model gets no standalone page (avoid thin pages)


def family_of(gpu: str) -> str | None:
    for slug, name in FAMILIES.items():
        if gpu == name or gpu.startswith(name + " "):
            return slug
    return None


def families(rates: list[dict]) -> dict[str, dict]:
    out = {}
    for slug, name in FAMILIES.items():
        rs = [r for r in rates if family_of(r["gpu"]) == slug]
        vendors = {r["advertiser"] for r in rs}
        out[slug] = {"name": name, "rates": rs, "vendors": sorted(vendors),
                     "page": len(rs) >= MIN_OFFERS and len(vendors) >= MIN_VENDORS}
    return out


GPU_TAGS = ("gpu",)


def is_gpu_deal(d: dict) -> bool:
    return any(t in (d.get("tags") or []) for t in GPU_TAGS)


def build_rates(deals: list[dict]) -> dict:
    by_id = {d["id"]: d for d in deals}
    rates, problems = [], []
    for deal_id, gpu, vram, price, unit, quote, tier in RATE_SPECS:
        d = by_id.get(deal_id)
        if not d:
            problems.append(f"{deal_id}: not in public feed")
            continue
        if quote not in (d.get("pricing_note") or ""):
            problems.append(f"{deal_id}: quote not in pricing_note: {quote!r}")
            continue
        if not d.get("verified_at"):
            problems.append(f"{deal_id}: no verified_at")
            continue
        rates.append({"deal_id": deal_id, "advertiser": d.get("advertiser"), "gpu": gpu, "vram_gb": vram,
                      "price_usd": price, "unit": unit, "tier": tier,
                      "hourly_equiv_usd": round(price if unit == "hour" else price / HOURS_PER_MONTH, 4),
                      "billing": "per hour while running" if unit == "hour" else "flat monthly (dedicated server)",
                      "offer_type": d.get("offer_type"), "affiliate": bool(d.get("affiliate")),
                      "verified_at": d.get("verified_at"), "source_url": d.get("source_url"),
                      "redeem_url": d.get("redeem_url"), "basis": quote})
    priced = {r["deal_id"] for r in rates}
    unpriced = [{"deal_id": d["id"], "advertiser": d.get("advertiser"),
                 "reason": "no verified structured GPU price in feed", "source_url": d.get("source_url")}
                for d in sorted(deals, key=lambda x: x["id"]) if is_gpu_deal(d) and d["id"] not in priced]
    credits = [{"deal_id": d["id"], "advertiser": d.get("advertiser"), "unit": d.get("unit")}
               for d in deals if is_gpu_deal(d) and d.get("offer_type") in ("free_tier", "trial")]
    return {"rates": rates, "unpriced": unpriced, "free_credits": credits, "problems": problems}


def estimate(rates: list[dict], hours_per_month: float, gpus: int = 1, gpu_filter: str | None = None,
             min_vram_gb: int | None = None) -> list[dict]:
    """Monthly cost per option for N GPUs x hours. Flat monthly servers need ceil(hours/730) per GPU."""
    if hours_per_month < 0 or gpus < 1:
        raise ValueError("hours_per_month >= 0 and gpus >= 1 required")
    out = []
    for r in rates:
        if gpu_filter and gpu_filter.lower() not in r["gpu"].lower():
            continue
        if min_vram_gb and (r["vram_gb"] or 0) < min_vram_gb:
            continue
        if r["unit"] == "hour":
            cost = r["price_usd"] * hours_per_month * gpus
            basis = f"${r['price_usd']}/hr x {hours_per_month} h x {gpus} GPU"
        else:
            n = max(1, math.ceil(hours_per_month / HOURS_PER_MONTH)) * gpus
            cost = r["price_usd"] * n
            basis = f"${r['price_usd']}/mo x {n} server(s), flat regardless of hours"
        out.append({**r, "monthly_cost_usd": round(cost, 2), "calc": basis})
    return sorted(out, key=lambda x: (x["monthly_cost_usd"], x["advertiser"] or "", x["gpu"]))
