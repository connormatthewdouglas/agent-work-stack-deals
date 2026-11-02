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
