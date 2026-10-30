import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_unknown_is_never_out_of_stock_and_has_note():
    rates = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())["rates"]
    for r in rates:
        a = r["availability"]
        if a["in_stock"] is None:
            # unknown: no time, unless a record-level check (with its source) found no stock signal
            assert a["note"] and "Stock changes within minutes" not in a["note"]
            if a.get("availability_stale"):  # 0.3.30: a Scout check older than 8 h renders unknown, with its last check time
                assert a["status"].startswith("unknown (stale availability, last checked ") and a["checked_at"]
                continue
            if a.get("basis") == "vendor_static_label":
                assert a["status"].startswith("vendor-labelled in stock (static page label") and a["checked_at"]
                continue
            assert a["status"] == "unknown" and (a["checked_at"] is None or a.get("source"))
            assert "time shown" not in a["note"]
        else:
            assert "not a guarantee" in a["note"] and a["refresh"].startswith(("automated check", "manual snapshot"))
            assert a["checked_at"] and (a["checked_at"] != r["verified_at"] or a.get("same_capture_as_price"))  # separate timestamp, unless price and stock count come from one capture (J6)
        if r["advertiser"] == "Vast.ai" and a["in_stock"] is not None:
            assert "later" not in a["consistency_note"] and "same snapshot" not in a["consistency_note"]
    rp = [r for r in rates if r["advertiser"] == "RunPod" and "Community" in r["tier"]]
    assert rp and all(r["availability"]["status"].startswith("unknown") or r["availability"]["in_stock"] is not None for r in rp)
    assert any("no stock status" in r["availability"]["note"] or r["availability"].get("availability_stale") for r in rp) and all("out of stock" not in r["availability"]["note"].replace("every region is confirmed out of stock", "") for r in rp)  # the region-derived rule text names the false condition; it is not a claim


def test_pages_never_say_out_of_stock():
    for p in [ROOT / "gpu" / "price-comparison" / "index.html", *ROOT.glob("gpu/cheapest-*/index.html")]:
        t = p.read_text().lower()
        t2 = t.replace("out of stock when checked", "").replace("not marked out of stock", "")
        assert "out of stock" not in t2 and "statuses from a vendor&#x27;s live stock check can change within minutes" in t.replace("'", "&#x27;")


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


def test_record_level_availability_and_region():
    rates = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())["rates"]
    new = {r["advertiser"]: r for r in rates if r["advertiser"] in ("Nova Cloud", "RunC.AI")}
    assert set(new) == {"Nova Cloud", "RunC.AI"}
    for r in new.values():
        assert r["region"] and r["source_url"].startswith("https://") and r["availability"]["checked_at"]
        assert r["availability"]["source"]
    na = new["Nova Cloud"]["availability"]
    assert na["in_stock"] is None and na["basis"] == "vendor_static_label" and "not a capacity check" in na["status"]
    assert new["RunC.AI"]["availability"]["status"] == "unknown"


def test_new_held_rtx4090_vendors_not_ranked():
    feed = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
    held = {h["vendor"] for h in feed["held_stale"]}
    assert {"SimplePod", "Runcrate", "Beam"} <= held
    assert not held & {r["advertiser"] for r in feed["rates"]} - {"Clore.ai"}
    assert not {"TensorDock", "Clore.ai"} & {r["advertiser"] for r in feed["rates"] if r["tier_class"] == "on-demand"}
