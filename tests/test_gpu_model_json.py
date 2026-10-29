import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "api" / "v1" / "gpu"


def test_index_and_views_exist():
    idx = json.loads((V / "index.json").read_text())
    assert idx["models"]
    for m in idx["models"]:
        assert (V / f"{m['slug']}.json").exists()


def test_reserved_never_cheapest_and_tier_split():
    for p in V.glob("*.json"):
        if p.name == "index.json":
            continue
        d = json.loads(p.read_text())
        assert "reserved" not in d["cheapest"]
        for b, rows in d["cheapest"].items():
            for r in rows:
                assert r["tier_class"] != "reserved" and r["bucket"] == b
                assert r["verified_at"] and r["source_url"].startswith("https://")
        assert d["last_checked"] == max(r["verified_at"] for r in d["rows"])
        assert not any(k in json.dumps(d).lower() for k in ("commission", "payout"))


def test_reserved_sorted_last_in_rows_and_price_comparison():
    d = json.loads((V / "h200.json").read_text())
    tcs = [r["tier_class"] == "reserved" for r in d["rows"]]
    assert tcs == sorted(tcs)
    html = (ROOT / "gpu" / "price-comparison" / "index.html").read_text()
    import re
    flags = [t == "reserved" for t in re.findall(r'<tr data-tier="([a-z-]+)"', html)]
    assert any(flags) and flags == sorted(flags)


def test_modal_rows_carry_preemption_quote():
    d = json.loads((ROOT / "data" / "gpu_pricing" / "modal.json").read_text())
    assert len(d["records"]) == 4
    for r in d["records"]:
        assert "subject to preemption by default" in r["evidence"]["interruption_quote"]
