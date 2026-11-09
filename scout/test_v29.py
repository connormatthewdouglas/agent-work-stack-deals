"""Offline tests v2.9: runs v2.8 chain, then region-row 1h expiry in the availability file, confirmed-only available_regions,
confirmed = both reads in stock, single_read labelling for other vendors / untyped DC rows."""
import json, runpy
runpy.run_path("test_v28.py")
import collect_v2 as c, enrich_feed_v2 as e
def EXPV(o, rows):  # v3.3c: exact expected expiry of a derived overall row (latest in-stock region expiry, capped at checked_at + 1h / 15m spot)
    _P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
    g = lambda r: (r.get("vendor"), r.get("gpu_model"), r.get("vram_gb"), r.get("tier"))
    cap = _P(o["checked_at"]) + (c.SPOT_REGION_TTL if o["vendor"] == "Verda" and "Spot" in o["tier"] else c.REGION_TTL)
    regs = [_P(r["availability_expires_at"]) for r in rows if r.get("region") != "all" and g(r) == g(o) and r.get("in_stock") is True and r.get("availability_expires_at")]
    return min(max(regs), cap) if o.get("in_stock") is True and regs else cap
c.time.sleep = lambda s: None; c.RP_SLEEP = lambda s: None
H, A = "NVIDIA H100 80GB HBM3", "NVIDIA A100 80GB PCIe"; calls = {}
def fake(url, data=None):
    q = json.loads(data)["query"]; sec = "secureCloud:true" in q
    if "dataCenters" in q:
        return {"data": {"dataCenters": [{"id": "US-GA-2", "location": "X", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": "Low"}]},
            {"id": "US-NE-1", "location": "X", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": "Low"}]},
            {"id": "US-TX-9", "location": "X", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": "Low"}]},
            {"id": "EU-RO-1", "location": "Europe", "gpuAvailability": [{"gpuTypeId": A, "stockStatus": "Low"}]}]}}
    if "dataCenterId" not in q:
        return {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": "Medium" if sec else None, "uninterruptablePrice": 2.99 if sec else None}},
                                      {"id": A, "lowestPrice": {"stockStatus": None, "uninterruptablePrice": None}}]}}
    dc = q.split('dataCenterId:"')[1].split('"')[0]; k = (dc, sec); calls[k] = calls.get(k, 0) + 1; n = calls[k]
    lv = lambda s_: {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": s_, "uninterruptablePrice": 3.99 if s_ else None}}]}}
    if sec and dc == "US-GA-2": return lv("Low")                          # Low, Low -> confirmed
    if sec and dc == "US-NE-1": return lv("Low" if n == 1 else "Medium")  # Low, Medium -> confirmed (both in stock)
    if sec and dc == "US-TX-9": return lv("Low" if n == 1 else None)      # Low, then null -> NOT confirmed
    return lv(None)
c.get = fake; c.RP_LOG.clear()
rows, _ = c.runpod(); c.add_claim_fields(rows)
reg = {(r["tier"], r["region"]): r for r in rows}
P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
# item 3: confirmed = both reads in stock; second level kept
ne, tx = reg[("On-demand (Secure Cloud)", "US-NE-1 (X)")], reg[("On-demand (Secure Cloud)", "US-TX-9 (X)")]
assert ne["confirmed"] is True and ne["second_read_stock_level"] == "Medium" and ne["stock_level"] == "Low"
assert tx["confirmed"] is False and tx["second_read_stock_level"] is None and tx["confirmation"] == "two_reads"
# item 1 + 5: availability file -> per-DC rows (typed and untyped in-stock) 1h, overall rows 8h
ro = reg[("Data center (cloud type not stated by API)", "EU-RO-1 (Europe)")]
assert ro["in_stock"] is True and ro["confirmation"] == "single_read" and ro["confirmed"] is None
assert P(ro["availability_expires_at"]) - P(ro["checked_at"]) == c.timedelta(hours=1)
for r in rows:
    if r["checked_at"]:
        d_ = P(r["availability_expires_at"]) - P(r["checked_at"]); assert (d_ > c.timedelta(0) and P(r["availability_expires_at"]) == EXPV(r, rows) if r["region"] == "all" and r["vendor"] in c.DERIVED_VENDORS else d_ == c.timedelta(hours=8 if r["region"] == "all" else 1)), r  # v3.3c exact
# same check against a JSON round-trip of the availability document, as written to out/availability_v2_latest.json
doc = json.loads(json.dumps({"version": "2.9", "rows": rows}))
dcrows = [r for r in doc["rows"] if r["region"] != "all" and r["checked_at"]]
assert dcrows and all(P(r["availability_expires_at"]) - P(r["checked_at"]) == c.timedelta(hours=1) for r in dcrows)
# item 2: available_regions only confirmed=True
feed = [{"vendor": "RunPod", "records": [{"gpu": "H100 SXM", "vram_gb": 80, "tier": "On-demand (Secure Cloud)", "hourly_usd": 2.99, "source_url": "x"}]}]
out, _ = e.enrich(feed, {"rows": rows, "errors": {}}, None); h = out[0]
assert h["available_regions"] == ["US-GA-2 (X)", "US-NE-1 (X)"], h["available_regions"]
assert "US-TX-9 (X)" not in h["available_regions"] and {x["region"]: x["confirmed"] for x in h["available_regions_detail"]}["US-TX-9 (X)"] is False
# the v2.8 failure case: a region with confirmed false is excluded
bad = [dict(r, confirmed=False) if r["region"] == "US-NE-1 (X)" else r for r in rows]
out, _ = e.enrich(feed, {"rows": bad, "errors": {}}, None)
assert "US-NE-1 (X)" not in (out[0]["available_regions"] or [])
# item 4: other vendors -> single_read, listed only in detail, label says so
c.get = lambda url, data=None: {"servers": [{"rented": False, "specs": {"gpu": "1x NVIDIA GeForce RTX 4090", "gpuram": 24, "net": {"cc": "DE"}}}]}
cl = c.add_claim_fields(c.clore())
de = [r for r in cl if r["region"] == "DE"][0]
assert de["confirmation"] == "single_read" and de["confirmed"] is None
assert P(de["availability_expires_at"]) - P(de["checked_at"]) == c.timedelta(hours=1)
cf = [{"vendor": "Clore.ai", "records": [{"gpu": "RTX 4090", "vram_gb": 24, "tier": "Marketplace on-demand (host USD listings; median per GPU)", "hourly_usd": 0.5, "source_url": "x"}]}]
o2, _ = e.enrich(cf, {"rows": cl, "errors": {}}, None); g = o2[0]
# v3.5c: a single-read Clore region is not a confirmed region -> region row and overall in_stock unknown, no region list
assert de["in_stock"] is None and g["in_stock"] is None and g["available_regions"] is None and g["available_regions_detail"] is None
print("test_v29 OK")
