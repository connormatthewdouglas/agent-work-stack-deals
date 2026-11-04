"""T62 Lium collector acceptance tests (Pax spec A1-A10) on synthetic nodes payloads."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("collect_lium", ROOT / "scripts" / "collect_lium.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)
NOW = datetime(2026, 11, 3, 0, 30, tzinfo=timezone.utc)


def node(model, price, tier="secure", avail=1, mn=1, mem=80, now=True, **kw):
    return {"gpu_model": model, "price_per_gpu_hour": price, "tier": tier, "available_gpu_count": avail,
            "available_now": now, "min_rentable_gpu_count": mn, "gpu_memory_gb": mem, "city": "X", "country": "Y",
            "rent_url": "https://lium.io/browse-pods/x", "last_verified_at": "2026-11-03T00:13:19Z", **kw}


def baseline():
    ns = [node("H100 80GB HBM3", 2.2, "spot", 8, 8) for _ in range(4)]
    ns += [node("H100 80GB HBM3", 2.5, "secure", 8, 8), node("H100 80GB HBM3", 3.75, "secure", 28, 1),
           node("H200 NVL", 3.75, "secure", 1, 1, 140), node("B300 SXM6 PC", 10.0, "secure", 1, 1, 269),
           node("H100 80GB HBM3", 0.5, "secure", 0, 1), node("H100 80GB HBM3", 0.6, "secure", 8, 1, now=False)]
    return {"generated_at": "2026-11-03T00:23:34Z", "nodes": ns}


def rows(doc):
    return {(r["gpu"], r["interruptible"]): r for r in doc["records"]}


def test_a2_a5_a8_derivation_tiers_whole_node():
    doc, _ = L.build(baseline(), None, NOW)
    r = rows(doc)
    spot, sec = r[("H100 SXM", True)], r[("H100 SXM", False)]
    assert (spot["hourly_usd"], spot["min_gpus"]) == (2.2, 8) and "32 GPUs free" in spot["availability"]["stock_level"]
    assert sec["hourly_usd"] == 2.5 and sec["min_gpus"] == 8 and "36 GPUs free" in sec["availability"]["stock_level"]
    assert r[("H200 NVL", False)]["hourly_usd"] == 3.75 and "1 GPUs free" in r[("H200 NVL", False)]["availability"]["stock_level"]


def test_a1_no_pricing_json_source():
    src = (ROOT / "scripts" / "collect_lium.py").read_text()
    assert "pricing.json\"" not in src and "reference_price_usd_per_gpu_hour" not in src
    doc, _ = L.build(baseline(), None, NOW)
    assert all(r["source_url"] == L.NODES_URL for r in doc["records"])


def test_a3_nvl_never_merged():
    doc, _ = L.build(baseline(), None, NOW)
    r = rows(doc)
    assert r[("H200 NVL", False)]["vram_gb"] == 141 and r[("H200 NVL", False)]["form_factor"] == "NVL"
    assert r[("H100 SXM", False)]["form_factor"] == "SXM" and "NVL" not in r[("H100 SXM", False)]["gpu"]
    assert L.ALIASES["H100 NVL"][1] == 94


def test_a4_a6_zero_fleet_and_unmatched_quarantine():
    doc, log = L.build(baseline(), None, NOW)
    assert "H100 NVL" not in {r["gpu"] for r in doc["records"]}
    assert not any(r["lium_model"] == "B300 SXM6 PC" for r in doc["records"])
    assert any("QUARANTINED" in x and "B300 SXM6 PC" in x for x in log)


def test_a7_staleness_refusal():
    with pytest.raises(SystemExit):
        L.build(baseline(), None, NOW + timedelta(hours=2))


def test_a9_flicker_withdraws_price():
    doc, _ = L.build(baseline(), None, NOW)
    p = baseline()
    p["nodes"] = [n for n in p["nodes"] if n["gpu_model"] != "H200 NVL"]
    doc2, _ = L.build(p, json.loads(json.dumps(doc)), NOW)
    nvl = rows(doc2)[("H200 NVL", False)]
    assert nvl["price_usd"] is None and nvl["stale"] and nvl["availability"]["in_stock"] is False


def test_a10_vram_divergence_logged():
    _, log = L.build(baseline(), None, NOW)
    assert not any("H200 NVL" in x and "divergence" in x for x in log)  # 140 vs 141 within tolerance
    p = baseline(); p["nodes"].append(node("L40S", 0.4, mem=45))
    _, log = L.build(p, None, NOW)
    assert any("divergence" in x and "L40S" in x for x in log)
