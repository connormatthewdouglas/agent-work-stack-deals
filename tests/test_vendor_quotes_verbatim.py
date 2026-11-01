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


def _gb_mismatch(quote, vram, gpu):
    """GPU memory sizes stated in the quote: '<gpu> 45GB', 'vRAM: 24 GB' or '80GB HBM3/VRAM' (not system RAM or disk)."""
    import re
    q = quote or ""
    pats = [rf"{re.escape(gpu or '')}\s+(\d+)\s*GB\b", r"vRAM:?\s*(\d+)\s*GB\b", r"(\d+)\s*GB\s*(?:vRAM|VRAM|HBM\w*|GDDR\w*)"]
    gbs = {int(x) for pat in pats for x in re.findall(pat, q, re.I)}
    return vram is not None and bool(gbs) and vram not in gbs


def test_quote_gb_differing_from_vram_gb_carries_vram_note():
    """Gauge nov1_mart4 fix 1: vendor files, the published feed (rates + held_stale) and per-model JSON."""
    bad = []
    for f in (ROOT / "data/gpu_pricing").glob("*.json"):
        d = json.loads(f.read_text()); rows = d.get("records") if isinstance(d, dict) else None
        for r in rows or []:
            if _gb_mismatch(r.get("quote"), r.get("vram_gb"), r.get("gpu")) and not r.get("vram_note"):
                bad.append((f.name, r["gpu"], r.get("tier")))
    api = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    pub = list(api["rates"]) + [r for h in api["held_stale"] for r in h.get("records") or []]
    for m in (ROOT / "api/v1/gpu").glob("*.json"):
        md = json.loads(m.read_text())
        pub += [r for k in ("rates", "rows", "held_stale") for r in (md.get(k) or []) if isinstance(r, dict)]
    for r in pub:
        if _gb_mismatch(r.get("quote") or (r.get("evidence") or {}).get("quote"), r.get("vram_gb"), r.get("gpu")) and not r.get("vram_note"):
            bad.append(("published", r.get("advertiser") or r.get("vendor"), r.get("gpu"), r.get("tier")))
    assert not bad, bad


def test_clore_l40s_vram_note_published():
    api = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    rec = [r for h in api["held_stale"] if h["vendor"] == "Clore.ai" for r in h["records"] if r["gpu"] == "L40S"]
    assert rec and rec[0]["vram_gb"] == 48 and "reports 45" in rec[0]["vram_note"]
