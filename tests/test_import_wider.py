import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_scout_wider import normalize  # noqa: E402

BASE = {"tier": "On-demand", "source_url": "https://example.test/api", "verified_at": "2026-10-31T13:08:29Z",
        "batch": "wider-gpu", "price_basis": "list"}


def row(**k):
    return {**BASE, **k}


def test_extra_keys_and_vram_rules():
    r = normalize(row(vendor="Verda", gpu_model="B300 SXM 268GB", vram_gb=268, price_usd_hr=11.35))
    assert r["gpu"] == "B300 SXM" and r["form_factor"] == "SXM" and r["vram_gb"] == 288 and "268" in r["vram_note"]
    assert normalize(row(vendor="Vast.ai", gpu_model="A40 45GB", vram_gb=45, price_usd_hr=0.5)) is None  # no median/min fields
    assert normalize(row(vendor="RunPod", gpu_model="B200 SXM 180GB", vram_gb=180, price_usd_hr=5.98))["vram_gb"] == 180
    assert normalize(row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.59))["vram_gb"] == 24


def test_skips():
    assert normalize(row(vendor="RunPod", gpu_model="T4 16GB", vram_gb=16, price_usd_hr=0.2)) is None
    assert normalize(row(vendor="Clore.ai", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.3)) is None
    assert normalize(row(vendor="TensorDock", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.3)) is None
    assert normalize(row(vendor="Vast.ai", gpu_model="L4 22GB", vram_gb=22, price_usd_hr=0.6, feed_status="held_below_min_offers")) is None
    assert normalize(row(vendor="Oblivus", gpu_model="B200 SXM 192GB", vram_gb=192, price_usd_hr=None)) is None


def test_refuses_wrong_schema(tmp_path):
    f = tmp_path / "w.json"
    f.write_text(json.dumps({"version": "3.1", "batch": "wider-gpu", "collected_at": datetime.now(timezone.utc).isoformat(), "rows": []}))
    p = subprocess.run([sys.executable, str(ROOT / "scripts/import_scout_wider.py"), str(f), "--dry-run"], capture_output=True, text=True)
    assert p.returncode != 0 and "refusing" in (p.stdout + p.stderr)
