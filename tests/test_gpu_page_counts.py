"""Gauge Nov 1: the H100 pages must list every H100 rate in the feed (all forms, NVL included)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _feed():
    return json.loads((ROOT / "api/v1/gpu-prices.json").read_text())["rates"]


def test_h100_pages_offer_count_matches_feed():
    n = sum(r["gpu"].startswith("H100") for r in _feed())
    cheap = (ROOT / "gpu/cheapest-h100-rental/index.html").read_text()
    m = re.search(r"(\d+) offers from \d+ vendors", cheap)
    assert m and int(m.group(1)) == n, (m and m.group(0), n)
    assert "NVL</strong>: RunPod" in cheap
    spec = (ROOT / "gpu/h100-rental-price/index.html").read_text()
    assert spec.count('data-label="$/GPU-hr"') == n
    assert "H100 NVL" in spec


def test_storage_egress_count_is_62():
    # 60 vendor-published rows + the 2 RunPod H100 NVL rows (RunPod's cited storage text); intended
    assert sum("storage" in r or "egress" in r for r in _feed()) == 62
