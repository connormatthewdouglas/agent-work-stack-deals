"""T30: outbound click counts are aggregate per vendor/day, from virtual /e/out/ paths only; tracker sends no PII."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import click_report as C  # noqa: E402
import site_ui  # noqa: E402


def test_aggregate_per_vendor_per_day():
    by_deal = {"hyperstack-001": "Hyperstack"}
    groups = [{"count": 3, "dimensions": {"date": "2026-10-29", "requestPath": "/e/out/hyperstack-001/"}},
              {"count": 2, "dimensions": {"date": "2026-10-29", "requestPath": "/e/out/h-hyperstack-cloud/"}},
              {"count": 1, "dimensions": {"date": "2026-10-28", "requestPath": "/e/out/hyperstack-001/"}},
              {"count": 9, "dimensions": {"date": "2026-10-29", "requestPath": "/gpu/"}},
              {"count": 4, "dimensions": {"date": "2026-10-29", "requestPath": "/e/out/x/?ip=1.2.3.4"}}]
    rep = C.aggregate(groups, by_deal)
    assert rep["by_day"]["2026-10-29"] == {"Hyperstack": 3, "hyperstack-cloud": 2}
    assert rep["totals"] == {"Hyperstack": 4, "hyperstack-cloud": 2}


def test_tracker_sends_path_only():
    js = site_ui.TRACK_JS
    assert "/e/" in js and "hostname" in js
    for bad in ("document.cookie", "localStorage", "sessionStorage", "navigator.userAgent", "fetch(", "sendBeacon", "u.search", "u.pathname"):
        assert bad not in js, bad


def test_report_refuses_repo_output(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "fetch_groups", lambda days: [])
    try:
        C.main(["--out", str(ROOT / "x.json")])
        assert False
    except SystemExit as e:
        assert "inside the repo" in str(e)
    out = tmp_path / "c.json"
    assert C.main(["--out", str(out)]) == 0 and oct(out.stat().st_mode)[-3:] == "600"
