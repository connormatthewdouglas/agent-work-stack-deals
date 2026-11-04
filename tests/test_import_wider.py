"""T63: the wider importer preserves the full economic offer, separates verbatim and normalized evidence, holds rows
with missing allocation/evidence, and re-imports idempotently without touching curated rows."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from core import gpu as g  # noqa: E402
from import_scout_wider import apply, normalize, normalize_ex  # noqa: E402

BASE = {"tier": "On-demand", "source_url": "https://example.test/pricing", "source_detail": "https://example.test/api",
        "verified_at": "2026-10-31T13:08:29+00:00", "batch": "wider-gpu", "price_basis": "api.price_per_hour (list price, 1 GPU)"}


def row(**k):
    return {**BASE, **k}


def _doc(vendor, records):
    return {"vendor": vendor, "deal_id": None, "source_url": "https://example.test/pricing",
            "checked_at": "2026-10-31T13:08:29+00:00", "records": records}


FILES = {"RunPod": "runpod.json", "Lambda": "lambda.json", "Vast.ai": "vast.json", "Verda": "verda.json"}


def _valid(vendor, rec):
    doc = json.loads((ROOT / "data/gpu_pricing" / FILES[vendor]).read_text())
    doc["records"] = [{**rec, "vendor": doc["vendor"]}]
    probs = g.record_problems(doc)
    assert not probs, probs


def test_b300_keeps_vendor_memory():
    r = normalize(row(vendor="Verda", gpu_model="B300 SXM 268GB", vram_gb=268, price_usd_hr=11.35))
    assert r["gpu"] == "B300 SXM" and r["vram_gb"] == 268 and "vram_note" not in r
    _valid("Verda", r)


def test_eight_gpu_only_offer_bills_sixteen_for_nine():
    r = normalize(row(vendor="Lambda", gpu_model="H100 SXM 80GB", vram_gb=80, price_usd_hr=2.99, gpu_count=8,
                      min_gpus=8, server_price_usd_hr=23.92, price_basis="instance price_cents_per_hour (8x H100 server)"))
    assert r["gpu_count"] == 8 and r["min_gpus"] == 8 and r["price_usd"] == 23.92
    assert r["hourly_usd"] == 2.99 and r["server_hourly_usd"] == 23.92
    _valid("Lambda", r)
    est = g.estimate([{**r, "advertiser": "Lambda", "unit": "hour", "price_usd": r["hourly_usd"]}], 10, gpus=9)[0]
    assert est["billed_gpus"] == 16 and est["instances"] == 2


def test_per_second_service():
    r = normalize(row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=None, price_usd_sec=0.000119,
                      billing_unit="per-second", price_basis="serverless flex price per second (1 GPU)"))
    assert r["billing_unit"] == "per-second" and r["price_usd"] == 0.000119 and r["hourly_usd"] == round(0.000119 * 3600, 4)
    _valid("RunPod", r)


def test_marketplace_median_keeps_sample_and_method():
    r = normalize(row(vendor="Vast.ai", gpu_model="A40", vram_gb=48, price_usd_hr=0.5344, offer_count=7, distinct_machines=6,
                      lowest_offer_usd=0.41, gpu_count=1, price_basis="median per-GPU dph_total", tier="Marketplace on-demand"))
    assert r["price_status"] == "marketplace" and r["offer_count"] == 7 and r["lowest_offer_usd"] == 0.41
    assert r["market_sample"]["distinct_machines"] == 6 and r["evidence_kind"] == "api_field"
    assert "7 offers" in r["evidence"]["quote"] and "0.5344" in r["evidence"]["quote"]
    _valid("Vast.ai", r)
    # without a lowest offer it stays a plain listed median (offer_count never at top level)
    r2 = normalize(row(vendor="Vast.ai", gpu_model="A40", vram_gb=48, price_usd_hr=0.5344, offer_count=7, gpu_count=1))
    assert r2["price_status"] == "listed" and "offer_count" not in r2 and r2["market_sample"]["offer_count"] == 7


def test_reserved_rate_is_classed_reserved():
    r = normalize(row(vendor="Lambda", gpu_model="B200 SXM 180GB", vram_gb=180, price_usd_hr=3.79, tier="Reserved 1-year",
                      term="1 year"))
    assert r["tier_class"] == "reserved" and r["term"] == "1 year"
    _valid("Lambda", r)


def test_thin_market_held():
    rec, why = normalize_ex(row(vendor="Vast.ai", gpu_model="A40", vram_gb=48, price_usd_hr=0.5, offer_count=4, gpu_count=1))
    assert rec is None and "thin market" in why
    rec, why = normalize_ex(row(vendor="Vast.ai", gpu_model="L4", vram_gb=22, price_usd_hr=0.6, feed_status="held_below_min_offers"))
    assert rec is None and "thin market" in why


def test_unsupported_input():
    for r in (row(vendor="Nowhere", gpu_model="H100", price_usd_hr=1.0),
              row(vendor="RunPod", gpu_model="H100", price_usd_hr="cheap"),
              row(vendor="RunPod", gpu_model="H100", price_usd_hr=1.0, billing_unit="per-day"),
              row(vendor="RunPod", gpu_model="H100", price_usd_hr=1.0, gpu_count=0),
              row(vendor="RunPod", gpu_model="Quantum Widget", price_usd_hr=1.0)):
        rec, why = normalize_ex(r)
        assert rec is None and why, r


def test_missing_allocation_or_evidence_held():
    rec, why = normalize_ex(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.0, price_basis="list"))
    assert rec is None and "allocation missing" in why
    rec, why = normalize_ex(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.0, gpu_count=1, price_basis=None))
    assert rec is None and "evidence missing" in why
    rec, why = normalize_ex(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.0, gpu_count=1, source_url="http://x"))
    assert rec is None and "evidence missing" in why


def test_verbatim_and_summary_separate():
    v = normalize(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.39, quote_verbatim="H100 SXM $2.39/hr"))
    assert v["evidence_kind"] == "verbatim" and v["evidence"]["quote"] == "H100 SXM $2.39/hr"
    assert "importer summary" in v["normalized_summary"] and v["normalized_summary"] != v["evidence"]["quote"]
    a = normalize(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.39))
    assert a["evidence_kind"] == "api_field" and a["evidence"]["quote"].startswith("api.price_per_hour (list price, 1 GPU): 2.39")
    assert "importer summary" not in a["evidence"]["quote"] and a["evidence_method"]


def test_skips():
    assert normalize(row(vendor="RunPod", gpu_model="T4 16GB", vram_gb=16, price_usd_hr=0.2)) is None
    assert normalize_ex(row(vendor="Clore.ai", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.3)) == (None, None)
    assert normalize_ex(row(vendor="TensorDock", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.3)) == (None, None)
    assert normalize_ex(row(vendor="Oblivus", gpu_model="B200 SXM 192GB", vram_gb=192, price_usd_hr=None)) == (None, None)


def test_idempotent_and_removes_stale_rows_only():
    curated = {"vendor": "RunPod", "gpu": "H100", "tier": "On-demand", "vram_gb": 80, "quote": "curated"}
    stale = {"vendor": "Verda", "gpu": "V100", "tier": "x", "vram_gb": 16, "batch": "wider-gpu"}
    docs = {"RunPod": _doc("RunPod", [curated]), "Verda": _doc("Verda", [stale, {"gpu": "A100", "quote": "curated"}])}
    rows = [row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=1.0),  # collides with curated: curated wins
            row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.59),
            row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.59)]  # duplicate in batch
    out1, unres, n1 = apply(docs, rows)
    assert n1 == 1 and out1["RunPod"]["records"][0] == curated
    assert [x["gpu"] for x in out1["Verda"]["records"]] == ["A100"]  # stale batch row removed, vendor absent from batch
    out2, _, n2 = apply(out1, rows)
    assert out2 == out1 and n2 == n1
    assert docs["Verda"]["records"][0] is stale  # inputs not mutated


def test_refuses_wrong_schema(tmp_path):
    f = tmp_path / "w.json"
    f.write_text(json.dumps({"version": "3.1", "batch": "wider-gpu", "collected_at": datetime.now(timezone.utc).isoformat(), "rows": []}))
    p = subprocess.run([sys.executable, str(ROOT / "scripts/import_scout_wider.py"), str(f), "--dry-run"], capture_output=True, text=True)
    assert p.returncode != 0 and "refusing" in (p.stdout + p.stderr)
