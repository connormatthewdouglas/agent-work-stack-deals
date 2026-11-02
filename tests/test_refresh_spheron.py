"""Gauge T73 F1-F6 #6: Spheron RTX 5090 'minimum runtime' wording parses; held rows keep checked_at."""
import copy
import importlib.util
import sys
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location("rgp_sph", "scripts/refresh_gpu_prices.py")
m = importlib.util.module_from_spec(spec); sys.modules["rgp_sph"] = m; spec.loader.exec_module(m)

PAGE = ("<html><body><p>On Spheron the NVIDIA RTX 5090 is $1.62/hr per GPU, billed per minute after a 20-minute "
        "minimum runtime, with no contract. Compared against published rates elsewhere, all per GPU: CloudRift "
        "lists $0.65/hr.</p><p>The minimum runtime is 20 minutes.</p></body></html>")
REC = {"vendor": "Spheron", "gpu": "RTX 5090", "vram_gb": 32, "price_usd": 1.56, "billing_unit": "hourly", "hourly_usd": 1.56,
       "interruptible": False, "tier": "on-demand", "quote": "On Spheron the NVIDIA RTX 5090 is $1.56/hr per GPU, billed per minute",
       "source_url": "https://www.spheron.network/gpu-rental/rtx-5090/", "checked_at": "2026-11-02T11:56:35+00:00",
       "verified_at": "2026-11-01T22:28:23+00:00",
       "evidence": {"source_url": "https://www.spheron.network/gpu-rental/rtx-5090/",
                    "quote": "On Spheron the NVIDIA RTX 5090 is $1.56/hr per GPU, billed per minute",
                    "checked_at": "2026-11-01T22:28:23+00:00"}}


class F:
    fetched_at = {}

    def get(self, url):
        return 200, PAGE


def test_minimum_runtime_wording_parses():
    v, q, msg = m.parse_listed(REC, m.page_text(PAGE))
    assert (v, msg) == ("1.62", "parsed") and "$1.62/hr per GPU, billed per minute" in q


def test_refresh_sources_new_price_when_not_held():
    doc = {"vendor": "Spheron", "records": [copy.deepcopy(REC)]}
    now = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
    m.refresh([doc], F(), now)
    r = doc["records"][0]
    assert r["price_usd"] == 1.62 and "$1.62/hr" in r["evidence"]["quote"] and r["verified_at"].startswith("2026-11-02T13")


def test_manual_hold_keeps_checked_at():
    rec = dict(copy.deepcopy(REC), stale={"reason": "held", "since": "2026-11-02"})
    doc = {"vendor": "Spheron", "records": [rec]}
    m.refresh([doc], F(), datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc))
    r = doc["records"][0]
    assert r["checked_at"] == "2026-11-02T11:56:35+00:00" and r["price_usd"] == 1.56 and r["stale"]


# Gauge T73 fix7 #1: both page states
NOCAP = ("<html><body><p>Rent RTX 5090 GPU from $0.89/hr</p><p>On Spheron the NVIDIA RTX 5090 has no capacity right now. "
         "$0.89/hr per GPU is the last rate it was listed at.</p></body></html>")


class N(F):
    def get(self, url):
        return 200, NOCAP


def _doc(rec):
    return {"vendor": "Spheron", "deal_id": None, "source_url": "https://www.spheron.network/pricing/", "checked_at": "2026-11-02T12:00:00+00:00",
            "extras": {k: {"status": "unknown", "text": "x", "source_url": "u"} for k in ("egress", "storage", "interruption")},
            "records": [rec]}


def test_no_capacity_marks_out_of_stock_keeps_price_and_quote():
    rec = dict(copy.deepcopy(REC), form_factor=None, price_usd=1.62, hourly_usd=1.62, quote="On Spheron the NVIDIA RTX 5090 is $1.62/hr per GPU, billed per minute")
    rec["evidence"] = dict(rec["evidence"], quote=rec["quote"])
    doc = _doc(rec)
    m.refresh([doc], N(), datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc))
    r = doc["records"][0]
    assert r["price_usd"] == 1.62 and "$1.62/hr" in r["quote"] and r["verified_at"] == REC["verified_at"]
    assert r["no_capacity"]["reason"] == "no capacity per vendor page" and r["no_capacity"]["read_at"].startswith("2026-11-02T13")
    assert r["no_capacity"]["page_text"].startswith("On Spheron the NVIDIA RTX 5090 has no capacity right now")
    sys.path.insert(0, '.')
    from core.gpu import build_rates
    out = build_rates([], [doc])
    assert not out.get("problems"), out.get("problems")
    assert not [x for x in out["rates"] if x["advertiser"] == "Spheron"]
    h = [x for x in out["held_stale"] if x["vendor"] == "Spheron"][0]
    assert h["availability"]["in_stock"] is False and h["availability"]["reason"] == "no capacity per vendor page"
    assert h["records"][0]["hourly_usd"] == 1.62 and "last sourced $1.62/hr" in h["reason"]
    # capacity back: the rate line parses again, no_capacity is cleared and the row ranks
    m.refresh([doc], F(), datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc))
    assert "no_capacity" not in doc["records"][0] and doc["records"][0]["verified_at"].startswith("2026-11-02T14")


def test_capacity_page_is_not_no_capacity():
    assert m.no_capacity_sentence("Spheron", "RTX 5090", m.page_text(PAGE)) is None
    assert m.no_capacity_sentence("Spheron", "L40S", m.page_text(NOCAP)) is None


def test_price_block_wording_is_no_capacity():
    t = "Spheron Your price $0.89/hr Last known - No capacity now"
    assert m.no_capacity_sentence("Spheron", "RTX 5090", t) == t


def test_failed_reverification_keeps_checked_at():
    class Bad(F):
        def get(self, url):
            return 200, "<p>nothing priced here</p>"
    rec = copy.deepcopy(REC)
    doc = {"vendor": "Spheron", "records": [rec]}
    m.refresh([doc], Bad(), datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc))
    r = doc["records"][0]
    assert r["checked_at"] == REC["checked_at"] and r["last_failed_check_at"].startswith("2026-11-02T13")
    doc = {"vendor": "Spheron", "records": [copy.deepcopy(REC)]}
    m.refresh([doc], N(), datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc))
    assert doc["records"][0]["checked_at"] == REC["checked_at"] and doc["records"][0]["no_capacity"]
