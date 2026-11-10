#!/usr/bin/env python3
"""v3.5c (stage-only; Gauge QA gen 20261030T222314Z-82d2e3ae): no Clore row has in_stock=True without a two-read confirmed region,
and every Clore claim expires at most checked_at + 1h (collector and enrich). Schema 3.2 unchanged."""
import json, os, sys, copy
D = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, D)
import collect_v2 as c, enrich_feed_v2 as e
from datetime import datetime, timedelta
P = lambda t: datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
def check(rows, where):
    cl = [r for r in rows if r.get("vendor") == "Clore.ai"]
    assert cl, where + ": no Clore rows"
    for r in cl:
        if r.get("in_stock") is True:
            if r.get("region") in (None, "all"):
                assert r.get("available_regions") or any(x.get("vendor") == "Clore.ai" and x.get("gpu_model") == r.get("gpu_model") and x.get("vram_gb") == r.get("vram_gb")
                           and x.get("region") not in (None, "all") and x.get("in_stock") is True and x.get("confirmed") is True for x in rows), (where, r)
            else: assert r.get("confirmed") is True, (where, r)
        if r.get("availability_expires_at"):
            assert P(r["availability_expires_at"]) - P(r["checked_at"]) <= timedelta(hours=1), (where, r["region"], r["checked_at"], r["availability_expires_at"])
    return cl
# ---- 1: collector, two reads; per-host cc only (never invented)
def srv(gpu, ram, cc, rented=False): return {"specs": {"gpu": "1x " + gpu, "gpuram": ram, "net": ({"cc": cc} if cc else {})}, "rented": rented}
R1 = [srv("NVIDIA GeForce RTX 4090", 24, "US"), srv("NVIDIA GeForce RTX 4090", 24, "DE"), srv("NVIDIA A100SXM440GB", 40, None), srv("NVIDIA H100 NVL", 94, "US")]
R2 = [srv("NVIDIA GeForce RTX 4090", 24, "US"), srv("NVIDIA A100SXM440GB", 40, None), srv("NVIDIA H100 NVL", 94, "US", rented=True)]
n = [0]
def fake(url, data=None): n[0] += 1; return {"servers": R1 if n[0] == 1 else R2}
c.get = fake; c.time.sleep = lambda s: None; clk = [1000.0]
rows = c.clore(); c.FIRST_READ["Clore.ai"] = clk[0]
assert not any(r["in_stock"] is True and r["region"] == "all" for r in rows), "overall True before confirmation"
c.second_reads(rows, sleep=lambda s: clk.__setitem__(0, clk[0] + s), clock=lambda: clk[0]); c.add_claim_fields(rows)
assert n[0] == 2 and c.SECOND_READ_GAPS.get("Clore.ai", 0) >= 60
b = {(r["gpu_model"], r["region"]): r for r in rows}
assert b[("RTX 4090", "US")]["in_stock"] is True and b[("RTX 4090", "US")]["confirmed"] is True
assert b[("RTX 4090", "DE")]["in_stock"] is None and b[("RTX 4090", "DE")]["confirmed"] is False
assert b[("RTX 4090", "all")]["in_stock"] is True
assert b[("A100 SXM", "all")]["in_stock"] is None and b[("A100 SXM", "all")]["unrented_servers"] == 1  # no location -> unknown
assert not any(k[0] == "A100 SXM" and k[1] != "all" for k in b)  # no region invented
assert b[("H100 NVL", "all")]["in_stock"] is None and b[("H100 NVL", "US")]["in_stock"] is None
check(rows, "collector")
# second read failure -> nothing confirmed -> no True at all
n[0] = 0; c.get = fake; rows = c.clore(); c.get = lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
c.second_reads(rows, sleep=lambda s: None, clock=lambda: clk[0]); c.add_claim_fields(rows)
assert not any(r["in_stock"] is True for r in rows); check(rows, "collector, second read failed")
# ---- 2: copy of the live snapshot (old pre-fix rows) through add_claim_fields and enrich
snap = json.load(open(os.path.join(os.environ.get("SCOUT_DIR") or D, "out", "availability_v2_latest.json")))
s2 = copy.deepcopy(snap); c.add_claim_fields(s2["rows"]); check(s2["rows"], "live snapshot re-claimed")
feed = [{"vendor": "Clore.ai", "records": [{"gpu": g, "vram_gb": v, "tier": "Marketplace on-demand (host USD listings; median per GPU)", "hourly_usd": 1.0,
         "source_url": c.CLORE, "price_status": "marketplace"} for g, v in (("RTX 4090", 24), ("A100 SXM", 40), ("H100 NVL", 94))]}]
for src in (snap, s2):
    out, _ = e.enrich(feed, copy.deepcopy(src), None)
    cl = [dict(r, gpu_model=r["gpu"]) for r in out if r["vendor"] == "Clore.ai"]; assert len(cl) == 3
    for r in cl:
        assert r["in_stock"] is not True or r["available_regions"], r
        assert r["availability_expires_at"] is None or P(r["availability_expires_at"]) - P(r["checked_at"]) <= timedelta(hours=1), r
        assert r["offer_count"] is None
# ---- 2b: v3.5d Gauge re34 tamper cases (enrich must not trust forged region fields)
TIER = "Marketplace on-demand"; F1 = [{"vendor": "Clore.ai", "records": [{"gpu": "RTX 4090", "vram_gb": 24, "tier": TIER, "hourly_usd": 0.5, "source_url": "x", "price_status": "marketplace"}]}]
T0 = "2026-10-30T21:47:47Z"
def snapc(**reg):
    base = dict(vendor="Clore.ai", gpu_model="RTX 4090", vram_gb=24, tier=TIER, stock_level=None, price_usd_hr=None, source_url="x", collected_at=T0, checked_at=T0, source="public no-auth API")
    good = dict(base, region="US", in_stock=True, unrented_servers=2, confirmed=True, confirmation="two_reads", second_read_unrented_servers=2,
                second_read_at="2026-10-30T21:48:47Z", availability_expires_at="2026-10-30T22:47:47Z"); good.update(reg)
    return {"rows": [dict(base, region="all", in_stock=True, unrented_servers=2, availability_expires_at="2026-10-31T05:47:47Z"), good], "errors": {}}
def one(**reg): o, _ = e.enrich(F1, snapc(**reg), None); return o[0]
g = one()  # control: a genuinely two-read confirmed region (60s gap) publishes, capped at 1h
assert g["in_stock"] is True and g["available_regions"] == ["US"] and g["availability_expires_at"] == "2026-10-30T22:47:47Z", g
for name, kw in (("forged confirmed=True, confirmation single_read", dict(confirmation="single_read")),
                 ("10s second-read gap", dict(second_read_at="2026-10-30T21:47:57Z")),
                 ("second read saw 0 servers", dict(second_read_unrented_servers=0)), ("no second_read_at", dict(second_read_at=None))):
    t = one(**kw); assert t["in_stock"] is None and t["available_regions"] is None and not t["available_regions_detail"], (name, t)
    assert t["availability_expires_at"] is None and t["checked_at"] is None, (name, t)  # v3.5e: unknown -> no claim fields
t = one(availability_expires_at="2026-10-31T05:47:47Z")  # forged 8h region expiry
assert t["in_stock"] is True and t["available_regions"] == ["US"]
for d_ in t["available_regions_detail"]: assert P(d_["availability_expires_at"]) - P(d_["checked_at"]) <= timedelta(hours=1), d_
assert P(t["availability_expires_at"]) - P(t["checked_at"]) <= timedelta(hours=1)
print("test_v35c: Gauge re34 tamper cases rejected")
# ---- 2c: v3.5e (rollback 20261030T225130Z): unknown rows carry no expiry after enrich AND prune; Gauge hardenings
import scout_io
from datetime import timezone
t = one(second_read_unrented_servers=True)  # bool is not a count
assert t["in_stock"] is None and t["available_regions"] is None and t["availability_expires_at"] is None and t["checked_at"] is None, t
for vend in ("clore", "CLORE.AI", "Clore.ai"):  # case-insensitive vendor match
    assert e.is_clore(vend)
    sv = snapc(second_read_at="2026-10-30T21:47:57Z")  # 10s gap -> must fail for every spelling
    for r_ in sv["rows"]: r_["vendor"] = vend
    o, _ = e.enrich([dict(F1[0], vendor=vend)], sv, None); assert o[0]["in_stock"] is None and o[0]["availability_expires_at"] is None and o[0]["offer_count"] is None, (vend, o[0])
    sv = snapc(second_read_unrented_servers=True)
    for r_ in sv["rows"]: r_["vendor"] = vend
    o, _ = e.enrich([dict(F1[0], vendor=vend)], sv, None); assert o[0]["in_stock"] is None, (vend, o[0])
    sv = snapc()
    for r_ in sv["rows"]: r_["vendor"] = vend
    o, _ = e.enrich([dict(F1[0], vendor=vend)], sv, None); assert o[0]["in_stock"] is True, (vend, o[0])  # a genuine region still publishes
assert not e.is_clore("Vast.ai") and not e.is_clore(None)
# unknown Clore overall row checked > 1h ago (the rolled-back case): enrich then prune -> no expiry anywhere, nothing expired left
NOW2 = datetime(2026, 10, 30, 22, 51, 36, tzinfo=timezone.utc)
sv = snapc(confirmation="single_read")
eo, _ = e.enrich(F1, copy.deepcopy(sv), None)
assert eo[0]["in_stock"] is None and eo[0]["availability_expires_at"] is None and eo[0]["checked_at"] is None, eo[0]
bad_enr = {"rows": [dict(eo[0], checked_at=T0, availability_expires_at="2026-10-30T22:47:47Z")]}  # v35d's published shape
s3, e3, n3 = scout_io.prune_and_rederive(copy.deepcopy(sv), bad_enr, now=NOW2, files=F1)
assert n3 and scout_io.expired_left(s3, e3, NOW2) == [], scout_io.expired_left(s3, e3, NOW2)
for r_ in e3["rows"] + [x for x in s3["rows"] if x["region"] == "all"]:
    assert r_["in_stock"] is not True and r_["availability_expires_at"] is None and r_["checked_at"] is None, r_
print("test_v35c: v3.5e unknown-row expiry + hardenings OK")
# ---- 3: no version bump
assert '"version": "3.2"' in open(os.path.join(D, "collect_v2.py")).read()
print("test_v35c: all Clore assertions passed")
print("OK")
