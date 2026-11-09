"""Offline tests v2.6: runs v2.5 (+v2.4, v2.3), then RunPod per-DC cloud-typed regions."""
import json, runpy
runpy.run_path("test_v25.py")
import collect_v2 as c, enrich_feed_v2 as e
c.time.sleep = lambda s: None
H = "NVIDIA H100 80GB HBM3"
def fake(url, data=None):
    q = json.loads(data)["query"]
    if "dataCenters" in q:
        return {"data": {"dataCenters": [
            {"id": "US-GA-2", "location": "United States", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": "Low"}]},
            {"id": "EU-RO-1", "location": "Europe", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": None}]},
            {"id": "US-KS-2", "location": "United States", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": None}]}]}}
    sec = "secureCloud:true" in q
    if '"US-GA-2"' in q:  # secure Low only
        return {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": "Low" if sec else None, "uninterruptablePrice": 3.99 if sec else None}}]}}
    if '"EU-RO-1"' in q:  # community High only
        return {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": None if sec else "High", "uninterruptablePrice": None if sec else 2.5}}]}}
    if '"US-KS-2"' in q:
        return {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": None, "uninterruptablePrice": None}}]}}
    return {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": "Low" if sec else None, "uninterruptablePrice": 2.99 if sec else None}}]}}
c.get = fake
rows, obs = c.runpod()
reg = {(r["tier"], r["region"]): r for r in rows if r["region"] != "all"}
assert reg[("On-demand (Secure Cloud)", "US-GA-2 (United States)")]["in_stock"] is True
assert reg[("On-demand (Secure Cloud)", "US-GA-2 (United States)")]["price_usd_hr"] == 3.99
assert reg[("On-demand (Community Cloud)", "EU-RO-1 (Europe)")]["in_stock"] is True
assert ("On-demand (Community Cloud)", "US-GA-2 (United States)") not in reg  # null signal -> no row, nothing invented
ks = reg[("Data center (cloud type not stated by API)", "US-KS-2 (United States)")]  # untyped fallback, unknown
assert ks["in_stock"] is None and ks["availability_note"].startswith("unknown")
assert ("Data center (cloud type not stated by API)", "US-GA-2 (United States)") not in reg  # typed row supersedes
# enrich: RunPod regions now joined by cloud tier
feed = [{"vendor": "RunPod", "records": [
  {"gpu": "H100 SXM", "vram_gb": 80, "tier": "On-demand (Secure Cloud)", "hourly_usd": 2.99, "source_url": "x"},
  {"gpu": "H100 SXM", "vram_gb": 80, "tier": "On-demand (Community Cloud)", "hourly_usd": 2.69, "source_url": "x"}]}]
out, st = e.enrich(feed, {"rows": rows, "errors": {}}, None)
o = {r["tier"]: r for r in out}
assert o["On-demand (Secure Cloud)"]["available_regions"] == ["US-GA-2 (United States)"], o
assert o["On-demand (Secure Cloud)"]["in_stock"] is True and o["On-demand (Secure Cloud)"]["region"] == "all"
assert o["On-demand (Community Cloud)"]["available_regions"] is None  # v2.7 rule: overall in_stock null -> no region list (was ["EU-RO-1 (Europe)"] in v2.6)
assert o["On-demand (Community Cloud)"]["in_stock"] is None  # aggregate 'all' stays unknown; region list is separate
print("test_v26 OK")
