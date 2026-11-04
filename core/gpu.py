"""GPU pricing core: structured per-vendor pricing records (data/gpu_pricing/<vendor>.json).

Each record carries vendor, GPU, VRAM, price + billing unit, interruptible, source_url and checked_at, plus an
`evidence` object {source_url, quote, checked_at} from the last live check of the vendor page.
Multi-GPU servers carry gpu_count (> 1) and server_hourly_usd; price_usd is the vendor's server price and
hourly_usd is always PER GPU (server price / gpu_count), so every ranking is per GPU.
Optional flags: min_gpus (instance only sold with N GPUs; estimates charge at least N); price_status
"marketplace" (variable host prices: hourly_usd is the median, plus lowest_offer_usd and offer_count >=
MIN_MARKET_OFFERS; a thinner market gets a record-level `stale` {reason} hold); vendor-level `stale` {reason, page_last_updated} holds the vendor out of `rates` (listed
under `held_stale` instead) so no comparison, page, MCP tool or optimizer can rank it.
deal_id may be null for vendors with no deal in the feed (links then go to the vendor's own page).
scripts/refresh_gpu_prices.py (daily Action) re-reads each source and updates a price only where it parsed it from
the vendor's own page/API: verified_at = when the price was last parsed, checked_at = last attempt. A rate not
re-verified for STALE_DAYS gets an automatic record-level hold (stale.auto) and is never ranked until re-verified.
scripts/check_gpu_sources.py re-fetches sources daily and flags stale/unreachable ones (never edits); scripts/refresh_gpu_prices.py updates parsed prices.
Ranking is by estimated cost for the user's hours, never by affiliate status or commission.
"""
from __future__ import annotations

from .referrals import referral_fields_for
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOURS_PER_MONTH = 730  # 24 * 365 / 12

SERVERLESS = "Serverless, preemptible (per second)"

_EXCL = "tracked providers only; excludes storage, egress, idle time and preemption"
PRICE_BASIS_LABELS = {
    "on-demand": "on-demand list price per GPU-hour; " + _EXCL,
    "spot-community": "interruptible/community/marketplace list price per GPU-hour (may be preempted); " + _EXCL,
    "serverless": "serverless list price per GPU-hour while running (cold starts not included); " + _EXCL,
    "reserved": "reserved/commitment list price per GPU-hour, excluded from lowest-price picks; " + _EXCL,
    "monthly": "flat monthly price / 730 h per GPU; " + _EXCL,
}


def price_bucket(r: dict) -> str:
    tc = r.get("tier_class") or "on-demand"
    if r.get("tier") == SERVERLESS or "serverless" in (r.get("tier") or "").lower():
        return "serverless"
    if tc == "reserved":
        return "reserved"
    if tc == "dedicated-monthly" or r.get("unit") == "month":
        return "monthly"
    if tc in ("interruptible", "community", "marketplace"):
        return "spot-community"
    return "on-demand"


def price_basis_label(r: dict) -> str:
    return PRICE_BASIS_LABELS[price_bucket(r)]
BILLING_UNITS = ("per-second", "hourly", "monthly")
RECORD_FIELDS = ("vendor", "gpu", "vram_gb", "price_usd", "billing_unit", "hourly_usd", "interruptible",
                 "tier", "form_factor", "quote", "source_url", "checked_at")
PRICING_DIR = Path(__file__).resolve().parents[1] / "data" / "gpu_pricing"
STALE_DAYS = 7
EVIDENCE_FIELDS = ("source_url", "quote", "checked_at")
# optional second cited quote for the row's interruption/preemption terms (Modal); all three or none
EVIDENCE_OPTIONAL = ("interruption_quote", "interruption_source_url", "interruption_checked_at")
MIN_MARKET_OFFERS = 5
MAX_QUOTE = 200


def load_vendor_files(directory: Path | None = None) -> list[dict]:
    """Per-vendor structured pricing records (data/gpu_pricing/<vendor>.json): the only source of GPU rates."""
    d = Path(directory or PRICING_DIR)
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))]


# Integrated / laptop-class GPUs are not cloud GPU rentals; they never belong in the comparison (audit T7/M4).
INTERRUPTIBLE_TIER_RE = re.compile(r"(?<!not )(?<!non-)(?:spot|preempt|interrupt)", re.I)
NON_DEDICATED_RE = re.compile(r"\b(radeon\s+\d{3,4}m|iris|uhd graphics|vega\s*\d+|integrated|igpu)\b", re.I)


def is_non_dedicated(gpu: str) -> bool:
    return bool(NON_DEDICATED_RE.search(gpu or ""))


def record_problems(doc: dict) -> list[str]:
    """Schema/consistency checks for one vendor file. Empty list = valid."""
    out, name = [], doc.get("vendor") or "?"
    for k in ("vendor", "source_url", "checked_at", "records", "extras"):
        if not doc.get(k):
            out.append(f"{name}: missing {k}")
    if "deal_id" not in doc or not (doc["deal_id"] is None or isinstance(doc["deal_id"], str) and doc["deal_id"]):
        out.append(f"{name}: deal_id must be a feed deal id or null")
    st = doc.get("stale")
    if st is not None and not (isinstance(st, dict) and st.get("reason")):
        out.append(f"{name}: stale needs a reason")
    for k in ("egress", "storage", "interruption"):
        x = (doc.get("extras") or {}).get(k) or {}
        if x.get("status") not in ("published", "unknown") or not x.get("text") or not x.get("source_url"):
            out.append(f"{name}: extras.{k} needs status published|unknown, text, source_url")
    for i, r in enumerate(doc.get("records") or []):
        tag = f"{name} record {i} ({r.get('gpu')})"
        rst = r.get("stale")
        if rst is not None and not (isinstance(rst, dict) and rst.get("reason")):
            out.append(f"{tag}: stale needs a reason")
        miss = [k for k in RECORD_FIELDS if k not in r]
        if miss:
            out.append(f"{tag}: missing {miss}")
            continue
        if r["vendor"] != doc.get("vendor"):
            out.append(f"{tag}: vendor mismatch")
        if is_non_dedicated(r.get("gpu")):
            out.append(f"{tag}: integrated/laptop-class GPU is not a cloud GPU rental; don't list it")
        if r["billing_unit"] not in BILLING_UNITS:
            out.append(f"{tag}: billing_unit must be one of {BILLING_UNITS}")
        if not isinstance(r["interruptible"], bool):
            out.append(f"{tag}: interruptible must be true/false")
        if r["price_usd"] is None and r.get("stale"):
            pass  # a held row (never ranked) may withhold its price, e.g. a thin Clore group (Gauge Nov 1)
        elif not (isinstance(r["price_usd"], (int, float)) and r["price_usd"] > 0):
            out.append(f"{tag}: price_usd must be > 0")
            continue
        factor = {"per-second": 3600, "hourly": 1, "monthly": 1 / HOURS_PER_MONTH}.get(r["billing_unit"], 1)
        n = r.get("gpu_count", 1)
        if not (isinstance(n, int) and not isinstance(n, bool) and n >= 1):
            out.append(f"{tag}: gpu_count must be an integer >= 1")
            continue
        if r["price_usd"] is None:
            continue
        if abs(round(r["price_usd"] * factor / n, 4) - r["hourly_usd"]) > 1e-4:
            out.append(f"{tag}: hourly_usd {r['hourly_usd']} != price_usd x {factor:g} / gpu_count {n} (must be per GPU)")
        if n > 1 and abs(round(r["price_usd"] * factor, 4) - (r.get("server_hourly_usd") or 0)) > 1e-4:
            out.append(f"{tag}: gpu_count {n} needs server_hourly_usd = price_usd x {factor:g}")
        if n == 1 and "server_hourly_usd" in r:
            out.append(f"{tag}: server_hourly_usd only for gpu_count > 1")
        if bool(r.get("interruptible")) != bool(INTERRUPTIBLE_TIER_RE.search(r.get("tier") or "")):
            out.append(f"{tag}: interruptible={r.get('interruptible')} must match the tier label '{r.get('tier')}' "
                       "(spot/preemptible/interruptible tiers say so in the label)")
        if r.get("tier_class") is not None and r["tier_class"] not in ("on-demand", "interruptible", "community", "marketplace", "reserved", "dedicated-monthly"):
            out.append(f"{tag}: tier_class override must be a known class")
        mg = r.get("min_gpus", 1)
        if not (isinstance(mg, int) and not isinstance(mg, bool) and mg >= 1):
            out.append(f"{tag}: min_gpus must be an integer >= 1")
        ps = r.get("price_status", "listed")
        if ps not in ("listed", "marketplace"):
            out.append(f"{tag}: price_status must be listed|marketplace")
        if ps == "marketplace":
            lo, cnt = r.get("lowest_offer_usd"), r.get("offer_count")
            if not (isinstance(lo, (int, float)) and 0 < lo <= r["hourly_usd"]):
                out.append(f"{tag}: marketplace needs 0 < lowest_offer_usd <= hourly_usd (median)")
            if not (isinstance(cnt, int) and (cnt >= MIN_MARKET_OFFERS or (cnt >= 1 and r.get("stale")))):
                # A thinner market is allowed only with a record-level stale hold (listed, never ranked).
                out.append(f"{tag}: marketplace median needs offer_count >= {MIN_MARKET_OFFERS}")
            if not r.get("price_basis"):
                out.append(f"{tag}: marketplace needs price_basis")
        ev = r.get("evidence")
        if not isinstance(ev, dict) or any(not ev.get(k) for k in EVIDENCE_FIELDS):
            out.append(f"{tag}: evidence needs {EVIDENCE_FIELDS}")
        else:
            if set(ev) - set(EVIDENCE_FIELDS) - set(EVIDENCE_OPTIONAL):
                out.append(f"{tag}: evidence has extra keys {sorted(set(ev) - set(EVIDENCE_FIELDS) - set(EVIDENCE_OPTIONAL))}")
            opt = [k for k in EVIDENCE_OPTIONAL if ev.get(k)]
            if opt and len(opt) != len(EVIDENCE_OPTIONAL):
                out.append(f"{tag}: evidence interruption quote needs {EVIDENCE_OPTIONAL}")
            if ev.get("interruption_source_url") and not str(ev["interruption_source_url"]).startswith("https://"):
                out.append(f"{tag}: evidence.interruption_source_url must be https")
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
        for k in ("checked_at", "verified_at"):
            if k == "verified_at" and k not in r:
                continue
            try:
                datetime.fromisoformat(r[k])
            except (TypeError, ValueError):
                out.append(f"{tag}: {k} not ISO-8601")
    return out


def stale_records(docs: list[dict], now: datetime | None = None, days: int = STALE_DAYS) -> list[str]:
    now = now or datetime.now(timezone.utc)
    out = []
    for doc in docs:
        for r in doc.get("records") or []:
            if r.get("stale"):
                continue  # held records are never ranked; their age isn't a live-site failure
            v = r.get("verified_at") or r["checked_at"]
            age = now - datetime.fromisoformat(v)
            if age > timedelta(days=days):
                out.append(f"{doc['vendor']} {r['gpu']} ({r['tier']}): price last verified {v} is {age.days} days old")
    return out


# Model families for landing pages: rates whose gpu starts with the family name.
FAMILIES = {"h100": "H100", "h200": "H200", "a100": "A100", "l40s": "L40S", "rtx-4090": "RTX 4090", "rtx-5090": "RTX 5090",
            "l40": "L40", "rtx-a6000": "RTX A6000", "rtx-3090": "RTX 3090", "rtx-a5000": "RTX A5000",
            "b200": "B200", "gh200": "GH200", "mi300x": "MI300X", "mi250": "MI250", "l4": "L4", "a10": "A10",
            "a10g": "A10G", "a40": "A40", "rtx-6000-ada": "RTX 6000 Ada", "t4": "T4", "v100": "V100",
            "b300": "B300", "rtx-pro-6000": "RTX PRO 6000", "rtx-a4000": "RTX A4000",
            "h200-nvl": "H200 NVL", "h100-nvl": "H100 NVL",
            "gb300": "GB300", "quadro-rtx-6000": "Quadro RTX 6000",
            # T69 (Pax research-t69, Nov 2): broader hardware; RTX PRO 5000 48GB and 72GB stay separate rows (vram_gb)
            "mi325x": "MI325X", "mi355x": "MI355X", "rtx-pro-5000": "RTX PRO 5000", "rtx-pro-4000": "RTX PRO 4000",
            "rtx-pro-4500": "RTX PRO 4500"}
PAGE_ALSO = {"h100-nvl": "h100"}  # H100 NVL rows also list (labelled by form) on the H100 pages; the NVL family keeps its own
MIN_OFFERS, MIN_VENDORS = 3, 2  # below this a model gets no standalone page (avoid thin pages)


def family_of(gpu: str) -> str | None:
    """Longest family name that equals the model or prefixes it at a word boundary: 'L4' never takes
    'L40'/'L40S', 'A10' never takes 'A100'/'A10G', and 'H100 NVL' wins over 'H100'."""
    best = None
    for slug, name in FAMILIES.items():
        if (gpu == name or gpu.startswith(name + " ")) and (best is None or len(name) > len(FAMILIES[best])):
            best = slug
    return best


def families(rates: list[dict]) -> dict[str, dict]:
    out = {}
    for slug, name in FAMILIES.items():
        rs = [r for r in rates if family_of(r["gpu"]) == slug or PAGE_ALSO.get(family_of(r["gpu"])) == slug]
        vendors = {r["advertiser"] for r in rs}
        out[slug] = {"name": name, "rates": rs, "vendors": sorted(vendors),
                     "page": len(rs) >= MIN_OFFERS and len(vendors) >= MIN_VENDORS}
    return out


GPU_TAGS = ("gpu",)


def is_gpu_deal(d: dict) -> bool:
    return any(t in (d.get("tags") or []) for t in GPU_TAGS)


_DASHES = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")


def normalize_tier(t: str | None) -> str | None:
    """ASCII hyphens and 'On-demand' casing for the tier label (audit E6); evidence quotes stay verbatim."""
    if t is None:
        return None
    t = _DASHES.sub("-", t)
    return t.replace("On-Demand", "On-demand")


def _tier_class(r: dict) -> str:
    from .deals import tier_class
    return tier_class(r)


from .gpu_availability import availability_for  # noqa: E402


PRICE_SCOPE = ("GPU-hour price only: excludes storage, data egress, extra vCPU/RAM and taxes. Check the vendor pricing page "
               "(source_url) for those; storage/egress fields appear on a rate only where that vendor's own page states them.")


SPLIT_FORM_MODELS = ("H100", "A100")
FORM_FACTOR_ORDER = ("SXM", "PCIe", "NVL", "not stated")


def split_by_form(gpu: str | None) -> bool:
    """gpu_poor #18: H100 and A100 are compared within one form factor (SXM vs PCIe never ranked as one)."""
    return (gpu or "").upper().startswith(SPLIT_FORM_MODELS)


def form_of(r: dict) -> str:
    """The row's existing form_factor field, normalised for grouping ('not stated' when absent)."""
    return r.get("form_factor") or "not stated"


def form_class(gpu: str, quote: str = "") -> str | None:
    """H100 form factor for ranking splits (gpu_poor #18): SXM, PCIe, NVL, or 'form not stated'. HGX boards are SXM."""
    g = (gpu or "").upper()
    if not g.startswith("H100"):
        return None
    if "NVL" in g and "NVLINK" not in g:  # 'H100 NVL' (94 GB). 'H100 NVLink' names the bridge, not the form: not stated
        return "NVL"
    if "PCIE" in g:
        return "PCIe"
    if "SXM" in g or "HGX" in (quote or "").upper():
        return "SXM"
    return "form not stated"


_FORM_TOKEN = re.compile(r"\b(SXM\d?|PCIe|NVL)\b", re.I)


def canonical_model(gpu: str) -> str:
    """T75: the tracked model a GPU string belongs to (e.g. 'H100 SXM', 'H100 PCIe', 'H100 NVLink' -> 'H100';
    'H100 NVL' stays its own model). Unknown strings map to themselves."""
    f = family_of(gpu or "")
    return FAMILIES[f] if f else gpu


def _vendor_gpu_id(r: dict) -> str:
    """The vendor's own GPU id when the source cites one ('... id=NVIDIA B300 SXM6 AC')."""
    for u in (r.get("source_url"), (r.get("evidence") or {}).get("source_url")):
        m = re.search(r"\bid=(.+)$", str(u or ""))
        if m:
            return m.group(1)
    return ""


def form_factor_of(gpu: str, vendor_value: str | None = None, quote: str = "", vendor_id: str = "") -> str:
    """T75: complete form_factor. The vendor record's own value wins; otherwise the form stated in the GPU name (SXM,
    SXM2.., PCIe, NVL; 'NVLink' names the bridge, not the form), an HGX board in the quote (SXM), else 'not stated'.
    Never guessed from the model alone."""
    if vendor_value:
        return vendor_value
    m = _FORM_TOKEN.search(gpu or "") or _FORM_TOKEN.search(vendor_id or "")  # vendor GPU id, e.g. RunPod "NVIDIA B300 SXM6 AC"
    if m:
        t = m.group(1)
        return "PCIe" if t.lower() == "pcie" else t.upper()
    if "HGX" in (quote or "").upper():
        return "SXM"
    return "not stated"


def vendor_counts(rates: list[dict]) -> dict:
    """T76: '25 vs 23'. priced_sources = every advertiser with a priced rate (gpu-prices.json); instance_vendors = those with
    at least one non-serverless row (the /coverage/ matrix count, which excludes serverless rows)."""
    priced = {r["advertiser"] for r in rates}
    inst = {r["advertiser"] for r in rates if "serverless" not in str(r.get("tier") or "").lower()}
    return {"priced_sources": len(priced), "instance_vendors": len(inst), "serverless_only": sorted(priced - inst)}


def vendor_counts_label(rates: list[dict]) -> str:
    c = vendor_counts(rates)
    if not c["serverless_only"]:
        return f"{c['priced_sources']} vendors"
    return (f"{c['priced_sources']} vendors ({c['priced_sources']} priced sources, {c['instance_vendors']} instance vendors: "
            f"{' and '.join(c['serverless_only'])} sell serverless only)")


def _published_extras(doc: dict) -> dict:
    out = {}
    for k in ("storage", "egress"):
        x = (doc.get("extras") or {}).get(k) or {}
        if x.get("status") == "published" and x.get("source_url"):
            out[k] = {"text": x["text"], "source_url": x["source_url"], "checked_at": x.get("checked_at")}
    return out


BATCH_HOLD_HOURS = 48  # Gauge G5: batch rows (Scout wider-GPU) are not re-read daily; hold them like manual snapshots


def _is_batch(r: dict) -> bool:
    return r.get("price_check") == "batch" or bool(r.get("batch"))


def _price_too_old(r: dict, doc: dict) -> bool:
    if doc.get("manual_snapshot"):
        return False  # manual snapshots have their own hold_after rule
    from .data_age import STALE_HOURS, age_fields
    h = age_fields(r)["data_age_hours"]
    return h is not None and h > (BATCH_HOLD_HOURS if _is_batch(r) else STALE_HOURS)


def _vram_note(r: dict) -> dict:
    """Gauge nov1_mart4: a corrected vram_gb next to the vendor's verbatim quote (e.g. Clore '45GB' published as 48)
    always travels with its explanation."""
    return {"vram_note": r["vram_note"]} if r.get("vram_note") else {}


def build_rates(deals: list[dict], vendor_docs: list[dict] | None = None) -> dict:
    """Rates for /api/v1/gpu-prices.json and every GPU page, from the per-vendor records.

    Output fields stay compatible with 0.2.0 consumers: price_usd/unit are the hourly (unit 'hour') or
    monthly (unit 'month') price; per-second prices are carried as price_per_second_usd."""
    by_id = {d["id"]: d for d in deals}
    docs = load_vendor_files() if vendor_docs is None else vendor_docs
    rates, problems, vendors, held = [], [], [], []
    for doc in docs:
        bad = record_problems(doc)
        if bad:
            problems += bad
            continue
        d = by_id.get(doc["deal_id"]) if doc["deal_id"] else {}
        if d is None:
            problems.append(f"{doc['deal_id']}: not in public feed")
            continue
        if doc.get("stale"):
            held.append({"vendor": doc["vendor"], "deal_id": doc["deal_id"], "source_url": doc["source_url"],
                         "checked_at": doc["checked_at"], "reason": doc["stale"]["reason"],
                         "page_last_updated": doc["stale"].get("page_last_updated"),
                         "records": [{**{k: r.get(k) for k in ("gpu", "vram_gb", "hourly_usd", "tier", "quote", "evidence")}, **_vram_note(r)}
                                     for r in doc["records"]]})
            continue
        vendors.append({"vendor": doc["vendor"], "deal_id": doc["deal_id"], "source_url": doc["source_url"],
                        "checked_at": doc["checked_at"], "billing_granularity": doc.get("billing_granularity"),
                        "extras": doc["extras"], "market_note": doc.get("market_note")})
        for r in doc["records"]:
            nc = r.get("no_capacity")
            if nc and not r.get("stale"):
                # Gauge T73 fix7 #1: vendor page says no capacity now -> out of stock, last sourced price kept, never ranked
                held.append({"vendor": doc["vendor"], "deal_id": doc["deal_id"], "source_url": r["source_url"],
                             "checked_at": nc["read_at"], "reason": f"{nc['reason']} (read {nc['read_at']}); last sourced "
                             f"${r['hourly_usd']:.2f}/hr on {r['verified_at'][:10]}", "page_last_updated": None, "scope": "record",
                             "availability": {"status": "out of stock when checked", "in_stock": False, "reason": nc["reason"],
                                              "checked_at": nc["read_at"], "source": nc["source_url"], "page_text": nc.get("page_text")},
                             "records": [{**{k: r.get(k) for k in ("gpu", "vram_gb", "hourly_usd", "tier", "quote", "evidence")}, **_vram_note(r)}]})
        held_recs = [r for r in doc["records"] if r.get("stale")]
        for r in held_recs:
            # Record-level hold (e.g. marketplace too thin: < MIN_MARKET_OFFERS offers): listed, never ranked.
            held.append({"vendor": doc["vendor"], "deal_id": doc["deal_id"], "source_url": r["source_url"],
                         "checked_at": r["checked_at"], "reason": r["stale"]["reason"],
                         "page_last_updated": r["stale"].get("page_last_updated"),
                         "records": [{**{k: r.get(k) for k in ("gpu", "vram_gb", "hourly_usd", "tier", "quote", "evidence")}, **_vram_note(r)}], "scope": "record"})
        for r in doc["records"]:
            if r.get("stale") or r.get("no_capacity"):
                continue
            if _price_too_old(r, doc):
                # Gauge re28: a price not re-verified for STALE_DAYS never ranks on any page; listed in held_stale.
                from .data_age import stale_label
                held.append({"vendor": doc["vendor"], "deal_id": doc["deal_id"], "source_url": r["source_url"],
                             "checked_at": r["checked_at"], "reason": stale_label(r), "page_last_updated": None, "scope": "record",
                             "records": [{**{k: r.get(k) for k in ("gpu", "vram_gb", "hourly_usd", "tier", "quote", "evidence")}, **_vram_note(r)}]})
                continue
            monthly = r["billing_unit"] == "monthly"
            n = r.get("gpu_count", 1)
            rates.append({
                "deal_id": doc["deal_id"], "advertiser": r["vendor"], "gpu": r["gpu"], "vram_gb": r["vram_gb"],
                # Always per GPU: monthly multi-GPU servers are divided by gpu_count.
                "price_usd": round(r["price_usd"] / n, 2) if monthly else r["hourly_usd"],
                "gpu_count": n,
                "server_price_usd": r["price_usd"] if n > 1 else None,
                "server_hourly_usd": r.get("server_hourly_usd"),
                "min_gpus": r.get("min_gpus", 1),
                "price_status": r.get("price_status", "listed"),
                "price_basis": r.get("price_basis"),
                # T41-19: lowest_offer_usd/offer_count exist only on marketplace rows (absent, not null, elsewhere)
                **({"lowest_offer_usd": r.get("lowest_offer_usd"), "offer_count": r.get("offer_count")}
                   if r.get("price_status") == "marketplace" else {}),
                "unit": "month" if monthly else "hour", "tier": normalize_tier(r["tier"]),
                "hourly_equiv_usd": r["hourly_usd"],
                "billing": {"per-second": "per second while running", "hourly": "per hour while running",
                            "monthly": "flat monthly (dedicated server)"}[r["billing_unit"]],
                "billing_unit": r["billing_unit"],
                "price_per_second_usd": r["price_usd"] if r["billing_unit"] == "per-second" else None,
                "interruptible": r["interruptible"],
                "canonical_model": canonical_model(r["gpu"]),
                "form_factor": form_factor_of(r["gpu"], r.get("form_factor"), f"{r['quote']} {(r.get('evidence') or {}).get('quote') or ''}",
                                              _vendor_gpu_id(r)),
                **({"form_class": fc} if (fc := form_class(r["gpu"], f"{r['quote']} {(r.get('evidence') or {}).get('quote') or ''}")) else {}),
                "price_scope": "gpu_hour_only", **_published_extras(doc),
                **({k: r[k] for k in ("provider", "availability_note", "platform_fee_note", "region", "vram_note", "price_rotates") if r.get(k)}),
                # Manual snapshot vendors (e.g. Clore.ai): not re-checked daily; held automatically after hold_after.
                **({"price_check": "manual snapshot", "snapshot_at": r["checked_at"],
                    "hold_after": (datetime.fromisoformat(r["checked_at"]) + timedelta(days=STALE_DAYS)).isoformat()}
                   if doc.get("manual_snapshot") else
                   {"price_check": "batch", "last_read": r.get("verified_at") or r["checked_at"],
                    "hold_after": (datetime.fromisoformat((r.get("verified_at") or r["checked_at"]).replace("Z", "+00:00"))
                                   + timedelta(hours=BATCH_HOLD_HOURS)).isoformat()} if _is_batch(r) else {"price_check": r.get("price_check", "daily"),
                                                        **({"price_check_note": r["price_check_note"]} if r.get("price_check_note") else {})}),
                "tier_class": _tier_class({"tier": r["tier"], "interruptible": r["interruptible"], "billing_unit": r["billing_unit"],
                                           "price_status": r.get("price_status", "listed")}) if not r.get("tier_class") else r["tier_class"],
                "offer_type": d.get("offer_type"), "affiliate": bool(d.get("affiliate")),
                "verified_at": r.get("verified_at") or r["checked_at"], "checked_at": r["checked_at"], "source_url": r["source_url"],
                # Brain #247 (additive): every tracked vendor quotes in USD, so no FX conversion is applied (fx_date null);
                # last_verified = when the price itself was last confirmed on the vendor page (same as verified_at).
                "quote_currency": "USD", "fx_date": None, "last_verified": r.get("verified_at") or r["checked_at"],
                "redeem_url": d.get("redeem_url") or r["source_url"], "basis": r["quote"], "evidence": r["evidence"],
                # availability has its own timestamp/cadence, separate from the daily price check (verified_at)
                "availability": availability_for(r["vendor"], r["gpu"], r["vram_gb"], r["tier"], r.get("availability"), price_rec=r)})
    for x in rates:  # Gauge strat2 #4: label every code-carrying link; sort order is untouched
        x.update(referral_fields_for(x))
        x["price_basis_label"] = price_basis_label(x)  # additive: plain-language basis (600me review)
    priced = {r["deal_id"] for r in rates} | {d["id"] for d in deals if d.get("advertiser") in {h["vendor"] for h in held}}  # Gauge G1: held != unpriced
    unpriced = [{"deal_id": d["id"], "advertiser": d.get("advertiser"),
                 "reason": "no structured GPU pricing record", "source_url": d.get("source_url")}
                for d in sorted(deals, key=lambda x: x["id"]) if is_gpu_deal(d) and d["id"] not in priced]
    credits = [{"deal_id": d["id"], "advertiser": d.get("advertiser"), "unit": d.get("unit")}
               for d in deals if is_gpu_deal(d) and d.get("offer_type") in ("free_tier", "trial")]
    return {"rates": rates, "vendors": vendors, "held_stale": held, "unpriced": unpriced, "free_credits": credits,
            "problems": problems}


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
        per = r.get("gpu_count") or 1
        servers = math.ceil(max(gpus, r.get("min_gpus") or 1) / per)
        g = servers * per  # billed GPUs: whole servers/instances only, never fractional
        if r["unit"] == "hour":
            cost = r["price_usd"] * hours_per_month * g
            basis = f"${r['price_usd']}/hr x {hours_per_month} h x {g} GPU"
            if g > gpus:
                basis += f" ({gpus} requested, {g} billed: " + (f"sold only as whole {per}-GPU servers, {servers} instance{'s' if servers > 1 else ''})" if per > 1 else f"minimum {g} GPUs per instance)")
            if r.get("price_status") == "marketplace":
                basis += f"; variable marketplace median, lowest offer ${r['lowest_offer_usd']}/hr"
        else:
            n = max(1, math.ceil(hours_per_month / HOURS_PER_MONTH)) * g
            cost = r["price_usd"] * n
            per = r.get("gpu_count") or 1
            if per > 1:
                basis = (f"${r['price_usd']}/GPU-mo x {n} GPU-month(s) (sold as {per}-GPU servers at "
                         f"${r['server_price_usd']:,.2f}/mo; {gpus} requested, {g} billed), flat regardless of hours")
            else:
                basis = f"${r['price_usd']}/mo x {n} server(s), flat regardless of hours"
        out.append({**r, "monthly_cost_usd": round(cost, 2), "calc": basis,
                    "requested_gpus": gpus, "billed_gpus": g, "instances": servers})
    # Reservation / commitment prices are shown but never ranked as "cheapest": they sort after every pay-as-you-go row.
    return sorted(out, key=lambda x: (_tier_class(x) == "reserved", x["monthly_cost_usd"], x["advertiser"] or "", x["gpu"]))


def live_rate_count(deals: list[dict], vendor_docs: list[dict] | None = None) -> int:
    """The one public GPU rate count: ranked rates published in /api/v1/gpu-prices.json. Never hardcode it."""
    return len(build_rates(deals, vendor_docs)["rates"])


# Availability coverage (T73 surfacing on /gpu/): vendors with no free stock signal are labelled, not counted as gaps.
UNMEASURABLE_NO_SIGNAL = ("99Stack", "Civo", "CoreWeave", "DigitalOcean", "E2E", "Modal", "Nebius", "Ucartz", "RunC.AI", "SaladCloud")
UNMEASURABLE_ACCOUNT = ("Hyperstack", "Novita")
# rel055 (Scout): Scout does not collect Jarvislabs stock and Thunder Compute collection is paused. Their rows keep
# their cited prices; stock is labelled with this text on /gpu/ pages (existing status text and fields only).
NO_STOCK_COLLECTION = ("Jarvislabs", "Thunder Compute")
NO_STOCK_COLLECTION_LABEL = "unmeasurable (no stock collection)"
AVAILABILITY_TARGET = 0.80
# Account-gated vendors whose stock Scout now collects (T73 rev 4, Gauge-passed): counted as soon as any of their
# rows carries a real stock reading; until then they stay labelled "account required". Thunder Compute stays labelled
# (its rows stay null: not reachable from the collector).
ACCOUNT_COLLECTED = ("Hyperstack", "Novita")


def unmeasurable_reason(vendor: str, measured_vendors: frozenset = frozenset()):
    if vendor in measured_vendors and any(vendor.startswith(p) for p in ACCOUNT_COLLECTED):
        return None
    if any(vendor.startswith(p) for p in UNMEASURABLE_NO_SIGNAL):
        return "no public stock signal"
    if any(vendor.startswith(p) for p in UNMEASURABLE_ACCOUNT):
        return "account required"
    if any(vendor.startswith(p) for p in NO_STOCK_COLLECTION):
        return NO_STOCK_COLLECTION_LABEL
    return None


def availability_measured(r: dict) -> bool:
    """A real stock status: available / out of stock when checked, or stale with its last-check timestamp.
    'unknown' and static vendor page labels are not measurements."""
    a = r.get("availability") or {}
    if a.get("price_join_failed") or a.get("two_read_gap_ok") is False:  # dropped claims are not measurements
        return False
    st = str(a.get("status") or "unknown")
    return st in ("available when checked", "out of stock when checked") or st.startswith("unknown (stale availability, last checked")


MARKETPLACE_VENDORS = ("Vast.ai", "Clore", "Lium")  # T73 F5: counted, labelled "marketplace listing"
MARKETPLACE_LABEL = "marketplace listing"
COVERAGE_RULE = ("Interruptible (spot) rows are left out of coverage entirely (numerator and denominator). Marketplace "
                 "rows (Vast.ai, Clore.ai) count and are labelled \u201cmarketplace listing\u201d: an unrented marketplace "
                 "server counts as available.")


def is_marketplace_row(r: dict) -> bool:
    return r.get("price_status") == "marketplace" or r.get("tier_class") == "marketplace" or str(r.get("advertiser") or "").startswith(MARKETPLACE_VENDORS)


def availability_coverage(rates: list[dict]) -> dict:
    """Per canonical model: rows, rows from vendors with a free stock signal (measurable), and how many of those are
    measured. Computed from whatever feed is current. T73 F5 (owner decision 2026-11-02): interruptible/spot rows are
    excluded from every count; marketplace rows count and are listed with a 'marketplace listing' label."""
    spot = [r for r in rates if r.get("interruptible")]
    rates = [r for r in rates if not r.get("interruptible")]
    mv = frozenset(r["advertiser"] for r in rates if availability_measured(r))
    models = {}
    for r in rates:
        m = models.setdefault(r.get("canonical_model") or canonical_model(r["gpu"]),
                              {"rows": 0, "measurable": 0, "measured": 0})
        m["rows"] += 1
        if unmeasurable_reason(r["advertiser"], mv) is None:
            m["measurable"] += 1
            m["measured"] += availability_measured(r)
    for m in models.values():
        m["coverage"] = round(m["measured"] / m["measurable"], 4) if m["measurable"] else None
        m["meets_target"] = m["coverage"] is not None and m["coverage"] >= AVAILABILITY_TARGET
    tot = {k: sum(m[k] for m in models.values()) for k in ("rows", "measurable", "measured")}
    tot["coverage"] = round(tot["measured"] / tot["measurable"], 4) if tot["measurable"] else None
    unm = sorted({(r["advertiser"], unmeasurable_reason(r["advertiser"], mv)) for r in rates if unmeasurable_reason(r["advertiser"], mv)})
    market = [{"vendor": r["advertiser"], "gpu": r["gpu"], "vram_gb": r.get("vram_gb"), "label": MARKETPLACE_LABEL,
               "measured": availability_measured(r)} for r in rates if is_marketplace_row(r)]
    # Gauge T73 F1-F6 #4: say why claims are missing, from the feed itself (price check vs expiry vs two-read gap)
    lab = lambda r: f"{r['advertiser']} {r['gpu']}" + (f" {r['vram_gb']}GB" if r.get("vram_gb") else "")
    av = lambda r: r.get("availability") or {}
    dropped = {"price_changed": [lab(r) for r in rates if av(r).get("price_join_failed")],
               "two_read_gap": [lab(r) for r in rates if av(r).get("two_read_gap_ok") is False and not av(r).get("price_join_failed")],
               "expired": [lab(r) for r in rates if av(r).get("availability_stale") and not av(r).get("price_join_failed")
                           and av(r).get("two_read_gap_ok") is not False]}
    return {"target": AVAILABILITY_TARGET, "models": models, "totals": tot, "unmeasurable": unm,
            "excluded_interruptible_rows": len(spot), "marketplace_rows": market, "rule": COVERAGE_RULE,
            "dropped_claims": dropped}
