"""Lium joins the git-history 7-day window (Brain #961): counted from lium.json captures, never invented."""
import importlib.util
from pathlib import Path

from core import availability_rate as A

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ar7", ROOT / "scripts/availability_rate_7d.py")
ar7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar7)


def _rec(in_stock, stamp, gpu="A100 SXM", av=True):
    r = {"vendor": "Lium", "gpu": gpu, "vram_gb": 80, "tier": "Marketplace secure node"}
    if av:
        r["availability"] = {"in_stock": in_stock, "checked_at": stamp}
    return r


def _rows(docs):
    rows, n = ar7.rows_from_docs(ar7.lium_docs_as_scout(docs))
    return {r["gpu"]: r for r in rows}, n


def test_each_capture_is_one_check_and_repeats_count_once():
    docs = [{"records": [_rec(False, "2026-11-21T02:00:00Z")]},
            {"records": [_rec(True, "2026-11-21T01:00:00Z")]},
            {"records": [_rec(True, "2026-11-21T01:00:00Z")]}]  # same capture seen in a later commit (row carried)
    by, n = _rows(docs)
    r = by["A100 SXM"]
    assert n == 2 and (r["checks"], r["in_stock_checks"], r["unknown_checks"]) == (2, 1, 0)
    assert r["rate"] == 0.5 and r["first_check_at"] == "2026-11-21T01:00:00Z" and r["last_check_at"] == "2026-11-21T02:00:00Z"


def test_unknown_stays_unknown_and_missing_availability_adds_no_check():
    docs = [{"records": [_rec(None, "2026-11-21T01:00:00Z"), _rec(None, None, gpu="H100 SXM", av=False)]}]
    by, _ = _rows(docs)
    assert (by["A100 SXM"]["checks"], by["A100 SXM"]["unknown_checks"], by["A100 SXM"]["rate"]) == (0, 1, None)
    assert by["A100 SXM"]["never_ran_checks"] is None  # no recorded reason: no guessed split
    assert "H100 SXM" not in by  # no availability object: no invented check


def test_lium_row_joins_the_git_history_window_with_its_own_vendor_key():
    docs = [{"records": [_rec(i % 2 == 0, f"2026-11-2{i}T00:00:00Z") for i in range(1, 8)][:1]}]
    docs = [{"records": [_rec(i % 2 == 0, f"2026-11-0{i}T00:00:00Z")]} for i in range(1, 8)]
    rows, n = ar7.rows_from_docs(ar7.lium_docs_as_scout(docs))
    saved = (A._CACHE, A._SCOUT, A._SCOUT_AT)
    try:
        A._CACHE = {"window_start": "s", "window_end": "2026-11-08T00:00:00Z", "window_days": 7,
                    "rows": {(r["vendor"], r["gpu"], r["vram_gb"], r["tier"]): r for r in rows}}
        A._SCOUT, A._SCOUT_AT = {}, None
        ar = A.fields("Lium", "A100 SXM", 80, "Marketplace secure node", 1.0)["availability_rate_7d"]
    finally:
        A._CACHE, A._SCOUT, A._SCOUT_AT = saved
    assert ar["source"] == "git_history" and ar["checks"] == 7 and ar["in_stock_checks"] == 3
