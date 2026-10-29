"""Availability attached to GPU rates (T11/T19), from data/gpu_availability/latest.json (Lantern Scout v2).

Display rules: unknown -> "unknown" (never "out of stock"); availability carries its own checked_at and cadence
(about every 4 h for marketplace/stock signals) separate from the daily price check; stock is never a guarantee."""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "gpu_availability" / "latest.json"
NOTE = "Stock changes within minutes; this is a snapshot from the time shown, not a guarantee."
VAST_NOTE = "Vast.ai: offer count is consistency-checked against the same snapshot as the median price only."
_CACHE: dict | None = None


def _index() -> dict:
    global _CACHE
    if _CACHE is None:
        rows = json.loads(PATH.read_text(encoding="utf-8"))["rows"] if PATH.exists() else []
        _CACHE = {(r["vendor"], r["gpu"], r.get("vram_gb"), r["tier"]): r for r in rows}
    return _CACHE


def _tier_key(tier: str) -> str:
    return tier.replace("Marketplace on-demand (verified; median per GPU)", "Marketplace on-demand (verified; median per GPU)")


def availability_for(vendor: str, gpu: str, vram_gb, tier: str) -> dict:
    r = _index().get((vendor, gpu, vram_gb, _tier_key(tier)))
    if not r or r.get("in_stock") is None:
        out = {"status": "unknown", "in_stock": None, "checked_at": (r or {}).get("availability_checked_at"), "note": NOTE}
        if r and r.get("stock_level") is None and vendor == "RunPod":
            out["detail"] = "RunPod reported no stock level for this tier"
        return out
    out = {"status": "available when checked" if r["in_stock"] else "no rentable offers when checked",
           "in_stock": r["in_stock"], "checked_at": r.get("availability_checked_at"),
           "refresh": "availability checked about every 4 h (prices daily)",
           "note": NOTE}
    for k in ("offer_count", "stock_level", "available_regions"):
        if r.get(k) is not None:
            out[k] = r[k]
    if vendor == "Vast.ai":
        out["consistency_note"] = VAST_NOTE
    return out
