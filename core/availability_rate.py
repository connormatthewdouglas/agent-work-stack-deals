"""T112: availability-adjusted expected cost (additive fields; never replaces the raw rate).

availability_rate_7d = observed in-stock share over the trailing 7 days of Scout checks (data/gpu_availability/rate_7d.json,
built by scripts/availability_rate_7d.py). expected_cost_usd = hourly rate / max(availability_rate_7d, FLOOR), an
estimate: a row that is rarely in stock costs more in practice (waiting, retries, falling back to a dearer vendor).
Rows with fewer than MIN_CHECKS known readings get nulls, never a guess.

Preferred source: Scout's own t112_availability_rate_7d.json (copied verbatim from scout-data latest/ by the scout-import
workflow to data/gpu_availability/scout_rate_7d.json). Used per row when the file is present, no older than SCOUT_MAX_AGE_H
and has a row for the key; otherwise the git-history file (rate_7d.json) is used. availability_rate_7d.source says which.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "gpu_availability" / "rate_7d.json"
SCOUT_PATH = PATH.with_name("scout_rate_7d.json")
SCOUT_MAX_AGE_H = 24
FLOOR = 0.1
MIN_CHECKS = 6
LABEL = ("estimate: hourly rate / max(7-day observed in-stock share, 0.1); not a price. Based on Lantern Scout stock "
         "checks; unknown when fewer than 6 readings.")
_CACHE: dict | None = None
_SCOUT: dict | None = None


def _vkey(vendor) -> str:
    return str(vendor).split(" ")[0].lower()


def _scout_index() -> dict:
    """Scout's T112 rows keyed (vendor first word, gpu_model, vram_gb, tier); {} when missing, unreadable or stale."""
    global _SCOUT
    if _SCOUT is None:
        _SCOUT = {}
        try:
            doc = json.loads(SCOUT_PATH.read_text(encoding="utf-8")) if SCOUT_PATH.exists() else {}
            gen = doc.get("generated_at")
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(gen.replace("Z", "+00:00"))).total_seconds() / 3600 if gen else None
            if doc.get("kind") == "t112_availability_rate_inputs" and age is not None and 0 <= age <= SCOUT_MAX_AGE_H:
                for r in doc.get("rows") or []:
                    _SCOUT[(_vkey(r.get("vendor")), r.get("gpu_model"), r.get("vram_gb"), r.get("tier"))] = (r, gen)
        except (ValueError, TypeError, AttributeError, OSError):
            _SCOUT = {}
    return _SCOUT


def _index() -> dict:
    global _CACHE
    if _CACHE is None:
        doc = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}
        _CACHE = {"window_end": doc.get("window_end"),
                  "rows": {(r["vendor"], r["gpu"], r.get("vram_gb"), r["tier"]): r for r in doc.get("rows") or []}}
    return _CACHE


def fields(vendor: str, gpu: str, vram_gb, tier: str, hourly) -> dict:
    if not isinstance(hourly, (int, float)):
        return {"availability_rate_7d": None, "expected_cost_usd": None}
    hit = _scout_index().get((_vkey(vendor), gpu, vram_gb, tier))
    if hit:
        sr, gen = hit
        n, rate = sr.get("known_checks_7d"), sr.get("availability_rate_7d")
        if not isinstance(n, int) or n < MIN_CHECKS or not isinstance(rate, (int, float)) or sr.get("sufficient_sample") is False:
            return {"availability_rate_7d": None, "expected_cost_usd": None}
        return {"availability_rate_7d": {"rate": rate, "checks": n, "in_stock_checks": sr.get("in_stock_checks_7d"),
                                         "window_end": sr.get("last_check_at") or gen, "source": "scout_t112"},
                "expected_cost_usd": round(hourly / max(rate, FLOOR), 4), "expected_cost_label": LABEL}
    ix = _index()
    r = ix["rows"].get((vendor, gpu, vram_gb, tier))
    if not r or r["checks"] < MIN_CHECKS or not isinstance(hourly, (int, float)):
        return {"availability_rate_7d": None, "expected_cost_usd": None}
    return {"availability_rate_7d": {"rate": r["rate"], "checks": r["checks"], "in_stock_checks": r["in_stock_checks"],
                                     "window_end": ix["window_end"], "source": "git_history"},
            "expected_cost_usd": round(hourly / max(r["rate"], FLOOR), 4), "expected_cost_label": LABEL}
