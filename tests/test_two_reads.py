"""Gauge T73 F1-F6 #2: first and second read times stored; reads < 60 s apart (or no second read) are not counted."""
import importlib.util
import sys

from core import gpu_availability as ga
from core.gpu import availability_measured

spec = importlib.util.spec_from_file_location("isa", "scripts/import_scout_availability.py")
m = importlib.util.module_from_spec(spec); sys.modules["isa"] = m; spec.loader.exec_module(m)


def _row(**kw):
    return {"vendor": "Lambda", "gpu": "A100 SXM", "tier": "t", "in_stock": True, "availability_checked_at": "2026-11-02T12:19:13Z",
            "available_regions_detail": [{"region": "us-east-1", "checked_at": "2026-11-02T12:19:13Z"}], **kw}


def test_importer_carries_overall_and_region_reads():
    row = _row()
    ov = {"checked_at": "2026-11-02T12:19:13Z", "second_read_at": "2026-11-02T12:20:27Z"}
    reg = {"us-east-1": {"region": "us-east-1", "in_stock": True, "checked_at": "2026-11-02T12:19:13Z",
                         "second_read_at": "2026-11-02T12:20:27Z", "second_read_stock_level": "Low"}}
    m._carry_reads(row, ov, reg)
    assert (row["first_read_at"], row["second_read_at"], row["second_read_gap_s"], row["second_read_basis"]) == (
        "2026-11-02T12:19:13Z", "2026-11-02T12:20:27Z", 74.0, "overall")
    d = row["available_regions_detail"][0]
    assert d["second_read_gap_s"] == 74.0 and d["second_read_stock_level"] == "Low"


def test_derived_claim_takes_region_reads_and_missing_second_read_fails():
    row = _row()
    reg = {"us-east-1": {"region": "us-east-1", "in_stock": True, "checked_at": "2026-11-02T12:19:13Z", "second_read_at": "2026-11-02T12:19:50Z"}}
    m._carry_reads(row, {"checked_at": "2026-11-02T12:19:13Z"}, reg)
    assert row["second_read_gap_s"] == 37.0 and row["second_read_basis"] == "region us-east-1"
    row2 = _row()
    m._carry_reads(row2, None, {})
    assert row2["second_read_at"] is None and row2["second_read_gap_s"] is None


def test_claim_under_60s_not_counted():
    base = _row(first_read_at="2026-11-02T12:19:13Z", second_read_at="2026-11-02T12:19:50Z", second_read_gap_s=37.0)
    a = ga._scout("Lambda", base)
    assert a["two_read_gap_ok"] is False and not availability_measured({"availability": a})
    ok = ga._scout("Lambda", dict(base, second_read_at="2026-11-02T12:20:27Z", second_read_gap_s=74.0))
    assert ok["two_read_gap_ok"] is True and availability_measured({"availability": ok})
    legacy = ga._scout("Lambda", _row())  # rows imported before the read times existed: no new field
    assert "two_read_gap_ok" not in legacy
