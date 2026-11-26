"""E2E pricing table added an INR figure before the same USD prices."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_gpu_prices as R  # noqa: E402

URL = "https://www.e2enetworks.com/pricing"
# Verbatim visible fragments from https://www.e2enetworks.com/pricing
# (GET 2026-11-26T13:31:49Z, robots Allow: /). USD amounts are unchanged.
NEW = {
    ("H100", 80, 3.99): "NVIDIA H100 80 26 250 ₹379.05 $3.99",
    ("A100", 80, 2.10): "NVIDIA A100 80 16 115 ₹189.00 $2.10",
    ("A100", 40, 1.98): "NVIDIA A100 40 16 115 ₹179.00 $1.98",
    ("T4", 16, 0.45): "NVIDIA T4 16 12 50 ₹30.00 $0.45",
}
OLD = {
    ("H100", 80, 3.99): "GPU vRAM vCPUs RAM, GB Hourly/On-Demand ... NVIDIA H100 80 26 250 $3.99",
    ("A100", 80, 2.10): "NVIDIA A100 80 16 115 $2.10",
    ("A100", 40, 1.98): "NVIDIA A100 40 16 115 $1.98",
    ("T4", 16, 0.45): "GPU vRAM vCPUs RAM, GB Hourly/On-Demand ... NVIDIA T4 16 12 50 $0.45",
}
# Surrounding table rows so the fixture looks like the live card, not a lone sentence.
PAGE = (
    "NVIDIA H200 141 30 375 ₹502.55 $5.29 Contact Sales "
    + NEW[("H100", 80, 3.99)]
    + " Contact Sales NVIDIA RTX PRO 6000 96 32 170 ₹236.55 $2.49 Contact Sales "
    + NEW[("A100", 80, 2.10)]
    + " Contact Sales "
    + NEW[("A100", 40, 1.98)]
    + " Contact Sales NVIDIA A40 48 16 100 ₹96.00 $1.44 Contact Sales "
    + "NVIDIA L4 24 25 110 ₹49.00 $0.57 Contact Sales "
    + NEW[("T4", 16, 0.45)]
    + " Contact Sales On-demand prices are per GPU-hour and do not include taxes."
)


def _rec(gpu: str, vram: int, price: float) -> dict:
    old = OLD[(gpu, vram, price)]
    return {
        "vendor": "E2E Networks",
        "gpu": gpu,
        "vram_gb": vram,
        "tier": "On-demand",
        "price_usd": price,
        "hourly_usd": price,
        "source_url": URL,
        "evidence": {"quote": old, "source_url": URL},
    }


def test_old_quote_is_gone_without_the_inr_sentence():
    rec = _rec("H100", 80, 3.99)
    price, quote, msg = R.parse_listed(rec, "NVIDIA H200 141 30 375 ₹502.55 $5.29 Contact Sales")
    assert price is None and "not found" in msg


def test_pricing_alternate_quote_parses_same_usd_prices():
    for (gpu, vram, price), new in NEW.items():
        got, quote, msg = R.parse_listed(_rec(gpu, vram, price), PAGE)
        assert got is not None and abs(float(got) - price) < 1e-9 and msg == "parsed", (gpu, vram, got, msg)
        assert new in quote


def test_refresh_adopts_inr_prefix_when_usd_price_is_unchanged():
    recs = []
    stamp = "2026-11-23T22:06:22+00:00"
    for (gpu, vram, price), old in OLD.items():
        rec = _rec(gpu, vram, price)
        rec.update({
            "billing_unit": "hourly",
            "interruptible": False,
            "quote": old,
            "checked_at": stamp,
            "verified_at": stamp,
        })
        rec["evidence"]["checked_at"] = stamp
        recs.append(rec)
    doc = {
        "vendor": "E2E Networks",
        "deal_id": None,
        "source_url": URL,
        "checked_at": "2026-11-23T22:05:42+00:00",
        "records": recs,
    }

    class F:
        fetched_at = {URL: datetime(2026, 11, 26, 13, 31, 49, tzinfo=timezone.utc)}

        def get(self, url):
            assert url == URL
            return 200, PAGE

    report = R.refresh([doc], F(), datetime(2026, 11, 26, 13, 31, 49, tzinfo=timezone.utc))
    assert all(r["result"] == "unchanged" for r in report), report
    for rec, ((gpu, vram, price), new) in zip(doc["records"], NEW.items()):
        assert rec["gpu"] == gpu and rec["price_usd"] == price
        assert rec["verified_at"].startswith("2026-11-26T13:31:49")
        # Elided evidence quotes are kept when the USD amount is unchanged;
        # the non-elided A100 lines adopt the INR-prefixed visible sentence.
        if "..." in OLD[(gpu, vram, price)]:
            assert rec["evidence"]["quote"] == OLD[(gpu, vram, price)]
        else:
            assert new in rec["evidence"]["quote"]
