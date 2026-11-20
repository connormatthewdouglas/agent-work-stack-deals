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
WINDOW_HOURS = 7 * 24  # planned 7-day stock window; a last_check_at older than this has lapsed
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


def _age_hours(ts, now=None) -> float | None:
    from core.gpu_availability import age_hours
    return age_hours(ts, now)


def _last_observed_rate(ar) -> float | None:
    """The last published rate value. Never invented: null when the last window had no known checks."""
    if not isinstance(ar, dict):
        return None
    if ar.get("window_status") == "lapsed":
        v = ar.get("last_observed_rate")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    v = ar.get("rate")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def lapsed_rate(ar, now=None) -> dict | None:
    """P62: if the 7-day window has no checks in the last 7 days, return a labelled object that keeps
    last_check_at and last_observed_rate, with the current rate null. None when there is no last_check_at
    older than 7 days (and the object is not already lapsed with a last_check_at)."""
    if not isinstance(ar, dict):
        return None
    last = ar.get("last_check_at")
    age = _age_hours(last, now)
    already = ar.get("window_status") == "lapsed"
    if age is None or age < 0:
        return None
    if not already and age <= WINDOW_HOURS:
        return None
    return {
        "rate": None,  # current window has no checks; do not present the old rate as current
        "checks": 0, "known_checks": 0, "unknown_checks": None,
        "never_ran_checks": None, "no_source_checks": None, "total_checks": None,
        "in_stock_checks": 0,
        "window_start": ar.get("window_start"), "window_end": ar.get("window_end"),
        "window_days": 7, "first_check_at": ar.get("first_check_at"), "last_check_at": last,
        "observed_hours": None, "coverage_note": None, "source": ar.get("source"),
        "sample_status": "all_unknown", "sufficient_sample": False, "window_stale": True,
        "interpretation": "observed share of known stock checks, not a forecast or monetary estimate",
        "last_observed_rate": _last_observed_rate(ar),
        "window_status": "lapsed",
        "stale_age_hours": round(age, 1),
    }


def lapsed_phrase(ar) -> str | None:
    """Site wording for a lapsed 7-day window. None when the rate is current or unlabelled."""
    if not isinstance(ar, dict) or ar.get("window_status") != "lapsed":
        return None
    age = ar.get("stale_age_hours")
    if isinstance(age, (int, float)) and not isinstance(age, bool) and age >= 0:
        if age >= 24:
            return f"lapsed · last checked {round(age / 24, 1):g}d ago"
        return f"lapsed · last checked {age:g}h ago"
    return "lapsed"


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
    hours = _observed_hours(first, last, end)
    # P59: one-line note only when actual coverage is shorter than the planned window; otherwise null
    note = f"Covers {hours}h of the planned 7-day window." if hours is not None and hours < 7 * 24 else None
    return {"rate": round(stocked / known, 4) if known else None,
            "checks": known, "known_checks": known, "unknown_checks": unknown,
            # P38 (additive): unknown_checks split; null when the source did not record why each check was unknown
            **dict(zip(("never_ran_checks", "no_source_checks"), _split(unknown, never_ran, no_source))),
            "total_checks": known + unknown if unknown is not None else None,
            "in_stock_checks": stocked, "window_start": start, "window_end": end,
            "window_days": 7, "first_check_at": first, "last_check_at": last,
            "observed_hours": hours,  # P58: real coverage next to the planned 7d window
            "coverage_note": note,
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
    if isinstance(ar, dict) and ar.get("window_status") == "lapsed":
        return None  # P62: current rate is unknown; use lapsed_phrase for the last check
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
        # Keep a fresh published Scout series when generate would fall back to git history,
        # but a 7-day-lapsed series is labelled (current rate null), not copied as current.
        if isinstance(old, dict) and old.get("source") == "scout_t112" and (
                not isinstance(new, dict) or new.get("source") == "git_history"):
            r["availability_rate_7d"] = lapsed_rate(old) or old
            continue
        if converted := lapsed_rate(new):
            r["availability_rate_7d"] = converted
            continue
        if not isinstance(new, dict):
            converted = lapsed_rate(old)
            if converted:
                r["availability_rate_7d"] = converted
    return rows


def window_summary(rates: list[dict] | None) -> dict:
    """File-level counts of ranked rates with no 7-day stock window, plus when current windows began.

    Computed only from row data. A rate has a window when availability_rate_7d is an object
    (including a P38 null rate: checks exist, none were known). Otherwise:
    - signal_no_window_yet: a usable in_stock true/false is present, but no 7d window yet
    - read_no_usable_signal: a stock source was read (source, origin, or checked_at) but in_stock is null
    - no_stock_source: no stock source was read
    earliest_first_check_at is the earliest first_check_at among current windows; null if none.
    """
    no_source = read_no_signal = signal_no_window = 0
    firsts: list[str] = []
    for r in rates or []:
        if not isinstance(r, dict):
            continue
        ar = r.get("availability_rate_7d")
        if isinstance(ar, dict):
            # P62: a lapsed window stays a window object (not no_window), but is not current.
            if ar.get("window_status") != "lapsed":
                ts = ar.get("first_check_at")
                if isinstance(ts, str) and ts:
                    firsts.append(ts)
            continue
        av = r.get("availability") if isinstance(r.get("availability"), dict) else {}
        if av.get("in_stock") is True or av.get("in_stock") is False:
            signal_no_window += 1
        elif av.get("source") or av.get("origin") or av.get("checked_at"):
            read_no_signal += 1
        else:
            no_source += 1
    return {
        "no_window_count": no_source + read_no_signal + signal_no_window,
        "no_stock_source": no_source,
        "read_no_usable_signal": read_no_signal,
        "signal_no_window_yet": signal_no_window,
        "earliest_first_check_at": min(firsts) if firsts else None,
    }
