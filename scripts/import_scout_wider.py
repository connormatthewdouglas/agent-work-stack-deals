"""Import Scout's wider-GPU price batch (out/wider_gpu_prices_latest.json, schema 3.2, batch "wider-gpu") into
data/gpu_pricing/<vendor>.json, merged with the existing records. Extra row keys (verified_at, batch) are tolerated.
Re-running removes every previous wider-gpu record (idempotent); curated rows are never touched. Rules: priced rows only; T4 stays unpriced;
held_below_min_offers rows skipped; Clore and TensorDock never imported; pulled vendors (core/compliance) skipped;
B300 keeps the vendor's own memory figure; rows with missing allocation/evidence are held (listed as unresolved in wider_meta.json); Vast A40/L4/RTX A4000 = 48/24/16 GB with the vendor's own figure kept in vram_note.
Usage: import_scout_wider.py <wider_gpu_prices_latest.json> [--dry-run]"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.compliance import is_pulled  # noqa: E402
from core.gpu import INTERRUPTIBLE_TIER_RE, family_of  # noqa: E402
from core.owner_hold import hold_names, is_held  # noqa: E402
from core.source_urls import valid_source_url  # noqa: E402
from core import serverless  # noqa: E402  (T63: one shared serverless/per-second rule)

PRICING = ROOT / "data" / "gpu_pricing"
META = ROOT / "data" / "gpu_availability" / "wider_meta.json"
FILES = {"RunPod": "runpod.json", "Lambda": "lambda.json", "Vast.ai": "vast.json", "Verda": "verda.json", "Oblivus": "oblivus.json"}
NEVER = ("clore", "tensordock")
MIN_VAST_OFFERS = 5  # same floor as core.gpu MIN_MARKET_OFFERS
MAX_AGE = timedelta(hours=36)  # prices refresh daily
# B300 is no longer forced to 288 GB (T63): the vendor's own allocation (e.g. Verda 268 GB) is kept as given.
VRAM_FIX = {("L40S", None): 48, ("A40", "Vast.ai"): 48, ("L4", "Vast.ai"): 24, ("RTX A4000", "Vast.ai"): 16}
UNITS = {"hourly": 1, "per-second": 3600}
RESERVED_RE = re.compile(r"reserved|commit|\d+\s*-?\s*(?:month|year|yr)\b", re.I)
ONE_GPU_RE = re.compile(r"\b1 GPU\b")
# Serverless / per-second / active-worker prices are not dedicated instance rates (Gauge 1104 #102): held, never imported.
# Interruptible matches core.gpu.INTERRUPTIBLE_TIER_RE (spot, preemptible, interruptible, bid). Community and
# marketplace labels stay non-interruptible. The tier text itself is not rewritten.
# Vendor text Scout copied from the page; price_quote is Scout's own field name for it (Gauge 1108 #102 c).
VERBATIM_KEYS = ("quote_verbatim", "verbatim_text", "price_quote")


def _ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _int(x):
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 1 else None


def serverless_reason(r: dict) -> str | None:
    return serverless.row_reason(r)


def normalize_ex(r: dict) -> tuple[dict | None, str | None]:
    """T63: (record, None) for an importable row, (None, reason) for an unresolved/held row, (None, None) for a skip.
    The full economic offer is carried through: gpu_count, min_gpus and server totals, per-second billing, reserved
    terms and marketplace sample details. Verbatim source text and the importer's normalized summary are separate
    fields; API-derived evidence quotes the actual field and value. Missing allocation or evidence is never guessed."""
    v = r.get("vendor") or ""
    if any(n in v.lower() for n in NEVER):
        return None, None
    priced = r.get("price_usd_hr") is not None or bool(serverless.per_second_keys(r))
    why = serverless_reason(r) if priced else None  # before vendor/GPU checks: a serverless row is always reported as one
    if why:
        return None, why
    if v not in FILES:
        return None, f"unsupported vendor {v!r}"
    if r.get("feed_status") == "held_below_min_offers":
        return None, "thin market: below the minimum offer count"
    if r.get("price_usd_hr") is None and r.get("price_usd_sec") is None:
        return None, None  # stock-only row, never a price
    m = r.get("gpu_model") or ""
    gpu = re.sub(r"\s*\d+\s*GB$", "", m).strip()
    if family_of(gpu) in (None, "t4"):
        return None, None if family_of(gpu) == "t4" else f"unsupported GPU {m!r}"
    unit = r.get("billing_unit") or ("per-second" if r.get("price_usd_sec") is not None else "hourly")
    if unit not in UNITS:
        return None, f"unsupported billing unit {unit!r}"
    raw = r.get("price_usd_sec") if unit == "per-second" else r.get("price_usd_hr")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or raw <= 0:
        return None, f"unsupported price {raw!r}"
    # source_url is the citation. source_detail is evidence text only and is never promoted to the URL
    # (Oblivus rows append ' ("RTX 4090" card)' and that string is not a canonical https URL).
    page = r.get("source_url") or ""
    detail = r.get("source_detail") if isinstance(r.get("source_detail"), str) else ""
    when = r.get("verified_at") or r.get("checked_at") or r.get("collected_at")
    if not (valid_source_url(page) and when):
        return None, "evidence missing: needs an https source_url and a check time"
    try:
        _ts(when)
    except (TypeError, ValueError):
        return None, f"evidence missing: bad check time {when!r}"
    basis = r.get("price_basis") or ""
    verbatim = next((r[k] for k in VERBATIM_KEYS if r.get(k)), None)
    if not (verbatim or basis):
        return None, "evidence missing: no verbatim text and no API field/method"
    # Allocation: explicit fields win; a basis that says "1 GPU" is a 1-GPU allocation; anything else stays held.
    n, mg = _int(r.get("gpu_count")), _int(r.get("min_gpus"))
    if r.get("gpu_count") is not None and n is None or r.get("min_gpus") is not None and mg is None:
        return None, "unsupported allocation: gpu_count/min_gpus must be whole numbers >= 1"
    if n is None and ONE_GPU_RE.search(basis):
        n = 1
    if n is None:
        return None, "allocation missing: the source does not state the GPUs per price (gpu_count/min_gpus)"
    mg = mg or (n if r.get("whole_server_only") else 1)
    server = r.get("server_price_usd_hr") if unit == "hourly" else r.get("server_price_usd_sec")
    if n > 1:
        price = float(server) if isinstance(server, (int, float)) and server > 0 else round(float(raw) * n, 6)
    else:
        price = float(raw)
    factor = UNITS[unit]
    hourly = round(price * factor / n, 4)
    base = re.sub(r"\s+(SXM\d*|PCIe)$", "", gpu)
    form = (re.search(r"\b(SXM\d*|PCIe)\b", gpu) or [None])[0]
    vram = r.get("vram_gb")
    note = r.get("vram_note")
    fix = VRAM_FIX.get((base, None)) or VRAM_FIX.get((base, v))
    if fix and vram != fix:
        note = f"vendor reports {vram}GB" if vram else note
        vram = fix
    offers = r.get("offer_count")
    if v == "Vast.ai" and (offers or 0) < MIN_VAST_OFFERS:
        return None, "thin market: below the minimum offer count"
    unit_txt = "/s" if unit == "per-second" else "/hr"
    alloc = f"{n} GPU" + ("s" if n > 1 else "") + (f", min {mg}" if mg > 1 else "")
    summary = f"{m} {r.get('tier') or ''} ${raw}{unit_txt} ({alloc}) [importer summary, not source text]".replace("  ", " ")
    if verbatim:
        quote, kind = str(verbatim), "verbatim"
    elif v == "Vast.ai" and offers:
        quote, kind = (f"Vast offers API: median per-GPU dph_total over {offers} offers"
                       + (f" on {r['distinct_machines']} machines" if r.get("distinct_machines") else "") + f" = {raw}"), "api_field"
    else:
        quote, kind = f"{basis}: {raw}", "api_field"
    quote = quote[:200]
    tier = r.get("tier")
    intr = bool(INTERRUPTIBLE_TIER_RE.search(tier or ""))
    evidence = {"source_url": page, "quote": quote, "checked_at": when}
    rec = {"vendor": v, "gpu": gpu, "vram_gb": vram, "price_usd": price, "billing_unit": unit, "hourly_usd": hourly,
           "interruptible": intr, "tier": tier, "form_factor": form,
           "quote": quote, "source_url": page,
           "checked_at": when, "evidence": evidence,
           "evidence_kind": kind, "normalized_summary": summary, "verified_at": when,
           "batch": "wider-gpu", "price_check": "batch"}  # Gauge G5: re-read only when Scout pushes a batch
    if detail.strip() and detail.strip() != page:
        rec["source_detail"] = detail.strip()  # evidence text, never the citation URL
    if kind == "api_field":
        rec["evidence_method"] = basis or "Vast offers API median"
    if n > 1:
        rec.update(gpu_count=n, server_hourly_usd=round(price * factor, 4))
    if mg > 1:
        rec["min_gpus"] = mg
    if RESERVED_RE.search(r.get("tier") or "") or r.get("term"):
        rec["tier_class"] = "reserved"
        if r.get("term"):
            rec["term"] = r["term"]
    if note:
        rec["vram_note"] = note
    if v == "Vast.ai":
        sample = {k: r[k] for k in ("offer_count", "distinct_machines", "lowest_offer_usd", "price_basis") if r.get(k) is not None}
        rec["market_sample"] = sample  # offer_count stays out of the top level (marketplace-only field, T41-19)
        lo = r.get("lowest_offer_usd")
        if isinstance(lo, (int, float)) and 0 < lo <= hourly and n == 1:
            rec.update(price_status="marketplace", lowest_offer_usd=lo, offer_count=offers, price_basis=basis or "median")
        else:
            rec.update(price_status="listed", price_basis=f"{basis} ({offers} verified offers)")
    return rec, None


def normalize(r: dict) -> dict | None:
    return normalize_ex(r)[0]


def apply(docs: dict, rows: list[dict], names: list[str] | None = None) -> tuple[dict, list[dict], int]:
    """Pure merge: every vendor file loses ALL its previous wider-gpu rows (stale batch rows go even when the vendor is
    absent from this batch); curated rows are never touched and win on (gpu, tier, vram_gb). Idempotent.
    Owner-held vendors are omitted entirely: their documents are not returned, so the caller does not rewrite them."""
    names = list(names or [])
    by_vendor: dict = {}
    unresolved = []
    seen = set()
    for r in rows:
        if is_held(r.get("vendor"), names):
            continue
        if r.get("batch") not in (None, "wider-gpu"):
            continue
        rec, why = normalize_ex(r)
        if why:
            unresolved.append({"vendor": r.get("vendor"), "gpu_model": r.get("gpu_model"), "tier": r.get("tier"), "reason": why})
        if rec:
            key = (rec["vendor"], rec["gpu"], rec["tier"], rec["vram_gb"])
            if key not in seen:
                seen.add(key)
                by_vendor.setdefault(rec["vendor"], []).append(rec)
    total = 0
    out = {}
    for v, doc in docs.items():
        if is_held(v, names) or is_held((doc or {}).get("vendor"), names):
            continue
        if doc is None or is_pulled(doc.get("deal_id")):
            continue
        doc = json.loads(json.dumps(doc))
        recs = by_vendor.get(v, [])
        for x in recs:  # records carry the vendor file's own name (e.g. "Verda (formerly DataCrunch)")
            x["vendor"] = doc.get("vendor") or x["vendor"]
        keep = [x for x in doc.get("records") or [] if x.get("batch") != "wider-gpu"]
        have = {(x.get("gpu"), x.get("tier"), x.get("vram_gb")) for x in keep}
        new = [x for x in recs if (x["gpu"], x["tier"], x["vram_gb"]) not in have]  # existing curated rows win
        doc["records"] = keep + new
        total += len(new)
        out[v] = doc
    return out, unresolved, total


def main() -> None:
    # Owner hold is resolved before any vendor file is read or hashed and before unresolved rows are recorded.
    names = hold_names()
    src = Path(sys.argv[1])
    dry = "--dry-run" in sys.argv
    d = json.loads(src.read_text())
    if str(d.get("version")) != "3.2" or d.get("batch") != "wider-gpu":
        raise SystemExit(f"refusing: expected version 3.2 batch wider-gpu, got {d.get('version')}/{d.get('batch')}")
    if datetime.now(timezone.utc) - _ts(d["collected_at"]) > MAX_AGE:
        raise SystemExit(f"refusing: wider batch {d['collected_at']} older than {MAX_AGE}")
    incoming = d.get("rows") or []
    held_skipped = sum(1 for r in incoming if is_held(r.get("vendor"), names))
    rows = [r for r in incoming if not is_held(r.get("vendor"), names)]
    docs = {}
    for v, f in FILES.items():
        if is_held(v, names):
            print(f"{v}: owner hold, file unchanged")
            continue
        p = PRICING / f
        docs[v] = json.loads(p.read_text()) if p.is_file() else None
    new_docs, unresolved, total = apply(docs, rows, names)
    for v, doc in sorted(new_docs.items()):
        n = sum(1 for x in doc["records"] if x.get("batch") == "wider-gpu")
        print(f"{v}: {n} wider-gpu records")
        if not dry:
            (PRICING / FILES[v]).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for u in unresolved:
        print(f"unresolved: {u['vendor']} {u['gpu_model']} ({u['tier']}): {u['reason']}")
    gen = os.environ.get("LW_WIDER_GEN") or d.get("generation_id") or d["collected_at"]
    if not dry:  # carried into gpu-prices.json as wider_generation_id
        META.write_text(json.dumps({"wider_generation_id": gen, "wider_collected_at": d["collected_at"],
                                    "wider_records": total, "unresolved": unresolved,
                                    "owner_hold_skipped": held_skipped}, indent=2) + "\n")
    print(f"wider-gpu records={total} owner_hold_skipped={held_skipped}{' (dry run)' if dry else ''}")


if __name__ == "__main__":
    main()
