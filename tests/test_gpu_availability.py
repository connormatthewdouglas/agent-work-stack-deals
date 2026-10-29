import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_unknown_is_never_out_of_stock_and_has_note():
    rates = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())["rates"]
    for r in rates:
        a = r["availability"]
        if a["in_stock"] is None:
            assert a["status"] == "unknown" and a["checked_at"] is None and a["note"]
            assert "time shown" not in a["note"]
        else:
            assert "not a guarantee" in a["note"] and "manual snapshot" in a["refresh"]
            assert a["checked_at"] and a["checked_at"] != r["verified_at"]  # separate timestamp from the price
        if r["advertiser"] == "Vast.ai" and a["in_stock"] is not None:
            assert "later" not in a["consistency_note"] and "same snapshot" not in a["consistency_note"]
    rp = [r for r in rates if r["advertiser"] == "RunPod" and "Community" in r["tier"]]
    assert rp and all(r["availability"]["status"] == "unknown" or r["availability"]["in_stock"] is not None for r in rp)
    assert any("no stock status" in r["availability"]["note"] for r in rp) and all("out of stock" not in r["availability"]["note"] for r in rp)


def test_pages_never_say_out_of_stock():
    for p in [ROOT / "gpu" / "price-comparison" / "index.html", *ROOT.glob("gpu/cheapest-*/index.html")]:
        t = p.read_text().lower()
        assert "out of stock" not in t.replace("out of stock when checked", "") and "stock changes within minutes" in t


def test_no_stale_cadence_wording():
    t = (ROOT / "gpu" / "price-comparison" / "index.html").read_text()
    assert "~4 h" not in t and "same snapshot" not in t and "manual snapshot" in t


def test_marketplace_basis_matches_fields():
    import re
    for r in json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())["rates"]:
        if r.get("price_status") != "marketplace":  # listed-price aggregators (Spheron) have no median/offer_count
            continue
        m = re.search(r"(\d+) (?:verified|available) .*median \$([\d.]+)/hr, min \$([\d.]+)/hr", r["basis"])
        assert m, r["basis"]
        assert int(m.group(1)) == r["offer_count"], r["advertiser"]
        assert abs(float(m.group(2)) - r["price_usd"]) < 1e-4 and abs(float(m.group(3)) - r["lowest_offer_usd"]) < 1e-4
        assert r["basis"] == r["evidence"]["quote"]


def test_verda_auth_label_and_false_is_out_of_stock():
    for r in json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())["rates"]:
        a = r["availability"]
        if r["advertiser"].startswith("Verda") and a["in_stock"] is not None:
            assert a["source_label"] == "authenticated vendor API (not publicly reproducible)"
        if a["in_stock"] is False:
            assert a["status"] == "out of stock when checked"
        if a.get("offer_count") == 0:
            assert a["in_stock"] is False
