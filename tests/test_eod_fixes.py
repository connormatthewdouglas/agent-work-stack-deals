"""Gauge EOD accuracy fixes F1-F4 (shipped in 0.3.46)."""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import gpu_availability as ga
from core.deals import stock_phrase
from core.gpu_changes import change_title
from core.money import usd, usd_pair

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _ver(v):
    return tuple(int(x) for x in v.split("."))


def test_f1_install_never_pairs_date_with_later_version():
    import install_page as ip
    dates = dict(re.findall(r"^## (\d+\.\d+\.\d+) \((\d{4}-\d{2}-\d{2})\)", (ROOT / "CHANGELOG.md").read_text(), re.M))
    assert dates[ip.TESTED_ON_VERSION] <= ip.TESTED_ON  # the tested version existed on the tested date
    assert _ver(ip.TESTED_ON_VERSION) <= _ver(ip.TESTED_VERSION)
    page = (ROOT / "install" / "index.html").read_text()
    assert f"Tested {ip.TESTED_ON}: a clean <code>uvx lantern-works-deals-mcp</code> (v{ip.TESTED_ON_VERSION}; current v{ip.TESTED_VERSION})" in page


def test_f2_scout_rows_are_automated_checks():
    feed = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
    for r in feed["rates"]:
        a = r.get("availability") or {}
        if a.get("origin") == "scout" and a.get("refresh"):
            want = "manual snapshot" if r["advertiser"].lower().startswith("clore") else "automated check"
            assert a["refresh"].startswith(want), (r["advertiser"], a["refresh"])
    for p in ("gpu/price-comparison", "gpu/cheapest-rtx-4090-rental", "gpu/h100-rental-price", "gpu/rtx-4090-rental-price"):
        t = (ROOT / p / "index.html").read_text()
        assert "Availability (manual snapshot, time shown)" not in t, p


def test_f3_formatter_keeps_digits():
    assert usd(3.125) == "$3.125" and usd(3.1) == "$3.10" and usd(2) == "$2.00" and usd(1234.5) == "$1,234.50"
    assert usd_pair(0.7965, 0.8045) == ("$0.7965", "$0.8045")
    assert usd_pair(0.80, 0.80) == ("$0.80", "$0.80")
    t = change_title({"change": "up", "gpu": "X", "vendor": "V", "pct": 1.0, "old_hourly_usd": 0.7965, "new_hourly_usd": 0.8045})
    assert "$0.7965/GPU-hr → $0.8045/GPU-hr" in t


def test_f4_stale_text_from_expiry_and_real_lifetime():
    c = datetime(2026, 10, 30, 20, 52, tzinfo=timezone.utc)
    x = c + timedelta(minutes=15)
    iso = lambda d: d.isoformat().replace("+00:00", "Z")
    assert ga.claim_hours(iso(c), iso(x)) == 0.25
    a = {"origin": "scout", "in_stock": True, "checked_at": iso(c), "availability_expires_at": iso(x)}
    out = ga.stale_guard(a, now=c + timedelta(minutes=20))
    assert out["availability_stale"] and out["max_age_hours"] == 0.25
    s = stock_phrase(out)
    assert "last stock check 20:52Z expired at 21:07Z" in s and "valid 15 min" in s and "over 8 h" not in s
