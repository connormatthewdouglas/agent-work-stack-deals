import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_unknown_is_never_out_of_stock_and_has_note():
    rates = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())["rates"]
    for r in rates:
        a = r["availability"]
        assert "not a guarantee" in a["note"]
        if a["in_stock"] is None:
            assert a["status"] == "unknown"
        else:
            assert a["checked_at"] and a["checked_at"] != r["verified_at"]  # separate timestamp from the price
        if r["advertiser"] == "Vast.ai" and a["in_stock"] is not None:
            assert "consistency-checked" in a["consistency_note"]
    rp = [r for r in rates if r["advertiser"] == "RunPod" and "Community" in r["tier"]]
    assert rp and all(r["availability"]["status"] == "unknown" for r in rp)


def test_pages_never_say_out_of_stock():
    for p in [ROOT / "gpu" / "price-comparison" / "index.html", *ROOT.glob("gpu/cheapest-*/index.html")]:
        t = p.read_text().lower()
        assert "out of stock" not in t and "stock changes within minutes" in t
