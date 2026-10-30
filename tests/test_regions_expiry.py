"""Scout v2.9: region lists (available_regions + per-region detail) expire 1 h after each region's check, separately
from the 8 h stock claim. Every check here uses an injected clock, never the wall clock."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core.gpu_availability import region_guard, stale_guard, regions_expires_at, REGIONS_NOTE  # noqa: E402

T = datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc)
DET = [{"region": "AP-IN-1 (India)", "stock_level": "Low", "checked_at": "2026-10-30T13:54:36Z",
        "availability_expires_at": "2026-10-30T14:54:36Z", "confirmed": True, "confirmation": "two_reads"},
       {"region": "US-NE-1 (United States)", "stock_level": "Low", "checked_at": "2026-10-30T13:56:59Z",
        "availability_expires_at": "2026-10-30T14:56:59Z", "confirmed": True, "confirmation": "two_reads"}]


def _claim():
    return {"status": "available when checked", "in_stock": True, "checked_at": "2026-10-30T13:54:32Z", "origin": "scout",
            "availability_expires_at": "2026-10-30T21:54:32Z", "available_regions": ["AP-IN-1 (India)", "US-NE-1 (United States)"],
            "available_regions_detail": DET, "available_regions_label": "seen in stock at check time",
            "regions_expires_at": regions_expires_at({"available_regions_detail": DET})}


def test_regions_expires_at_is_earliest_region():
    assert regions_expires_at({"available_regions_detail": DET}) == "2026-10-30T14:54:36Z"
    assert regions_expires_at({}) is None


def test_region_guard_before_and_after():
    a = _claim()
    assert region_guard(a, T) is a and stale_guard(a, T) is a
    b = stale_guard(a, datetime(2026, 10, 30, 14, 55, tzinfo=timezone.utc))
    assert b["available_regions"] is None and b["available_regions_detail"] is None and b["regions_expired"] is True
    assert b["in_stock"] is True and b["availability_expires_at"] == a["availability_expires_at"]  # row claim: own 8 h expiry
    assert REGIONS_NOTE in b["regions_note"]
    c = stale_guard(a, datetime(2026, 10, 30, 22, 0, tzinfo=timezone.utc))  # past 8 h: whole claim unknown, no regions
    assert c["in_stock"] is None and not c.get("available_regions")


def test_mcp_blanks_regions_at_request_time():
    from core import deals as D
    data = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    for x in data["rates"]:
        if x["gpu"].startswith("H100"):
            x["availability"] = _claim()
    def regs(now):
        out = D.compare_gpu_prices(data, "H100", limit=25, now=now)
        return [x["availability"].get("available_regions") for x in out["results"]
                if isinstance(x.get("availability"), dict) and x["availability"].get("regions_expires_at")]
    assert any(regs(T))
    assert regs(T + timedelta(hours=1)) and not any(regs(T + timedelta(hours=1)))


def test_page_cell_carries_region_expiry_and_script():
    import gpu_pages as gp
    import stale_js
    class G:
        esc = staticmethod(lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))
    h = gp._avail_cell(G, {"advertiser": "RunPod", "availability": _claim()})
    assert 'data-rg-expires="2026-10-30T14:54:36Z"' in h and "(regions valid until 10:54 ET)" in h
    assert "data-rg-expires" in stale_js.JS
    gone = gp._avail_cell(G, {"advertiser": "RunPod", "availability": stale_guard(_claim(), T + timedelta(hours=1))})
    assert "data-rg-expires" not in gone and "AP-IN-1" not in gone and "region list expired at 10:54" in gone


def test_built_outputs_list_no_region_past_its_expiry_at_build_time():
    # every served region list carries its expiry for the in-page script and the T41-25 live check
    data = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    for r in data["rates"]:
        a = r.get("availability") if isinstance(r.get("availability"), dict) else {}
        if a.get("available_regions_detail"):
            assert a.get("regions_expires_at") or a.get("regions_expired")
    for p in list((ROOT / "gpu").glob("**/*.html")):
        t = p.read_text(encoding="utf-8")
        if "data-rg-expires" in t:
            assert "<!-- av-stale -->" in t
