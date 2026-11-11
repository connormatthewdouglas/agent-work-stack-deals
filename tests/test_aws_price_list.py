"""AWS Price List collector: fixture-only, no network."""
from __future__ import annotations

import copy
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


from core import aws_price_list as apl
from core.gpu import MAX_QUOTE

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (ROOT / "tests/fixtures/aws-price-list-us-east-1-sample.csv").read_text(encoding="utf-8")
SPEC = importlib.util.spec_from_file_location("rgp_aws", "scripts/refresh_gpu_prices.py")
RGP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RGP)

URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-east-1/index.csv"
STAMP = "2026-11-04T16:11:55+00:00"
NOW = datetime(2026, 11, 11, 21, 45, tzinfo=timezone.utc)

REC = {
    "vendor": "Amazon Web Services",
    "gpu": "A10G",
    "vram_gb": 24,
    "price_usd": 1.006,
    "billing_unit": "hourly",
    "hourly_usd": 1.006,
    "interruptible": False,
    "tier": "On-demand EC2 instance g5.xlarge (1x A10G, 4 vCPU, 16 GiB, 250 GB NVMe; whole-instance price), US East (N. Virginia)",
    "form_factor": None,
    "quote": 'old quote',
    "source_url": URL,
    "checked_at": STAMP,
    "evidence": {"source_url": URL, "quote": "old quote", "checked_at": STAMP},
    "verified_at": STAMP,
    "region": "us-east-1",
    "instance_type": "g5.xlarge",
}


def _doc(rec=None, **extra):
    r = copy.deepcopy(rec or REC)
    d = {
        "vendor": "Amazon Web Services",
        "deal_id": None,
        "source_url": URL,
        "checked_at": STAMP,
        "billing_granularity": "hourly",
        "collector": "aws_price_list",
        "extras": {k: {"status": "unknown", "text": "Not verified in this pass.", "source_url": URL, "checked_at": STAMP}
                   for k in ("egress", "storage", "interruption")},
        "records": [r],
    }
    d.update(extra)
    return d


class FakeFetch:
    def __init__(self, status, body, at=None):
        self.status, self.body = status, body
        self.fetched_at = {}
        self._at = at or NOW

    def get(self, url):
        self.fetched_at[url] = self._at
        return self.status, self.body


def test_is_offer_url_csv_only():
    assert apl.is_offer_url(URL)
    assert not apl.is_offer_url(URL.replace(".csv", ".json"))
    assert not apl.is_offer_url("https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/index.json")


def test_filter_keeps_only_ondemand_linux_shared_used_hrs():
    body = apl.filter_csv_lines(FIXTURE.splitlines())
    meta, rows = apl.parse_preamble_and_table(body)
    assert meta["Version"] == "20261110173852"
    assert meta["Publication Date"] == "2026-11-10T17:38:52Z"
    types = sorted({r["Instance Type"] for r in rows})
    assert types == ["g5.2xlarge", "g5.xlarge"]
    assert all(apl.row_matches_filter(r) for r in rows)


def test_parse_record_matches_g5_xlarge():
    price, quote, msg, meta = apl.parse_record(REC, FIXTURE)
    assert msg == "parsed" and price == "1.0060000000"
    assert meta == {
        "offer_version": "20261110173852",
        "publication_date": "2026-11-10T17:38:52Z",
        "rate_code": "79BRGEEZC6TARVWJ.JRTCKXETXF.6YS6EN2CT7",
    }
    assert "RateCode 79BRGEEZC6TARVWJ.JRTCKXETXF.6YS6EN2CT7" in quote
    assert "v20261110173852" in quote
    assert "pub 2026-11-10T17:38:52Z" in quote
    assert '"PricePerUnit": "1.0060000000"' in quote
    assert len(quote) <= MAX_QUOTE
    # Must not pick Dedicated $1.1066, Windows, Reserved, or g5.2xlarge.
    assert "1.1066" not in quote and "2.012" not in quote


def test_parse_record_unknown_instance_fails():
    rec = dict(REC, instance_type="p5.48xlarge", tier="On-demand EC2 instance p5.48xlarge")
    price, quote, msg, meta = apl.parse_record(rec, FIXTURE)
    assert price is None and quote is None and meta is None and "p5.48xlarge" in msg


def test_parse_record_empty_or_garbage_fails():
    for body in ("", "not a csv", "SKU,Foo\n1,2\n"):
        price, _, msg, meta = apl.parse_record(REC, body)
        assert price is None and meta is None and msg


def test_refresh_success_same_price_restamps_and_records_ratecode():
    doc = _doc()
    rep = RGP.refresh([doc], FakeFetch(200, FIXTURE), NOW)
    r = doc["records"][0]
    assert r["price_usd"] == 1.006 and r["hourly_usd"] == 1.006
    assert r["verified_at"] == "2026-11-11T21:45:00+00:00"
    assert r["checked_at"] == r["verified_at"]
    ev = r["evidence"]
    assert ev["checked_at"] == r["verified_at"]
    assert ev["source_url"] == URL
    # Version, publication date and RateCode live in the allowed quote field, not extra keys.
    assert ev["quote"] == r["quote"]
    assert "v20261110173852" in ev["quote"]
    assert "pub 2026-11-10T17:38:52Z" in ev["quote"]
    assert "RateCode 79BRGEEZC6TARVWJ.JRTCKXETXF.6YS6EN2CT7" in ev["quote"]
    assert set(ev) <= {"source_url", "quote", "checked_at"}
    assert doc["checked_at"] == "2026-11-11T21:45:00+00:00"
    assert rep[0]["result"] == "unchanged"


def test_refresh_fetch_failure_leaves_timestamps_untouched():
    doc = _doc()
    RGP.refresh([doc], FakeFetch(None, "TimeoutError"), NOW)
    r = doc["records"][0]
    assert r["price_usd"] == 1.006
    assert r["verified_at"] == STAMP
    assert r["checked_at"] == STAMP
    assert r["evidence"]["checked_at"] == STAMP
    assert r["last_failed_check_at"] == "2026-11-11T21:45:00+00:00"
    assert doc["checked_at"] == STAMP
    assert "offer_version" not in r["evidence"]


def test_refresh_parse_failure_leaves_timestamps_untouched():
    doc = _doc()
    # 200 with a CSV that has no matching g5.xlarge Used/Shared/Linux/OnDemand row
    rec = dict(copy.deepcopy(REC), instance_type="p5.48xlarge",
               tier="On-demand EC2 instance p5.48xlarge (1x H100)")
    doc["records"] = [rec]
    RGP.refresh([doc], FakeFetch(200, FIXTURE), NOW)
    r = doc["records"][0]
    assert r["price_usd"] == 1.006
    assert r["verified_at"] == STAMP and r["checked_at"] == STAMP
    assert r["evidence"]["checked_at"] == STAMP
    assert r["last_failed_check_at"] == "2026-11-11T21:45:00+00:00"
    assert doc["checked_at"] == STAMP


def test_refresh_price_jump_gate_not_applied():
    # Fixture price is $1.006; a $0.40 listed price jumps > 50% and must not apply or restamp.
    rec = dict(copy.deepcopy(REC), price_usd=0.40, hourly_usd=0.40)
    rec["evidence"] = dict(rec["evidence"])
    doc = _doc(rec)
    rep = RGP.refresh([doc], FakeFetch(200, FIXTURE), NOW, confirmations=[])
    r = doc["records"][0]
    assert r["price_usd"] == 0.40
    assert r["verified_at"] == STAMP and r["checked_at"] == STAMP
    assert "NOT applied" in rep[0]["result"] and "50%" in rep[0]["result"]
    assert doc["checked_at"] == STAMP


def test_manual_snapshot_flag_does_not_skip_price_list_docs():
    doc = _doc(manual_snapshot={"reason": "legacy flag; collector now auto-refreshes"})
    RGP.refresh([doc], FakeFetch(200, FIXTURE), NOW)
    assert doc["records"][0]["verified_at"] == "2026-11-11T21:45:00+00:00"


def test_live_aws_json_is_wired_for_the_collector():
    doc = json.loads((ROOT / "data/gpu_pricing/aws.json").read_text(encoding="utf-8"))
    assert apl.is_doc(doc) and doc.get("collector") == apl.COLLECTOR
    assert not doc.get("manual_snapshot")
    assert apl.is_offer_url(doc["records"][0]["source_url"])
    assert apl.instance_type_of(doc["records"][0]) == "g5.xlarge"

def test_refresh_output_passes_same_validator_as_the_feed():
    """The daily gpu-refresh workflow writes vendor files then generate_seo_pages/pytest
    call core.gpu.record_problems (via build_rates / test_records_schema_and_compat_fields).
    #191 missed this: extra evidence keys passed unit tests but failed the refresh gate."""
    from core.gpu import EVIDENCE_FIELDS, EVIDENCE_OPTIONAL, EVIDENCE_REQUEST_FIELDS, record_problems
    doc = _doc()
    RGP.refresh([doc], FakeFetch(200, FIXTURE), NOW)
    probs = record_problems(doc)
    assert probs == [], probs
    ev = doc["records"][0]["evidence"]
    allowed = set(EVIDENCE_FIELDS) | set(EVIDENCE_OPTIONAL) | set(EVIDENCE_REQUEST_FIELDS)
    assert set(ev) <= allowed
    # Offer identity is still present, in the quote.
    assert "v20261110173852" in ev["quote"]
    assert "pub 2026-11-10T17:38:52Z" in ev["quote"]
    assert "RateCode 79BRGEEZC6TARVWJ.JRTCKXETXF.6YS6EN2CT7" in ev["quote"]

