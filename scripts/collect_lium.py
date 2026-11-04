#!/usr/bin/env python3
"""T62 Lium collector (spec: Pax spec-t62-lium-collector-2026-11-02, Brain #279/#112).

Source of truth: GET https://lium.io/api/public/v1/nodes (keyless). pricing.json aggregates (reference/min/max) are
NEVER read as prices (A1): this module does not fetch pricing.json at all.
Derivation per spec section 3: keep nodes with available_now and available_gpu_count > 0, map gpu_model through an
explicit alias table (no fuzzy matching; unmatched strings are quarantined and reported, A6), group by (model, tier);
row price = min price_per_gpu_hour, stock = sum available_gpu_count; the winning node supplies min rental size,
location, rent_url and last_verified_at. Spot and secure stay separate rows (A5). A model/tier with no available node
keeps its record but withdraws the price behind a stale hold (A9 flicker; never republished as live). Payload age is
computed from generated_at, not the vendor flag; older than MAX_AGE_MIN -> nothing is written (A7).
Writes data/gpu_pricing/lium.json (a new vendor file; quotes are built from the captured payload values only).
Usage: collect_lium.py [--file nodes.json] [--dry-run]
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "gpu_pricing" / "lium.json"
NODES_URL = "https://lium.io/api/public/v1/nodes"
UA = "Mozilla/5.0 (compatible; LanternWorksPriceCheck/1.1; +https://github.com/connormatthewdouglas/agent-work-stack-deals)"
MAX_AGE_MIN = 60
# nodes gpu_model -> (feed gpu, canonical vram_gb, form_factor). NVL strings map only to NVL rows (A3).
ALIASES = {
    "H100 80GB HBM3": ("H100 SXM", 80, "SXM"),
    "H100 PCIe": ("H100 PCIe", 80, "PCIe"),
    "H100 NVL": ("H100 NVL", 94, "NVL"),
    "H200": ("H200", 141, None),
    "H200 NVL": ("H200 NVL", 141, "NVL"),
    "A100-SXM4-80GB": ("A100 SXM", 80, "SXM"),
    "B200": ("B200", 180, None),
    "B300 SXM6 AC": ("B300", 288, None),
    "L40": ("L40", 48, None),
    "L40S": ("L40S", 48, None),
    "RTX 3090": ("RTX 3090", 24, None),
    "RTX 4090": ("RTX 4090", 24, None),
    "RTX 5090": ("RTX 5090", 32, None),
    "RTX A6000": ("RTX A6000", 48, None),
    "RTX 6000 Ada Generation": ("RTX 6000 Ada", 48, None),
    "RTX PRO 6000 Blackwell Server Edition": ("RTX PRO 6000 Server", 96, None),
}
TIERS = {"secure": "Marketplace secure node",
         "spot": "Marketplace spot node (interruptible)"}
EXTRA = {"status": "unknown", "text": "Not verified in this pass.", "source_url": "https://lium.io/pricing"}


def fetch() -> dict:
    req = urllib.request.Request(NODES_URL, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _iso(s: str) -> str:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).replace(microsecond=0).isoformat()


def derive(payload: dict) -> tuple[dict, list[str]]:
    """{(gpu, tier): group} from one nodes snapshot, plus quarantined (unmatched) gpu_model strings."""
    groups, unmatched = {}, set()
    for n in payload.get("nodes") or []:
        if not (n.get("available_now") is True and (n.get("available_gpu_count") or 0) > 0):
            continue
        if n.get("tier") not in TIERS or not isinstance(n.get("price_per_gpu_hour"), (int, float)) or n["price_per_gpu_hour"] <= 0:
            continue
        a = ALIASES.get(n.get("gpu_model"))
        if a is None:
            unmatched.add(str(n.get("gpu_model")))
            continue
        g = groups.setdefault((a[0], n["tier"]), {"alias": a, "nodes": []})
        g["nodes"].append(n)
    for g in groups.values():
        ns = sorted(g["nodes"], key=lambda n: (n["price_per_gpu_hour"], -n["available_gpu_count"]))
        g["best"], g["stock"], g["node_count"] = ns[0], sum(n["available_gpu_count"] for n in ns), len(ns)
    return groups, sorted(unmatched)


def build(payload: dict, old: dict | None, now: datetime) -> tuple[dict, list[str]]:
    gen = _iso(payload["generated_at"])
    age = now - datetime.fromisoformat(gen)
    if age > timedelta(minutes=MAX_AGE_MIN):
        raise SystemExit(f"refused: nodes snapshot generated_at {gen} is {int(age.total_seconds() // 60)} min old (> {MAX_AGE_MIN})")
    groups, unmatched = derive(payload)
    seen = {}  # model-level VRAM notes = the same note on rows from >= 2 vendor files
    for f in sorted(PATH.parent.glob("*.json")):
        if f != PATH:
            for x in json.loads(f.read_text()).get("records") or []:
                if x.get("vram_note"):
                    seen.setdefault((x["gpu"], x["vram_gb"], x["vram_note"]), set()).add(f.name)
    notes = {(g, v): n for (g, v, n), fs in seen.items() if len(fs) >= 2}
    log = [f"generated_at {gen}; {len(payload.get('nodes') or [])} nodes; {len(groups)} model/tier rows"]
    if unmatched:
        log.append("QUARANTINED (not in alias map, not published): " + ", ".join(unmatched))
    recs = {}
    for (gpu, tier), g in groups.items():
        b, (fg, vram, ff) = g["best"], g["alias"]
        p, mg = b["price_per_gpu_hour"], int(b.get("min_rentable_gpu_count") or 1)
        loc = ", ".join(x for x in (b.get("city"), b.get("country")) if x)
        q = (f"Lium nodes API {gen}: {g['node_count']} available {b['gpu_model']} {tier} nodes, {g['stock']} GPUs free; "
             f"lowest price_per_gpu_hour ${p:g} (min rental {mg} GPU{'s' if mg > 1 else ''}, {loc})")
        r = {"vendor": "Lium", "gpu": fg, "vram_gb": vram, "price_usd": p, "billing_unit": "hourly", "hourly_usd": p,
             "interruptible": tier == "spot", "tier": TIERS[tier], "form_factor": ff,
             "quote": q, "source_url": NODES_URL, "checked_at": gen, "verified_at": gen,
             "price_basis": "lowest price_per_gpu_hour among available nodes in the public nodes feed (never pricing.json reference prices)",
             "lium_model": b["gpu_model"], "node_memory_gb": b.get("gpu_memory_gb"), "rent_url": b.get("rent_url"),
             "node_verified_at": b.get("last_verified_at"), "available_nodes": g["node_count"],
             "availability": {"in_stock": True, "checked_at": gen, "source": NODES_URL, "same_capture_as_price": True,
                              "stock_level": f"{g['stock']} GPUs free on {g['node_count']} nodes",
                              "note": f"Lium public nodes API: {g['stock']} available GPUs ({tier} tier)"},
             "evidence": {"source_url": NODES_URL, "quote": q, "checked_at": gen}}
        if mg > 1:
            r["min_gpus"] = mg
        if notes.get((fg, vram)):  # shared model-level VRAM note (same wording as every other vendor's row)
            r["vram_note"] = notes[(fg, vram)]
        if b.get("gpu_memory_gb") and abs(b["gpu_memory_gb"] - vram) > 2:
            log.append(f"VRAM divergence (A10): {fg} node reports {b['gpu_memory_gb']} GB, canonical {vram} GB")
        recs[(fg, r["tier"])] = r
        log.append(f"{fg} [{tier}]: ${p:g} stock {g['stock']} min {mg}")
    for r in (old or {}).get("records", []):  # A9: vanished rows -> no stock, price withdrawn, never carried forward
        k = (r["gpu"], r["tier"])
        if k in recs:
            continue
        q = f"Lium nodes API {gen}: 0 available {r.get('lium_model', r['gpu'])} nodes in this tier; price withheld"
        r.update(price_usd=None, hourly_usd=None, quote=q, checked_at=gen,
                 availability={"in_stock": False, "checked_at": gen, "source": NODES_URL, "same_capture_as_price": True,
                               "stock_level": "0 GPUs free", "note": "No available node in the Lium public nodes feed"},
                 evidence={"source_url": NODES_URL, "quote": q, "checked_at": gen},
                 stale={"reason": f"no available Lium node at {gen}", "auto": True})
        recs[k] = r
        log.append(f"{r['gpu']} [{r['tier']}]: no available node, held")
    ex = {k: dict(EXTRA, checked_at=gen) for k in ("egress", "storage")}
    ex["interruption"] = {"status": "published", "source_url": NODES_URL, "checked_at": gen,
                          "text": "Secure tier rows are on-demand node rentals; spot tier rows are interruptible capacity."}
    doc = {"vendor": "Lium", "deal_id": None, "source_url": "https://lium.io/", "checked_at": gen,
           "billing_granularity": None, "extras": ex,
           "manual_snapshot": {"reason": "Collected by scripts/collect_lium.py (own workflow, lium-collect.yml), not by the daily page refresh; auto-holds after 7 days without a new capture."},
           "market_note": ("Lium is a GPU marketplace (Bittensor subnet 51). Each row is the cheapest available node per model and tier "
                           "in the public nodes feed, with free-GPU stock and the minimum rental size of that node. "
                           "Lium's pricing.json reference prices are not used."),
           "records": sorted(recs.values(), key=lambda r: (r["gpu"], r["tier"]))}
    return doc, log


def main() -> int:
    args = sys.argv[1:]
    payload = json.loads(Path(args[args.index("--file") + 1]).read_text()) if "--file" in args else fetch()
    old = json.loads(PATH.read_text()) if PATH.exists() else None
    doc, log = build(payload, old, datetime.now(timezone.utc))
    print("\n".join(log))
    if "--dry-run" not in args:
        PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
