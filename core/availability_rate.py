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
_SCOUT_AT = None  # now_utc() used when _SCOUT was built from the T112 file; None = test-injected


def _vkey(vendor) -> str:
    return str(vendor).split(" ")[0].lower()


def _scout_index() -> dict:
    """Scout's T112 rows keyed (vendor first word, gpu_model, vram_gb, tier); {} when missing, unreadable or stale.

    The 24h window follows the pinned build clock (LW_AVAIL_NOW / now_utc), not wall clock.
    Otherwise a regenerate after the window flips scout_t112 to git_history and pages-match
    dest tests (HEAD still has the scout_t112 feed) fail during GPU refresh (run 43616682835).
    A cached index is rebuilt when the clock changes; otherwise a stale load in the same
    process (tests, or generate then a later pin) would keep the empty map.
    """
    global _SCOUT, _SCOUT_AT
    from core.gpu_availability import now_utc
    clock = now_utc()
    # Tests inject a ready-made index by setting _SCOUT without a clock tag.
    if _SCOUT is not None and _SCOUT_AT is None:
        return _SCOUT
    if _SCOUT is not None and _SCOUT_AT == clock:
        return _SCOUT
    _SCOUT = {}
    _SCOUT_AT = clock
    try:
        doc = json.loads(SCOUT_PATH.read_text(encoding="utf-8")) if SCOUT_PATH.exists() else {}
        gen = doc.get("generated_at")
        age = (clock - datetime.fromisoformat(gen.replace("Z", "+00:00"))).total_seconds() / 3600 if gen else None
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


def _observed_hours(first, last, end) -> float | None:
    """P58: hours from first_check_at to last_check_at (else window_end), 1 decimal; null if no usable stamps."""
    if not first:
        return None
    end_stamp = last or end
    if not end_stamp:
        return None
    try:
        a = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end_stamp).replace("Z", "+00:00"))
        hours = (b - a).total_seconds() / 3600
        return round(hours, 1) if hours >= 0 else None
    except (ValueError, TypeError, AttributeError):
        return None


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
            "observed_hours": _observed_hours(first, last, end),  # P58: real coverage next to the nominal 7d window
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


# Display-only thresholds for site copy (P60). Not feed fields. A sample is small when
# the feed already marks it insufficient (< MIN_CHECKS), or when N is about 5-10 checks,
# or when observed coverage is under a day.
SMALL_SAMPLE_MAX_CHECKS = 10
SMALL_SAMPLE_MAX_HOURS = 24
# Typical spacing in the live trailing window: observed_hours / (known_checks - 1) is about 2.7 h.
TYPICAL_CHECK_GAP_H = 2.7
RATE_FOOTNOTE = (
    f"A 0/N reading means not observed in stock in N checks. Checks in this window typically run "
    f"about every {TYPICAL_CHECK_GAP_H:g} hours, so a short restock can be missed. Availability "
    f"comparisons with a small sample (about 5–10 checks, or less than {SMALL_SAMPLE_MAX_HOURS} hours "
    f"of coverage) are labelled as such and should be read as price-only; N is stated."
)


def _count(value) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def known_count(ar) -> int | None:
    if not isinstance(ar, dict):
        return None
    return _count(ar.get("known_checks", ar.get("checks")))


def stocked_count(ar) -> int | None:
    if not isinstance(ar, dict):
        return None
    return _count(ar.get("in_stock_checks"))


def is_small_sample(ar) -> bool:
    """True when a trailing availability reading is too small to treat as a firm comparison."""
    n = known_count(ar)
    if not n:
        return False
    if ar.get("sample_status") == "insufficient_sample" or ar.get("sufficient_sample") is False:
        return True
    if n <= SMALL_SAMPLE_MAX_CHECKS:
        return True
    hours = ar.get("observed_hours")
    return isinstance(hours, (int, float)) and not isinstance(hours, bool) and 0 <= hours < SMALL_SAMPLE_MAX_HOURS


def rate_phrase(ar) -> str | None:
    """Site wording for a trailing 0/N or K/N availability reading. None when the feed has no usable counts."""
    n, k = known_count(ar), stocked_count(ar)
    if n is None or k is None or n == 0:
        return None
    unit = "check" if n == 1 else "checks"
    if k == 0:
        text = f"not observed in stock in {n} {unit}"
    else:
        text = f"observed in stock in {k} of {n} {unit}"
    if is_small_sample(ar):
        text += f" (small sample, N={n}; treat availability as price-only)"
    return text


def zero_of_n_phrase(ar) -> str | None:
    """The 0/N wording only, when the trailing reading is zero in-stock checks over N known checks."""
    phrase = rate_phrase(ar)
    if phrase and stocked_count(ar) == 0:
        return phrase
    return None


def overlay_published_rates(rows: list[dict], published_path: Path | None = None) -> list[dict]:
    """Keep the already-published trailing rate when a generate would silently
    fall back from a fresh Scout T112 series to sparser git history because the
    Scout file is older than SCOUT_MAX_AGE_H. Copy/page regenerations must not
    rewrite the public feed's observations. Ranking is unchanged.
    """
    path = published_path or Path(__file__).resolve().parents[1] / "api" / "v1" / "gpu-prices.json"
    try:
        prev = { (r.get("advertiser"), r.get("gpu"), r.get("vram_gb"), r.get("tier")): r.get("availability_rate_7d")
                 for r in json.loads(path.read_text(encoding="utf-8")).get("rates") or [] }
    except (OSError, ValueError, TypeError, AttributeError):
        return rows
    for r in rows:
        old = prev.get((r.get("advertiser"), r.get("gpu"), r.get("vram_gb"), r.get("tier")))
        new = r.get("availability_rate_7d")
        if isinstance(old, dict) and old.get("source") == "scout_t112" and (
                not isinstance(new, dict) or new.get("source") == "git_history"):
            r["availability_rate_7d"] = old
    return rows
