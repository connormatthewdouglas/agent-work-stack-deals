import copy
import importlib.util
import json
import pathlib

spec = importlib.util.spec_from_file_location("ics", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "import_clore_snapshot.py")
ics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ics)

SNAP = {"source_url": "https://api.clore.ai/v1/marketplace", "checked_at": "2026-11-02T15:14:19Z", "listings": [], "summary": {
    "RTX 4090": {"available_with_usd_price": 9, "median": 0.5, "range_on_demand": [0.3, 1.0], "lowest_available_on_demand_usd_gpu_hr": 0.3},
    "A100": {"available_with_usd_price": 3, "lowest_available_on_demand_usd_gpu_hr": 0.3333},
    "L40S": {"available_with_usd_price": 0}}}


def test_median_published_and_below_five_held():
    doc = copy.deepcopy(json.loads(ics.PATH.read_text()))
    ics.apply(doc, SNAP)
    by = {r["gpu"]: r for r in doc["records"]}
    assert by["RTX 4090"]["price_usd"] == 0.5 and by["RTX 4090"]["lowest_offer_usd"] == 0.3 and "stale" not in by["RTX 4090"]
    assert by["RTX 4090"]["evidence"]["quote"] == by["RTX 4090"]["quote"] and by["RTX 4090"]["checked_at"] == "2026-11-02T15:14:19+00:00"
    a = by["A100 SXM"]
    assert a["price_usd"] is None and "N=3" in a["stale"]["reason"] and "price withheld" in a["quote"]
    assert by["L40S"]["price_usd"] is None and by["L40S"]["offer_count"] == 0 and "no available listing" in by["L40S"]["quote"]
    assert doc["checked_at"] == "2026-11-02T15:14:19+00:00"
