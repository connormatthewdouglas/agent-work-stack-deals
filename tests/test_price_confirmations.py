"""Manual confirmations for refresh changes over MAX_AUTO_CHANGE_PCT. Fixtures, pinned clock, no network."""
import copy
import importlib.util
import sys
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location("rgp_confirm", "scripts/refresh_gpu_prices.py")
m = importlib.util.module_from_spec(spec)
sys.modules["rgp_confirm"] = m
spec.loader.exec_module(m)

NOW = datetime(2026, 11, 10, 18, 50, tzinfo=timezone.utc)
QUOTE = "L40S 48 GB $0.96 /hr"
PAGE_211 = "<html><body><p>L40S 48 GB $2.11 /hr</p></body></html>"
PAGE_120 = "<html><body><p>L40S 48 GB $1.20 /hr</p></body></html>"
REC = {
    "vendor": "ExampleCo",
    "gpu": "L40S",
    "vram_gb": 48,
    "price_usd": 0.96,
    "billing_unit": "hourly",
    "hourly_usd": 0.96,
    "interruptible": False,
    "tier": "On-demand",
    "form_factor": None,
    "quote": QUOTE,
    "source_url": "https://example.com/pricing",
    "checked_at": "2026-11-01T00:00:00+00:00",
    "verified_at": "2026-11-01T00:00:00+00:00",
    "evidence": {
        "source_url": "https://example.com/pricing",
        "quote": QUOTE,
        "checked_at": "2026-11-01T00:00:00+00:00",
    },
}
CONFIRM = {
    "vendor": "ExampleCo",
    "gpu": "L40S",
    "tier": "On-demand",
    "confirmed_price": 2.11,
    "currency": "USD",
    "source_url": "https://example.com/pricing",
    "confirmed_by": "Bjorn (manual check)",
    "confirmed_at": "2026-11-10T18:44:00Z",
    "reread_by": "Scout",
    "reread_at": "2026-11-10T18:47:00Z",
    "expires_at": "2026-11-17T18:44:00Z",
}


class Page:
    def __init__(self, html, at=NOW):
        self.html, self.fetched_at = html, {}
        self._at = at

    def get(self, url):
        self.fetched_at[url] = self._at
        return 200, self.html


def _doc(rec=None):
    return {"vendor": "ExampleCo", "records": [copy.deepcopy(rec or REC)]}


def _run(html, confirmations, now=NOW, rec=None):
    doc = _doc(rec)
    rep = m.refresh([doc], Page(html, now), now, confirmations=confirmations)
    return doc["records"][0], rep[0]


def test_exact_match_within_window_releases_the_change():
    r, rep = _run(PAGE_211, [CONFIRM])
    assert r["price_usd"] == 2.11 and r["hourly_usd"] == 2.11
    assert "$2.11" in r["quote"] and "$2.11" in r["evidence"]["quote"]
    assert r["verified_at"] == r["checked_at"] == r["evidence"]["checked_at"] == m._iso(NOW)
    assert r["price_confirmation"]["confirmed_by"] == "Bjorn (manual check)"
    assert r["price_confirmation"]["confirmed_at"] == "2026-11-10T18:44:00Z"
    assert r["price_confirmation"]["confirmed_price"] == 2.11
    assert rep["result"] == "changed" and rep["new"] == 2.11
    assert rep["confirmation"]["confirmed_by"] == "Bjorn (manual check)"


def test_price_mismatch_stays_held():
    conf = {**CONFIRM, "confirmed_price": 2.00}
    r, rep = _run(PAGE_211, [conf])
    assert r["price_usd"] == 0.96 and r["hourly_usd"] == 0.96
    assert r["quote"] == QUOTE and r["verified_at"] == REC["verified_at"]
    assert "price_confirmation" not in r
    assert "NOT applied: 0.96 -> 2.11" in rep["result"]
    assert "exceeds 50%" in rep["result"]
    assert "confirmation is 2.0" in rep["result"] or "confirmation is 2.00" in rep["result"]
    assert "live parsed $2.11" in rep["result"]


def test_expired_entry_stays_held():
    r, rep = _run(PAGE_211, [CONFIRM], now=datetime(2026, 11, 17, 18, 44, tzinfo=timezone.utc))
    assert r["price_usd"] == 0.96 and r["verified_at"] == REC["verified_at"]
    assert "price_confirmation" not in r
    assert "NOT applied: 0.96 -> 2.11" in rep["result"] and "exceeds 50%" in rep["result"]
    assert "confirmation expired at 2026-11-17T18:44:00Z" in rep["result"]


def test_missing_entry_stays_held():
    r, rep = _run(PAGE_211, [])
    assert r["price_usd"] == 0.96 and r["verified_at"] == REC["verified_at"]
    assert "price_confirmation" not in r
    assert rep["result"] == "NOT applied: 0.96 -> 2.11 (+119.8%) exceeds 50%; re-check by hand"


def test_change_under_50_percent_is_unaffected():
    # 0.96 -> 1.20 is +25%. Applies through the normal path with or without an entry.
    r_plain, rep_plain = _run(PAGE_120, [])
    r_conf, rep_conf = _run(PAGE_120, [CONFIRM])
    for r, rep in ((r_plain, rep_plain), (r_conf, rep_conf)):
        assert r["price_usd"] == 1.20 and r["hourly_usd"] == 1.20
        assert "$1.20" in r["evidence"]["quote"]
        assert r["verified_at"] == m._iso(NOW)
        assert "price_confirmation" not in r
        assert rep["result"] == "changed" and rep["new"] == 1.20
        assert "confirmation" not in rep
