"""Gauge nov1_mart3: importers keep the vendor's own quote text; corrected VRAM goes in vram_gb + vram_note only."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _rows(name):
    d = json.loads((ROOT / "data/gpu_pricing" / name).read_text())
    return d["records"] if isinstance(d, dict) else d


def test_clore_l40s_quote_keeps_api_45gb():
    r = next(x for x in _rows("clore.json") if x["gpu"] == "L40S")
    assert r["vram_gb"] == 48
    assert "L40S 45GB" in r["quote"] and "L40S 45GB" in r["evidence"]["quote"]
    assert "reports 45" in r["vram_note"]


def test_e2e_h100_ranked_from_usd_pricing_table():
    r = next(x for x in _rows("e2e-networks.json") if x["gpu"] == "H100")
    assert "stale" not in r and r["price_usd"] == 3.99
    assert r["source_url"] == "https://www.e2enetworks.com/pricing"
    assert r["quote"].endswith("NVIDIA H100 80 26 250 $3.99")
