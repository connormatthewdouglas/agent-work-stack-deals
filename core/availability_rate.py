"""T112: availability-adjusted expected cost (additive fields; never replaces the raw rate).

availability_rate_7d = observed in-stock share over the trailing 7 days of Scout checks (data/gpu_availability/rate_7d.json,
built by scripts/availability_rate_7d.py). expected_cost_usd = hourly rate / max(availability_rate_7d, FLOOR), an
estimate: a row that is rarely in stock costs more in practice (waiting, retries, falling back to a dearer vendor).
Rows with fewer than MIN_CHECKS known readings get nulls, never a guess.
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "gpu_availability" / "rate_7d.json"
FLOOR = 0.1
MIN_CHECKS = 6
LABEL = ("estimate: hourly rate / max(7-day observed in-stock share, 0.1); not a price. Based on Lantern Scout stock "
         "checks; unknown when fewer than 6 readings.")
_CACHE: dict | None = None


def _index() -> dict:
    global _CACHE
    if _CACHE is None:
        doc = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}
        _CACHE = {"window_end": doc.get("window_end"),
                  "rows": {(r["vendor"], r["gpu"], r.get("vram_gb"), r["tier"]): r for r in doc.get("rows") or []}}
    return _CACHE


def fields(vendor: str, gpu: str, vram_gb, tier: str, hourly) -> dict:
    ix = _index()
    r = ix["rows"].get((vendor, gpu, vram_gb, tier))
    if not r or r["checks"] < MIN_CHECKS or not isinstance(hourly, (int, float)):
        return {"availability_rate_7d": None, "expected_cost_usd": None}
    return {"availability_rate_7d": {"rate": r["rate"], "checks": r["checks"], "in_stock_checks": r["in_stock_checks"],
                                     "window_end": ix["window_end"]},
            "expected_cost_usd": round(hourly / max(r["rate"], FLOOR), 4), "expected_cost_label": LABEL}
