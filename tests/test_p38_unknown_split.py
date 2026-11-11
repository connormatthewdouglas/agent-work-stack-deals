"""P38 (dingdang6284-bot2, #585): split unknown_checks into never_ran_checks + no_source_checks; total unchanged."""
import importlib.util
from pathlib import Path

from core import availability_rate as A

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ar7", ROOT / "scripts/availability_rate_7d.py")
ar7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar7)


def _row(in_stock, reason=None, t="2026-11-10T00:00:00Z", gpu="H100"):
    r = {"vendor": "V", "gpu": gpu, "vram_gb": 80, "tier": "On-demand", "in_stock": in_stock, "checked_at": t}
    if reason:
        r["availability_reason"] = reason
    return r


def test_builder_splits_by_reason_and_keeps_total():
    docs = [{"generation_id": "g3", "rows": [_row(None, "no_source"), _row(None, "no_source", gpu="A100")]},
            {"generation_id": "g2", "rows": [_row(None, "check_failed_timeout"), _row(None, gpu="A100")]},
            {"generation_id": "g2", "rows": [_row(None, "stale")]},  # repeated generation counts once
            {"generation_id": "g1", "rows": [_row(True, "in_stock"), _row(None, "check_failed_http")]}]
    rows, n = ar7.rows_from_docs(docs)
    by = {r["gpu"]: r for r in rows}
    assert n == 3
    h = by["H100"]
    assert (h["checks"], h["in_stock_checks"], h["unknown_checks"]) == (1, 1, 3)
    assert (h["never_ran_checks"], h["no_source_checks"]) == (2, 1)
    a = by["A100"]  # one unknown check has no recorded reason: no guessed split, total unchanged
    assert a["unknown_checks"] == 2 and a["never_ran_checks"] is None and a["no_source_checks"] is None


def test_describe_only_publishes_a_consistent_split():
    d = A._describe(10, 5, 4, "s", "e", "git_history", never_ran=1, no_source=3)
    assert (d["unknown_checks"], d["never_ran_checks"], d["no_source_checks"]) == (4, 1, 3)
    for nr, ns in ((None, None), (1, 2), (True, 3), (-1, 5), (None, 4)):
        d = A._describe(10, 5, 4, "s", "e", "git_history", never_ran=nr, no_source=ns)
        assert d["unknown_checks"] == 4 and d["never_ran_checks"] is None and d["no_source_checks"] is None
    d = A._describe(10, 5, None, "s", "e", "git_history", never_ran=0, no_source=0)  # old capture: no unknown count
    assert d["unknown_checks"] is None and d["never_ran_checks"] is None


def test_fields_read_both_sources(monkeypatch):
    k = ("V", "H100", 80, "On-demand")
    monkeypatch.setattr(A, "_SCOUT", {})
    monkeypatch.setattr(A, "_CACHE", {"window_start": "s", "window_end": "2026-11-10T00:00:00Z", "rows": {k: {
        "checks": 6, "in_stock_checks": 3, "unknown_checks": 5, "never_ran_checks": 2, "no_source_checks": 3}}})
    r = A.fields(*k, 2)["availability_rate_7d"]
    assert (r["unknown_checks"], r["never_ran_checks"], r["no_source_checks"]) == (5, 2, 3)
    sr = {"checks_7d": 10, "known_checks_7d": 7, "in_stock_checks_7d": 7, "last_check_at": "2026-11-10T00:00:00Z"}
    monkeypatch.setattr(A, "_SCOUT", {("v", "H100", 80, "On-demand"): (sr, "2026-11-10T00:00:00Z")})
    r = A.fields(*k, 2)["availability_rate_7d"]
    assert r["unknown_checks"] == 3 and r["never_ran_checks"] is None and r["no_source_checks"] is None  # Scout has no split yet
    monkeypatch.setattr(A, "_SCOUT", {("v", "H100", 80, "On-demand"): (
        {**sr, "never_ran_checks_7d": 1, "no_source_checks_7d": 2}, "2026-11-10T00:00:00Z")})
    r = A.fields(*k, 2)["availability_rate_7d"]
    assert (r["never_ran_checks"], r["no_source_checks"]) == (1, 2)
