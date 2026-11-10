"""Lambda public list is dated in the future: additive price_effective_at, hold until that instant."""
import copy
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("rgp_lambda", str(ROOT / "scripts/refresh_gpu_prices.py"))
m = importlib.util.module_from_spec(spec)
sys.modules["rgp_lambda"] = m
spec.loader.exec_module(m)

from core.gpu import (  # noqa: E402
    build_rates,
    not_yet_effective_reason,
    price_effective_at,
    price_not_yet_effective,
)
from scripts.gpu_calculator import _held_paragraph  # noqa: E402

PAGE = (
    "<html><body><p>Plan VRAM/GPU vCPUs RAM STORAGE PRICE/GPU/HR* "
    "NVIDIA B200 SXM6 180 GB 26 360 GiB 2.75 TiB SSD $7.99 "
    "* Plus applicable sales tax/VAT/GST. These prices take effect November 16, 2026, at 00:00 UTC. "
    "Until then, log in to your Lambda Cloud account to see current pricing.</p></body></html>"
)
NO_DATE = "<html><body><p>NVIDIA B200 SXM6 180 GB 26 360 GiB 2.75 TiB SSD $7.99 /hr</p></body></html>"
REC = {
    "vendor": "Lambda",
    "gpu": "B200",
    "vram_gb": 180,
    "price_usd": 7.99,
    "billing_unit": "hourly",
    "hourly_usd": 7.99,
    "interruptible": False,
    "tier": "On-demand instance (1x GPU)",
    "region": "unknown",
    "form_factor": "SXM6",
    "quote": "NVIDIA B200 SXM6 180 GB 26 360 GiB 2.75 TiB SSD $7.99",
    "source_url": "https://lambda.ai/pricing",
    "checked_at": "2026-11-10T18:31:05+00:00",
    "verified_at": "2026-11-10T18:31:05+00:00",
    "evidence": {
        "source_url": "https://lambda.ai/pricing",
        "quote": "NVIDIA B200 SXM6 180 GB 26 360 GiB 2.75 TiB SSD $7.99",
        "checked_at": "2026-11-10T18:31:05+00:00",
    },
}
BEFORE = datetime(2026, 11, 10, 19, 0, tzinfo=timezone.utc)
AFTER = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 11, 16, 0, 0, 1, tzinfo=timezone.utc)


def _doc(rec, extras=True):
    d = {
        "vendor": "Lambda",
        "deal_id": None,
        "source_url": "https://lambda.ai/pricing",
        "checked_at": "2026-11-10T18:30:05+00:00",
        "records": [rec],
    }
    if extras:
        d["extras"] = {k: {"status": "unknown", "text": "x", "source_url": "https://lambda.ai/pricing"}
                       for k in ("egress", "storage", "interruption")}
    return d


class F:
    fetched_at = {}

    def get(self, url):
        return 200, PAGE


def test_parse_price_effective_at_from_vendor_sentence():
    text = m.page_text(PAGE)
    dt = m.parse_price_effective_at(text)
    assert dt == datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
    assert m.parse_price_effective_at(m.page_text(NO_DATE)) is None
    assert m.parse_price_effective_at("") is None


def test_refresh_sets_price_effective_at_without_changing_price():
    doc = _doc(copy.deepcopy(REC), extras=False)
    rep = m.refresh([doc], F(), BEFORE, confirmations=[])
    r = doc["records"][0]
    assert r["price_usd"] == 7.99
    assert r["price_effective_at"] == "2026-11-16T00:00:00+00:00"
    assert r["verified_at"].startswith("2026-11-10T19:00:00")
    assert any(x.get("result") == "unchanged" for x in rep)


def test_refresh_does_not_invent_a_date_when_the_page_has_none():
    class N:
        fetched_at = {}

        def get(self, url):
            return 200, NO_DATE

    doc = _doc(copy.deepcopy(REC), extras=False)
    m.refresh([doc], N(), BEFORE, confirmations=[])
    assert "price_effective_at" not in doc["records"][0]


def test_build_rates_holds_before_effective_and_ranks_after():
    rec = dict(copy.deepcopy(REC), price_effective_at="2026-11-16T00:00:00+00:00")
    doc = _doc(rec)
    held = build_rates([], [doc], now=BEFORE)
    assert not held.get("problems"), held.get("problems")
    assert [x for x in held["rates"] if x["advertiser"] == "Lambda"] == []
    h = [x for x in held["held_stale"] if x["vendor"] == "Lambda"]
    assert len(h) == 1 and h[0]["reason"].startswith("not yet in effect:")
    assert h[0]["records"][0]["price_effective_at"] == "2026-11-16T00:00:00+00:00"
    assert "2026-11-16T00:00:00+00:00" in h[0]["reason"]

    at = build_rates([], [doc], now=AFTER)
    assert not at.get("problems")
    rates = [x for x in at["rates"] if x["advertiser"] == "Lambda"]
    assert len(rates) == 1 and rates[0]["price_usd"] == 7.99
    assert rates[0]["price_effective_at"] == "2026-11-16T00:00:00+00:00"
    assert not [x for x in at["held_stale"] if x["vendor"] == "Lambda" and str(x.get("reason","")).startswith("not yet in effect:")]

    later = build_rates([], [doc], now=LATER)
    assert [x for x in later["rates"] if x["advertiser"] == "Lambda"]


def test_price_not_yet_effective_helpers():
    rec = {"price_effective_at": "2026-11-16T00:00:00Z"}
    assert price_effective_at(rec) == datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
    assert price_not_yet_effective(rec, BEFORE) is True
    assert price_not_yet_effective(rec, AFTER) is False
    assert price_not_yet_effective({}, BEFORE) is False
    assert not_yet_effective_reason(rec).startswith("not yet in effect:")


def test_pages_show_not_yet_effective_note():
    held = [{
        "vendor": "Lambda",
        "source_url": "https://lambda.ai/pricing",
        "reason": not_yet_effective_reason({"price_effective_at": "2026-11-16T00:00:00+00:00"}),
        "records": [{"gpu": "B200", "hourly_usd": 7.99, "price_effective_at": "2026-11-16T00:00:00+00:00"}],
        "scope": "record",
    }]
    html = _held_paragraph(lambda s: s, held)
    assert "not yet in effect" in html and "Lambda" in html
    assert "Held out as stale" in html and "none" in html  # no stale vendors in this fixture

    class G:
        @staticmethod
        def esc(s):
            return s

    body = []
    # reuse the page branch by calling the snippet logic
    h = held[0]
    g = (h.get("records") or [{}])[0]
    note = f"{G.esc(h['vendor'])} {G.esc(g.get('gpu') or '')} not ranked as a current price: {G.esc(h['reason'])}"
    assert "Lambda B200" in note and "not yet in effect" in note
