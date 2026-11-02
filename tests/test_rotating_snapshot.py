"""Gauge spheron84: rotating-snapshot rows (Spheron /pricing/ rotates RAM/vCPU/NVMe per read) match GPU name + VRAM
+ '$X /hr' only, keep the full quote as display evidence, and change price only when two reads >= 60 s apart agree."""
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import refresh_gpu_prices as rg  # noqa: E402

QUOTE = "L40S Ada 48 GB 72 GB RAM 12 vCPUs 625 GB NVMe $0.96 /hr"
SRC = "https://www.spheron.network/pricing/"


def rec(**k):
    r = {"gpu": "L40S", "vram_gb": 48, "price_usd": 0.96, "hourly_usd": 0.96, "billing_unit": "hourly",
         "tier": "Marketplace", "quote": QUOTE, "source_url": SRC, "checked_at": "2026-11-02T15:29:20+00:00",
         "verified_at": "2026-11-02T15:29:20+00:00",
         "evidence": {"source_url": SRC, "quote": QUOTE, "checked_at": "2026-11-02T15:29:20+00:00"}}
    r.update(k)
    return r


def test_spheron_pricing_rows_are_rotating_without_a_data_edit():
    assert rg.is_rotating(rec(), "Spheron")
    assert not rg.is_rotating(rec(source_url="https://www.spheron.network/gpu-rental/rtx-5090/"), "Spheron")
    assert rg.is_rotating(rec(price_check="rotating snapshot", source_url="https://x.example/"), "Other")


def test_two_rotated_spec_strings_give_the_same_price():
    a = "L40S Ada 48 GB 72 GB RAM 12 vCPUs 625 GB NVMe $0.96 /hr || RTX 5090 Blackwell 32 GB 117 GB RAM $1.62 /hr"
    b = "L40S Ada 48 GB 294 GB RAM 16 vCPUs 128 GB NVMe $0.96 /hr || RTX 5090 Blackwell 32 GB 60 GB RAM $1.62 /hr"
    ra, rb = rg.parse_listed({**rec(), "vendor": "Spheron"}, a), rg.parse_listed({**rec(), "vendor": "Spheron"}, b)
    assert ra[0] == rb[0] == "0.96"
    assert rg.parse_listed({**rec(), "vendor": "Other", "source_url": "https://x.example/"}, b)[0] is None  # full-quote match breaks
    five = rec(gpu="RTX 5090", vram_gb=32, price_usd=1.62, hourly_usd=1.62)
    assert rg.parse_rotating(five, a)[0] == rg.parse_rotating(five, b)[0] == "1.62"
    assert rg.parse_rotating(rec(vram_gb=24), a)[0] is None  # VRAM must match


class FakeFetcher:
    def __init__(self, first, second):
        self.first, self.second, self.gaps = first, second, []

    def get(self, url):
        return 200, self.first

    def reread(self, url, gap):
        self.gaps.append(gap)
        return (200, self.second) if self.second is not None else (None, "")


def _run(first, second):
    doc = {"vendor": "Spheron", "checked_at": "x", "records": [rec()]}
    f = FakeFetcher(first, second)
    rep = rg.refresh([doc], f, datetime(2026, 11, 2, 17, tzinfo=timezone.utc))
    return doc["records"][0], rep[0], f


def test_unchanged_price_keeps_display_quote_and_needs_no_second_read():
    r, row, f = _run("<p>L40S Ada 48 GB 294 GB RAM 16 vCPUs 128 GB NVMe $0.96 /hr</p>", None)
    assert row["result"] == "unchanged" and r["price_usd"] == 0.96 and r["quote"] == QUOTE and f.gaps == []


def test_price_changes_only_when_two_reads_60s_apart_agree():
    flip = "<p>L40S Ada 48 GB 294 GB RAM 16 vCPUs 128 GB NVMe $1.80 /hr</p>"
    r, row, f = _run(flip, "<p>L40S Ada 48 GB 72 GB RAM 12 vCPUs 625 GB NVMe $0.96 /hr</p>")
    assert r["price_usd"] == 0.96 and row["result"].startswith("NOT applied") and f.gaps == [60]
    move = "<p>L40S Ada 48 GB 294 GB RAM 16 vCPUs 128 GB NVMe $1.01 /hr</p>"
    r, row, _ = _run(move, move.replace("294", "96"))
    assert r["price_usd"] == 1.01 and row["result"] == "changed"
