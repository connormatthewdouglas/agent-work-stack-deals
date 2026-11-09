"""Offline tests v2.7: runs v2.6 chain, then claim timestamps, RunPod per-DC retry+log, region gating, per-region stock detail."""
import json, runpy
runpy.run_path("test_v26.py")
import collect_v2 as c, enrich_feed_v2 as e
def EXPV(o, rows):  # v3.3c: exact expected expiry of a derived overall row (latest in-stock region expiry, capped at checked_at + 1h / 15m spot)
    _P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
    g = lambda r: (r.get("vendor"), r.get("gpu_model"), r.get("vram_gb"), r.get("tier"))
    cap = _P(o["checked_at"]) + (c.SPOT_REGION_TTL if o["vendor"] == "Verda" and "Spot" in o["tier"] else c.REGION_TTL)
    regs = [_P(r["availability_expires_at"]) for r in rows if r.get("region") != "all" and g(r) == g(o) and r.get("in_stock") is True and r.get("availability_expires_at")]
    return min(max(regs), cap) if o.get("in_stock") is True and regs else cap
c.time.sleep = lambda s: None
SLEPT = []; c.RP_SLEEP = lambda s: SLEPT.append(s)
H, G = "NVIDIA H100 80GB HBM3", "NVIDIA GeForce RTX 4090"
calls = {}
def fake(url, data=None):
    q = json.loads(data)["query"]; sec = "secureCloud:true" in q
    if "dataCenters" in q:
        return {"data": {"dataCenters": [
            {"id": "AP-IN-2", "location": "India", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": "Low"}]},
            {"id": "EUR-IS-3", "location": "Europe", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": "Low"}]},
            {"id": "US-MO-1", "location": "United States", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": "Low"}]},
            {"id": "EUR-IS-2", "location": "Europe", "gpuAvailability": [{"gpuTypeId": G, "stockStatus": "Low"}]}]}}
    if "dataCenterId" not in q:  # aggregate: H100 Secure Medium; 4090 unknown
        return {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": "Medium" if sec else None, "uninterruptablePrice": 2.99 if sec else None}},
                                      {"id": G, "lowestPrice": {"stockStatus": None, "uninterruptablePrice": None}}]}}
    dc = q.split('dataCenterId:"')[1].split('"')[0]; k = (dc, sec); calls[k] = calls.get(k, 0) + 1; n = calls[k]
    low = {"stockStatus": "Low", "uninterruptablePrice": 3.99}; nul = {"stockStatus": None, "uninterruptablePrice": None}
    if not sec: return {"data": {"gpuTypes": [{"id": H, "lowestPrice": nul}, {"id": G, "lowestPrice": nul}]}}
    if dc == "AP-IN-2":  # flicker: null first, Low on retry
        return {"data": {"gpuTypes": [{"id": H, "lowestPrice": low if n >= 2 else nul}]}}
    if dc == "EUR-IS-3":  # HTTP 429 first, then Low
        if n == 1: raise c.urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return {"data": {"gpuTypes": [{"id": H, "lowestPrice": low}]}}
    if dc == "US-MO-1":  # always null -> no invented row, logged
        return {"data": {"gpuTypes": [{"id": H, "lowestPrice": nul}]}}
    if dc == "EUR-IS-2":
        return {"data": {"gpuTypes": [{"id": G, "lowestPrice": low}]}}
import urllib.error; c.urllib.error = urllib.error
c.get = fake; c.RP_LOG.clear()
rows, obs = c.runpod(); c.add_claim_fields(rows)
reg = {(r["gpu_model"], r["tier"], r["region"]): r for r in rows}
# item 2: retry recovers flicker and 429; persistent null logged, not invented
assert reg[("H100 SXM", "On-demand (Secure Cloud)", "AP-IN-2 (India)")]["stock_level"] == "Low"
assert reg[("H100 SXM", "On-demand (Secure Cloud)", "EUR-IS-3 (Europe)")]["stock_level"] == "Low"
assert ("H100 SXM", "On-demand (Secure Cloud)", "US-MO-1 (United States)") not in reg
mo = reg[("H100 SXM", "Data center (cloud type not stated by API)", "US-MO-1 (United States)")]
assert mo["tier"].startswith("Data center")
log = {(x["data_center"], x["cloud"]): x for x in c.RP_LOG}
assert log[("US-MO-1", "Secure")]["attempts"] == c.RP_TRIES and log[("US-MO-1", "Secure")]["result"] == "null_for_listed_gpu"
assert log[("EUR-IS-3", "Secure")]["errors"] and "429" in log[("EUR-IS-3", "Secure")]["errors"][0]
assert log[("AP-IN-2", "Secure")]["attempts"] == 2 and SLEPT and SLEPT[0] == c.RP_BACKOFF
assert ("US-MO-1", "Community") in log  # every null/empty per-DC query logged
# item 1: claim fields
for r in rows:
    claim = any(r.get(k) is not None for k in ("in_stock", "stock_level", "price_usd_hr"))
    if claim:
        assert r["checked_at"] == r["collected_at"] and r["source"]
        h = (c.datetime.strptime(r["availability_expires_at"], "%Y-%m-%dT%H:%M:%SZ") - c.datetime.strptime(r["checked_at"], "%Y-%m-%dT%H:%M:%SZ"))
        assert (h > c.timedelta(0) and c.datetime.strptime(r["availability_expires_at"], "%Y-%m-%dT%H:%M:%SZ") == EXPV(r, rows) if r["region"] == "all" and r["vendor"] in c.DERIVED_VENDORS else h == c.timedelta(hours=8 if r["region"] == "all" else 1)), r  # v3.3c: derived overall exact  # v2.9: region rows 1h (was 8h for all in v2.7)
feed = [{"vendor": "RunPod", "records": [
  {"gpu": "H100 SXM", "vram_gb": 80, "tier": "On-demand (Secure Cloud)", "hourly_usd": 2.99, "source_url": "x"},
  {"gpu": "RTX 4090", "vram_gb": 24, "tier": "On-demand (Secure Cloud)", "hourly_usd": 0.69, "source_url": "x"}]}]
out, st = e.enrich(feed, {"rows": rows, "errors": {}}, None)
o = {r["gpu"]: r for r in out}; h = o["H100 SXM"]
agg = reg[("H100 SXM", "On-demand (Secure Cloud)", "all")]
assert (h["checked_at"], h["source"], h["availability_expires_at"]) == (agg["checked_at"], agg["source"], agg["availability_expires_at"]) and h["checked_at"]
assert h["availability_checked_at"] and h["availability_source"]  # old fields kept
# item 3: 4090 overall in_stock null -> no regions despite EUR-IS-2 Low
assert o["RTX 4090"]["in_stock"] is None and o["RTX 4090"]["available_regions"] is None and o["RTX 4090"]["available_regions_detail"] is None
# item 4: per-region stock detail, distinct from overall Medium
assert h["stock_level"] == "Medium"
assert [{k: x[k] for k in ("region", "stock_level")} for x in h["available_regions_detail"]] == [  # v2.8 adds per-region keys
    {"region": "AP-IN-2 (India)", "stock_level": "Low"}, {"region": "EUR-IS-3 (Europe)", "stock_level": "Low"}]
assert h["available_regions"] == ["AP-IN-2 (India)", "EUR-IS-3 (Europe)"]
print("test_v27 OK")
