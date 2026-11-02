import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import refresh_stack_quotes as r  # noqa: E402

NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)


def doc(tmp_path, vendor="9Proxy", quote="Starting from $0.68/GB"):
    d = {"vendor": vendor, "source_url": "https://x.test/p", "checked_at": "2026-10-27T02:54:00-04:00",
         "offers": [{"plan": "p", "quote": quote, "overage_usd": 0.68}]}
    p = tmp_path / "v.json"
    p.write_text(json.dumps(d))
    return p, d


def test_match_price_and_unit():
    assert r.match("Starting from $0.68/GB", "Enterprise Package 10000 GB $0.68 /GB $3.00/GB")[0]
    assert not r.match("Starting from $0.68/GB", "Enterprise $0.69 /GB")[0]
    assert not r.match("Starting from $0.68/GB", "$0.68 /IP")[0]


def test_verified_bumps_checked_at_only(tmp_path):
    p, d = doc(tmp_path)
    ok, flags = r.refresh([(p, d)], fetch=lambda u: (200, "<p>nothing</p>"),
                          render=lambda u: "10000 GB $0.68 /GB", now=NOW)
    out = json.loads(p.read_text())
    assert not flags and out["checked_at"] == "2026-11-02T18:00:00+00:00"
    assert out["offers"][0]["quote"] == "Starting from $0.68/GB"


def test_changed_price_flags_and_keeps_file(tmp_path):
    p, d = doc(tmp_path)
    before = p.read_text()
    ok, flags = r.refresh([(p, d)], fetch=lambda u: (200, "<p>$0.75 /GB</p>"), render=lambda u: "$0.75 /GB", now=NOW)
    assert flags and not ok and p.read_text() == before


def test_free_quote_needs_free_shown():
    assert r.match("Basic: 12000 emails, Free", "Basic Free plan")[0]
    assert not r.match("Basic: 12000 emails, Free", "Basic plan")[0]
