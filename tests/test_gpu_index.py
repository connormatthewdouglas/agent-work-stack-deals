import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gpu_index  # noqa: E402


def _run(tmp):
    out = tmp / "out"
    out.mkdir(exist_ok=True)
    shutil.copy(ROOT / "api/v1/gpu-price-index.json", out / "gpu-price-index.json")
    gpu_index.main_args(str(ROOT), str(out))
    return (out / "gpu-price-index.json").read_text(), (out / "gpu-price-index.csv").read_text()


def test_deterministic_and_matches_committed(tmp_path):
    a = _run(tmp_path)
    b = _run(tmp_path)
    assert a == b
    assert json.loads(a[0]) == json.loads((ROOT / "api/v1/gpu-price-index.json").read_text())
    assert a[1] == (ROOT / "api/v1/gpu-price-index.csv").read_text()


def test_excluded_rows_never_counted():
    idx = json.loads((ROOT / "api/v1/gpu-price-index.json").read_text())
    for d in idx["history"]:
        snap = json.loads((ROOT / "data/gpu_pricing/snapshots" / f"{d['date']}.json").read_text())
        by_key = {r["key"]: r for r in snap["rows"]}
        for k in d["rows_included"]:
            r = by_key[k]
            assert r["status"] == "ranked"
            assert gpu_index.classify(r["tier"]) not in ("spot/interruptible", "reserved/committed")
        reasons = {x["excluded_because"] for x in d["rows_excluded"]}
        for x in d["rows_excluded"]:
            assert x["key"] not in d["rows_included"]
        for s, v in d["series"].items():
            assert v["vendors"] == len(v["vendor_prices"])
            if v["median_usd_per_gpu_hour"] is not None:
                assert v["monthly_basis_usd"] == round(v["median_usd_per_gpu_hour"] * 730, 2)
        assert all(r for r in reasons)


def test_marketplace_rule():
    assert gpu_index.classify("Marketplace (median of offers)") == "marketplace"
    assert gpu_index.classify("Spot") == "spot/interruptible"
    assert gpu_index.classify("Reserved 12 mo") == "reserved/committed"


def test_page_has_license_and_badge():
    t = (ROOT / "gpu/index/index.html").read_text()
    assert "CC BY 4.0" in t and "History:" in t and "gpu-price-index.csv" in t
    assert "/gpu/index/methodology/" in (ROOT / "sitemap.xml").read_text()
