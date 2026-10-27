"""GPU pricing core: structured per-vendor pricing records (data/gpu_pricing/<vendor>.json).

Each record carries vendor, GPU, VRAM, price + billing unit, interruptible, source_url and checked_at, plus an
`evidence` object {source_url, quote, checked_at} from the last live check of the vendor page.
Multi-GPU servers carry gpu_count (> 1) and server_hourly_usd; price_usd is the vendor's server price and
hourly_usd is always PER GPU (server price / gpu_count), so every ranking is per GPU.
scripts/check_gpu_sources.py re-fetches sources daily and flags stale/unreachable ones (never edits).
Ranking is by estimated cost for the user's hours, never by affiliate status or commission.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOURS_PER_MONTH = 730  # 24 * 365 / 12

SERVERLESS = "Serverless (per second)"
BILLING_UNITS = ("per-second", "hourly", "monthly")
RECORD_FIELDS = ("vendor", "gpu", "vram_gb", "price_usd", "billing_unit", "hourly_usd", "interruptible",
                 "tier", "form_factor", "quote", "source_url", "checked_at")
PRICING_DIR = Path(__file__).resolve().parents[1] / "data" / "gpu_pricing"
STALE_DAYS = 7
EVIDENCE_FIELDS = ("source_url", "quote", "checked_at")
MAX_QUOTE = 200


def load_vendor_files(directory: Path | None = None) -> list[dict]:
    """Per-vendor structured pricing records (data/gpu_pricing/<vendor>.json): the only source of GPU rates."""
    d = Path(directory or PRICING_DIR)
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))]


def record_problems(doc: dict) -> list[str]:
    """Schema/consistency checks for one vendor file. Empty list = valid."""
    out, name = [], doc.get("vendor") or "?"
    for k in ("vendor", "deal_id", "source_url", "checked_at", "records", "extras"):
        if not doc.get(k):
            out.append(f"{name}: missing {k}")
    for k in ("egress", "storage", "interruption"):
        x = (doc.get("extras") or {}).get(k) or {}
        if x.get("status") not in ("published", "unknown") or not x.get("text") or not x.get("source_url"):
            out.append(f"{name}: extras.{k} needs status published|unknown, text, source_url")
    for i, r in enumerate(doc.get("records") or []):
        tag = f"{name} record {i} ({r.get('gpu')})"
        miss = [k for k in RECORD_FIELDS if k not in r]
        if miss:
            out.append(f"{tag}: missing {miss}")
            continue
        if r["vendor"] != doc.get("vendor"):
            out.append(f"{tag}: vendor mismatch")
        if r["billing_unit"] not in BILLING_UNITS:
            out.append(f"{tag}: billing_unit must be one of {BILLING_UNITS}")
        if not isinstance(r["interruptible"], bool):
            out.append(f"{tag}: interruptible must be true/false")
        if not (isinstance(r["price_usd"], (int, float)) and r["price_usd"] > 0):
            out.append(f"{tag}: price_usd must be > 0")
            continue
        factor = {"per-second": 3600, "hourly": 1, "monthly": 1 / HOURS_PER_MONTH}.get(r["billing_unit"], 1)
        n = r.get("gpu_count", 1)
        if not (isinstance(n, int) and not isinstance(n, bool) and n >= 1):
            out.append(f"{tag}: gpu_count must be an integer >= 1")
            continue
        if abs(round(r["price_usd"] * factor / n, 4) - r["hourly_usd"]) > 1e-4:
            out.append(f"{tag}: hourly_usd {r['hourly_usd']} != price_usd x {factor:g} / gpu_count {n} (must be per GPU)")
        if n > 1 and abs(round(r["price_usd"] * factor, 4) - (r.get("server_hourly_usd") or 0)) > 1e-4:
            out.append(f"{tag}: gpu_count {n} needs server_hourly_usd = price_usd x {factor:g}")
        if n == 1 and "server_hourly_usd" in r:
            out.append(f"{tag}: server_hourly_usd only for gpu_count > 1")
        ev = r.get("evidence")
        if not isinstance(ev, dict) or any(not ev.get(k) for k in EVIDENCE_FIELDS):
            out.append(f"{tag}: evidence needs {EVIDENCE_FIELDS}")
        else:
            if set(ev) - set(EVIDENCE_FIELDS):
                out.append(f"{tag}: evidence has extra keys {sorted(set(ev) - set(EVIDENCE_FIELDS))}")
            if not str(ev["source_url"]).startswith("https://"):
                out.append(f"{tag}: evidence.source_url must be https")
            if len(ev["quote"]) > MAX_QUOTE:
                out.append(f"{tag}: evidence.quote longer than {MAX_QUOTE} chars")
            try:
                datetime.fromisoformat(ev["checked_at"])
            except (TypeError, ValueError):
                out.append(f"{tag}: evidence.checked_at not ISO-8601")
        if not str(r["source_url"]).startswith("https://") or not r["checked_at"]:
            out.append(f"{tag}: needs https source_url and checked_at")
        try:
            datetime.fromisoformat(r["checked_at"])
        except (TypeError, ValueError):
            out.append(f"{tag}: checked_at not ISO-8601")
    return out


def stale_records(docs: list[dict], now: datetime | None = None, days: int = STALE_DAYS) -> list[str]:
    now = now or datetime.now(timezone.utc)
    out = []
    for doc in docs:
        for r in doc.get("records") or []:
            age = now - datetime.fromisoformat(r["checked_at"])
            if age > timedelta(days=days):
                out.append(f"{doc['vendor']} {r['gpu']} ({r['tier']}): checked_at {r['checked_at']} is {age.days} days old")
    return out


# Model families for landing pages: rates whose gpu starts with the family name.
FAMILIES = {"h100": "H100", "h200": "H200", "a100": "A100", "l40s": "L40S", "rtx-4090": "RTX 4090", "rtx-5090": "RTX 5090",
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


def build_rates(deals: list[dict], vendor_docs: list[dict] | None = None) -> dict:
    """Rates for /api/v1/gpu-prices.json and every GPU page, from the per-vendor records.

    Output fields stay compatible with 0.2.0 consumers: price_usd/unit are the hourly (unit 'hour') or
    monthly (unit 'month') price; per-second prices are carried as price_per_second_usd."""
    by_id = {d["id"]: d for d in deals}
    docs = load_vendor_files() if vendor_docs is None else vendor_docs
    rates, problems, vendors = [], [], []
    for doc in docs:
        bad = record_problems(doc)
        if bad:
            problems += bad
            continue
        d = by_id.get(doc["deal_id"])
        if not d:
            problems.append(f"{doc['deal_id']}: not in public feed")
            continue
        vendors.append({"vendor": doc["vendor"], "deal_id": doc["deal_id"], "source_url": doc["source_url"],
                        "checked_at": doc["checked_at"], "billing_granularity": doc.get("billing_granularity"),
                        "extras": doc["extras"]})
        for r in doc["records"]:
            monthly = r["billing_unit"] == "monthly"
            n = r.get("gpu_count", 1)
            rates.append({
                "deal_id": doc["deal_id"], "advertiser": r["vendor"], "gpu": r["gpu"], "vram_gb": r["vram_gb"],
                # Always per GPU: monthly multi-GPU servers are divided by gpu_count.
                "price_usd": round(r["price_usd"] / n, 2) if monthly else r["hourly_usd"],
                "gpu_count": n,
                "server_price_usd": r["price_usd"] if n > 1 else None,
                "server_hourly_usd": r.get("server_hourly_usd"),
                "unit": "month" if monthly else "hour", "tier": r["tier"],
                "hourly_equiv_usd": r["hourly_usd"],
                "billing": {"per-second": "per second while running", "hourly": "per hour while running",
                            "monthly": "flat monthly (dedicated server)"}[r["billing_unit"]],
                "billing_unit": r["billing_unit"],
                "price_per_second_usd": r["price_usd"] if r["billing_unit"] == "per-second" else None,
                "interruptible": r["interruptible"], "form_factor": r["form_factor"],
                "offer_type": d.get("offer_type"), "affiliate": bool(d.get("affiliate")),
                "verified_at": r["checked_at"], "checked_at": r["checked_at"], "source_url": r["source_url"],
                "redeem_url": d.get("redeem_url"), "basis": r["quote"], "evidence": r["evidence"]})
    priced = {r["deal_id"] for r in rates}
    unpriced = [{"deal_id": d["id"], "advertiser": d.get("advertiser"),
                 "reason": "no structured GPU pricing record", "source_url": d.get("source_url")}
                for d in sorted(deals, key=lambda x: x["id"]) if is_gpu_deal(d) and d["id"] not in priced]
    credits = [{"deal_id": d["id"], "advertiser": d.get("advertiser"), "unit": d.get("unit")}
               for d in deals if is_gpu_deal(d) and d.get("offer_type") in ("free_tier", "trial")]
    return {"rates": rates, "vendors": vendors, "unpriced": unpriced, "free_credits": credits, "problems": problems}


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
            per = r.get("gpu_count") or 1
            if per > 1:
                basis = (f"${r['price_usd']}/GPU-mo x {n} GPU-month(s) (sold as {per}-GPU servers at "
                         f"${r['server_price_usd']:,.2f}/mo), flat regardless of hours")
            else:
                basis = f"${r['price_usd']}/mo x {n} server(s), flat regardless of hours"
        out.append({**r, "monthly_cost_usd": round(cost, 2), "calc": basis})
    return sorted(out, key=lambda x: (x["monthly_cost_usd"], x["advertiser"] or "", x["gpu"]))
