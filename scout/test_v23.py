"""Offline test: a country-less Vast offer must not crash and must count in 'all' only."""
import collect_v2 as c
def fake_get(url, data=None):
    return {"offers": [
        {"num_gpus": 1, "gpu_ram": 81920, "dph_total": 2.0, "geolocation": "Paris, FR"},
        {"num_gpus": 1, "gpu_ram": 81920, "dph_total": 3.0, "geolocation": None},
        {"num_gpus": 2, "gpu_ram": 81920, "dph_total": 5.0, "geolocation": ""}]}
c.get = fake_get; c.time.sleep = lambda s: None
rows = [r for r in c.vast() if r["gpu_model"] == "H100 SXM"]
allr = [r for r in rows if r["region"] == "all"][0]
assert allr["offer_count"] == 3, allr
assert [r["region"] for r in rows if r["region"] != "all"] == ["FR"], rows
assert all(r["region"] is not None for r in rows)
# enrich-style listing must not crash with None present
regs = sorted(x for x in ["FR", None, "US"] if x is not None)
assert regs == ["FR", "US"]
print("test_v23 OK")
