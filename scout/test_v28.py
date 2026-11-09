"""Offline tests v2.8: runs v2.7 chain, then per-region claim times + confirmed, region conflicts, stock_level_scope."""
import json, runpy
runpy.run_path("test_v27.py")
import collect_v2 as c, enrich_feed_v2 as e
def EXPV(o, rows):  # v3.3c: exact expected expiry of a derived overall row (latest in-stock region expiry, capped at checked_at + 1h / 15m spot)
    _P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
    g = lambda r: (r.get("vendor"), r.get("gpu_model"), r.get("vram_gb"), r.get("tier"))
    cap = _P(o["checked_at"]) + (c.SPOT_REGION_TTL if o["vendor"] == "Verda" and "Spot" in o["tier"] else c.REGION_TTL)
    regs = [_P(r["availability_expires_at"]) for r in rows if r.get("region") != "all" and g(r) == g(o) and r.get("in_stock") is True and r.get("availability_expires_at")]
    return min(max(regs), cap) if o.get("in_stock") is True and regs else cap
c.time.sleep = lambda s: None; c.RP_SLEEP = lambda s: None
H = "NVIDIA H100 80GB HBM3"; calls = {}
def fake(url, data=None):
    q = json.loads(data)["query"]; sec = "secureCloud:true" in q
    if "dataCenters" in q:
        return {"data": {"dataCenters": [{"id": d_, "location": "X", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": "Low"}]}
                                         for d_ in ("US-GA-2", "US-NE-1", "EU-RO-1")]}}
    if "dataCenterId" not in q:  # Secure overall Medium; Community overall unknown
        return {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": "Medium" if sec else None, "uninterruptablePrice": 2.99 if sec else None}}]}}
    dc = q.split('dataCenterId:"')[1].split('"')[0]; k = (dc, sec); calls[k] = calls.get(k, 0) + 1; n = calls[k]
    nul = {"stockStatus": None, "uninterruptablePrice": None}
    lv = lambda s_: {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": s_, "uninterruptablePrice": 3.99}}]}}
    if dc == "US-GA-2" and sec: return lv("Low")                          # both passes Low -> confirmed
    if dc == "US-NE-1" and sec: return lv("Low" if n == 1 else "Medium")  # passes differ -> not confirmed
    if dc == "EU-RO-1" and not sec: return lv("High")                    # Community region High, overall null -> conflict
    return {"data": {"gpuTypes": [{"id": H, "lowestPrice": nul}]}}
c.get = fake; c.RP_LOG.clear()
rows, _ = c.runpod(); c.add_claim_fields(rows)
reg = {(r["tier"], r["region"]): r for r in rows}
ga, ne = reg[("On-demand (Secure Cloud)", "US-GA-2 (X)")], reg[("On-demand (Secure Cloud)", "US-NE-1 (X)")]
assert ga["confirmed"] is True and ga["second_read_stock_level"] == "Low"
assert ne["confirmed"] is True and ne["stock_level"] == "Low" and ne["second_read_stock_level"] == "Medium"  # first read kept, not overwritten
# item 3 (snapshot): scope
assert reg[("On-demand (Secure Cloud)", "all")]["stock_level_scope"] == "aggregate" and ga["stock_level_scope"] == "region"
assert reg[("On-demand (Community Cloud)", "all")]["stock_level_scope"] is None
feed = [{"vendor": "RunPod", "records": [
  {"gpu": "H100 SXM", "vram_gb": 80, "tier": "On-demand (Secure Cloud)", "hourly_usd": 2.99, "source_url": "x"},
  {"gpu": "H100 SXM", "vram_gb": 80, "tier": "On-demand (Community Cloud)", "hourly_usd": 2.69, "source_url": "x"}]}]
out, st = e.enrich(feed, {"rows": rows, "errors": {}}, None)
o = {r["tier"]: r for r in out}; s_, cm = o["On-demand (Secure Cloud)"], o["On-demand (Community Cloud)"]
# item 1: per-region checked_at + 1h expiry, label, confirmed; row-level keeps 8h
P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
assert s_["available_regions_label"].startswith("seen in stock at check time")  # v2.9 label extended
dt = {x["region"]: x for x in s_["available_regions_detail"]}
for x in dt.values():
    assert x["checked_at"] and P(x["availability_expires_at"]) - P(x["checked_at"]) == c.timedelta(hours=1)
assert dt["US-GA-2 (X)"]["checked_at"] == ga["collected_at"]
assert dt["US-GA-2 (X)"]["confirmed"] is True and dt["US-NE-1 (X)"]["confirmed"] is True  # v2.9: Low then Medium = both in stock
assert P(s_["availability_expires_at"]) - P(s_["checked_at"]) > c.timedelta(0) and P(s_["availability_expires_at"]) == EXPV(reg[("On-demand (Secure Cloud)", "all")], rows) == max(P(x["availability_expires_at"]) for x in dt.values())  # v3.3c: exact = latest in-stock region
# item 2: conflict recorded, available_regions empty
assert cm["in_stock"] is None and cm["available_regions"] is None and cm["available_regions_detail"] is None and cm["available_regions_label"] is None
assert cm["region_conflicts"] and cm["region_conflicts"][0]["region"] == "EU-RO-1 (X)" and cm["region_conflicts"][0]["stock_level"] == "High" and cm["region_conflicts"][0]["conflict"] is True
assert st["region_conflicts"] and st["region_conflicts"][0]["tier"] == "On-demand (Community Cloud)"
assert s_["region_conflicts"] is None
# item 3 (feed): scope only where an overall stock_level exists
assert s_["stock_level"] == "Medium" and s_["stock_level_scope"] == "aggregate" and cm["stock_level_scope"] is None
print("test_v28 OK")
