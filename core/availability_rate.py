"""T116: observed stock frequency is descriptive, never a dollar estimate.

The legacy expected_cost_usd field is retained as null with an explicit deprecation label.
Stock observations do not predict a bill, time-to-capacity, or a budget verdict.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "gpu_availability" / "rate_7d.json"
SCOUT_PATH = PATH.with_name("scout_rate_7d.json")
SCOUT_MAX_AGE_H = 24
MIN_CHECKS = 6
LABEL = ("deprecated (T116): expected_cost_usd is always null; observed stock frequency does not predict "
         "a quote, bill, or budget. Use the published hourly rate for compute costs.")
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
        _CACHE = {"window_start": doc.get("window_start"), "window_days": doc.get("window_days", 7),
                  "window_end": doc.get("window_end"),
                  "rows": {(r["vendor"], r["gpu"], r.get("vram_gb"), r["tier"]): r for r in doc.get("rows") or []}}
    return _CACHE


def _split(unknown, never_ran, no_source) -> tuple:
    """P38: (never_ran_checks, no_source_checks) only when both are counts that add up to unknown_checks; else (None, None)."""
    ok = all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (unknown, never_ran, no_source))
    return (never_ran, no_source) if ok and never_ran + no_source == unknown else (None, None)


def _describe(known, stocked, unknown, start, end, source, first=None, last=None, never_ran=None, no_source=None) -> dict | None:
    """Counts and their observed window; no price weighting or probability forecast."""
    if not isinstance(known, int) or isinstance(known, bool) or known < 0:
        return None
    if not isinstance(stocked, int) or isinstance(stocked, bool) or not 0 <= stocked <= known:
        return None
    if not isinstance(unknown, int) or isinstance(unknown, bool) or unknown < 0:
        unknown = None  # old captures did not retain unknown counts; do not invent a zero
    from core.gpu_availability import now_utc
    try:
        age = (now_utc() - datetime.fromisoformat((last or end).replace("Z", "+00:00"))).total_seconds() / 3600
        stale = not 0 <= age <= SCOUT_MAX_AGE_H
    except (ValueError, TypeError, AttributeError):
        stale = True
    status = "all_unknown" if known == 0 else "insufficient_sample" if known < MIN_CHECKS else "observed"
    return {"rate": round(stocked / known, 4) if known else None,
            "checks": known, "known_checks": known, "unknown_checks": unknown,
            # P38 (additive): unknown_checks split; null when the source did not record why each check was unknown
            **dict(zip(("never_ran_checks", "no_source_checks"), _split(unknown, never_ran, no_source))),
            "total_checks": known + unknown if unknown is not None else None,
            "in_stock_checks": stocked, "window_start": start, "window_end": end,
            "window_days": 7, "first_check_at": first, "last_check_at": last,
            "source": source, "sample_status": status, "sufficient_sample": known >= MIN_CHECKS,
            "window_stale": stale,
            "interpretation": "observed share of known stock checks, not a forecast or monetary estimate"}


def fields(vendor: str, gpu: str, vram_gb, tier: str, hourly) -> dict:
    # Keep the public key for API compatibility; never convert availability into dollars.
    out = {"availability_rate_7d": None, "expected_cost_usd": None, "expected_cost_label": LABEL}
    hit = _scout_index().get((_vkey(vendor), gpu, vram_gb, tier))
    if hit:
        sr, gen = hit
        known, total = sr.get("known_checks_7d"), sr.get("checks_7d")
        unknown = total - known if isinstance(total, int) and isinstance(known, int) else None
        out["availability_rate_7d"] = _describe(known, sr.get("in_stock_checks_7d"), unknown,
            sr.get("first_check_at"), sr.get("last_check_at") or gen, "scout_t112",
            sr.get("first_check_at"), sr.get("last_check_at"),
            sr.get("never_ran_checks_7d"), sr.get("no_source_checks_7d"))  # P38: null until Scout's T112 build emits them
        return out
    ix = _index()
    r = ix["rows"].get((vendor, gpu, vram_gb, tier))
    if r:
        out["availability_rate_7d"] = _describe(r.get("checks"), r.get("in_stock_checks"), r.get("unknown_checks"),
            ix.get("window_start"), ix.get("window_end"), "git_history", r.get("first_check_at"), r.get("last_check_at"),
            r.get("never_ran_checks"), r.get("no_source_checks"))
    return out
