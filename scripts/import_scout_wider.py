"""Import Scout's wider-GPU price batch (out/wider_gpu_prices_latest.json, schema 3.2, batch "wider-gpu") into
data/gpu_pricing/<vendor>.json, merged with the existing records. Extra row keys (verified_at, batch) are tolerated.
Re-running replaces that vendor's previous wider-gpu records. Rules: priced rows only; T4 stays unpriced;
held_below_min_offers rows skipped; Clore and TensorDock never imported; pulled vendors (core/compliance) skipped;
B300 = 288 GB; Vast A40/L4/RTX A4000 = 48/24/16 GB with the vendor's own figure kept in vram_note.
Usage: import_scout_wider.py <wider_gpu_prices_latest.json> [--dry-run]"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.compliance import is_pulled  # noqa: E402
from core.gpu import family_of  # noqa: E402

PRICING = ROOT / "data" / "gpu_pricing"
FILES = {"RunPod": "runpod.json", "Lambda": "lambda.json", "Vast.ai": "vast.json", "Verda": "verda.json", "Oblivus": "oblivus.json"}
NEVER = ("clore", "tensordock")
MAX_AGE = timedelta(hours=36)  # prices refresh daily
VRAM_FIX = {("B300", None): 288, ("A40", "Vast.ai"): 48, ("L4", "Vast.ai"): 24, ("RTX A4000", "Vast.ai"): 16}


def _ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def normalize(r: dict) -> dict | None:
    v = r.get("vendor") or ""
    if any(n in v.lower() for n in NEVER) or v not in FILES:
        return None
    if r.get("price_usd_hr") is None or r.get("feed_status") == "held_below_min_offers":
        return None
    m = r.get("gpu_model") or ""
    gpu = re.sub(r"\s*\d+\s*GB$", "", m).strip()
    if family_of(gpu) in (None, "t4"):
        return None
    base = re.sub(r"\s+(SXM\d*|PCIe)$", "", gpu)
    form = (re.search(r"\b(SXM\d*|PCIe)\b", gpu) or [None])[0]
    vram = r.get("vram_gb")
    note = r.get("vram_note")
    fix = VRAM_FIX.get((base, None)) or VRAM_FIX.get((base, v))
    if fix and vram != fix:
        note = f"vendor reports {vram}GB" if vram else note
        vram = fix
    price = float(r["price_usd_hr"])
    when = r.get("verified_at") or r.get("checked_at") or r.get("collected_at")
    quote = f"{m} {r.get('price_basis') or ''} ${price}/hr".strip()
    ev = {"source_url": r["source_url"], "quote": quote, "checked_at": when}
    rec = {"vendor": v, "gpu": gpu, "vram_gb": vram, "price_usd": price, "billing_unit": "hourly", "hourly_usd": price,
           "interruptible": "spot" in (r.get("tier") or "").lower(), "tier": r.get("tier"), "form_factor": form,
           "quote": quote, "source_url": r["source_url"], "checked_at": when, "evidence": ev, "verified_at": when,
           "batch": "wider-gpu"}
    if note:
        rec["vram_note"] = note
    return rec


def main() -> None:
    src = Path(sys.argv[1])
    dry = "--dry-run" in sys.argv
    d = json.loads(src.read_text())
    if str(d.get("version")) != "3.2" or d.get("batch") != "wider-gpu":
        raise SystemExit(f"refusing: expected version 3.2 batch wider-gpu, got {d.get('version')}/{d.get('batch')}")
    if datetime.now(timezone.utc) - _ts(d["collected_at"]) > MAX_AGE:
        raise SystemExit(f"refusing: wider batch {d['collected_at']} older than {MAX_AGE}")
    by_vendor: dict = {}
    for r in d.get("rows") or []:
        if r.get("batch") not in (None, "wider-gpu"):
            continue
        rec = normalize(r)
        if rec:
            by_vendor.setdefault(rec["vendor"], []).append(rec)
    total = 0
    for v, recs in sorted(by_vendor.items()):
        p = PRICING / FILES[v]
        if not p.is_file():
            continue
        doc = json.loads(p.read_text())
        if is_pulled(doc.get("deal_id")):
            continue
        keep = [x for x in doc.get("records") or [] if x.get("batch") != "wider-gpu"]
        have = {(x.get("gpu"), x.get("tier"), x.get("vram_gb")) for x in keep}
        new = [x for x in recs if (x["gpu"], x["tier"], x["vram_gb"]) not in have]  # existing curated rows win
        doc["records"] = keep + new
        total += len(new)
        print(f"{v}: +{len(new)} wider-gpu records")
        if not dry:
            p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wider-gpu records={total}{' (dry run)' if dry else ''}")


if __name__ == "__main__":
    main()
