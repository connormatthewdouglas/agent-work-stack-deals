#!/usr/bin/env python3
"""v3.5 (stage-only): Vast in the 20-min multi refresh, Gauge 4a (RunPod empty second-read level), Gauge 4b (no OOS wording on unknown rows)."""
import json, os, sys, copy
import tempfile as _tf0; os.environ["SCOUT_BACKOFF_FILE"] = _tf0.mktemp()  # T73: tests never write backoff state into out/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_v2 as c, refresh_multi as m, scout_io
from datetime import datetime, timedelta, timezone
P = lambda t: datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
# ---- 1: Vast via the existing bundles-by-location collector, two reads >= 60s, region claims <= 1h, MIN_MARKET_OFFERS hold unchanged
def offers(locs): return {"offers": [{"num_gpus": 1, "gpu_ram": 81559, "geolocation": "X, " + l, "dph_total": 2.0 + i / 10} for i, l in enumerate(locs)]}
FIRST = {"H100 SXM": ["US"] * 3 + ["AU"] * 2 + ["CZ"], "H100 PCIe": ["ZA", "ZA", "CZ"]}
SECOND = {"H100 SXM": ["US"] * 2 + ["AU"], "H100 PCIe": ["ZA"]}  # CZ gone on 2nd read
reads = {}
def fake_get(url, data=None):
    name = json.loads(__import__("urllib.parse").parse.unquote(url.split("q=", 1)[1]))["gpu_name"]["eq"]
    model = [k for k, v in c.VAST.items() if v == name][0]
    n = reads[model] = reads.get(model, 0) + 1
    return offers((FIRST if n == 1 else SECOND).get(model, []))
c.get = fake_get; c.time.sleep = lambda s: None
clk = [1000.0]; slept = []
rows = c.vast(); assert all(r["vendor"] == "Vast.ai" for r in rows)
for k in list(c.FIRST_READ): c.FIRST_READ[k] = clk[0] if k.startswith("Vast") else c.FIRST_READ[k]
c.second_reads(rows, sleep=lambda s: (slept.append(s), clk.__setitem__(0, clk[0] + s)), clock=lambda: clk[0])
assert slept and min(slept) >= 59 and all(v >= 60 for k, v in c.SECOND_READ_GAPS.items() if k.startswith("Vast")), (slept, c.SECOND_READ_GAPS)
c.add_claim_fields(rows); c.mark_vast_held(rows, 5)
by = {(r["gpu_model"], r["region"]): r for r in rows}
assert by[("H100 SXM", "US")]["confirmed"] is True and by[("H100 SXM", "AU")]["confirmed"] is True and by[("H100 SXM", "CZ")]["confirmed"] is False
for r in rows:
    if r["region"] != "all": assert timedelta(0) < P(r["availability_expires_at"]) - P(r["checked_at"]) <= timedelta(hours=1), r
assert by[("H100 SXM", "all")]["offer_count"] == 6 and by[("H100 SXM", "all")].get("feed_status") is None            # 6 >= 5 publishes
assert by[("H100 PCIe", "all")]["offer_count"] == 3 and all(r.get("feed_status") == "held_below_min_offers" for r in rows if r["gpu_model"] == "H100 PCIe")
assert c.mark_vast_held.__doc__ and "MIN_MARKET_OFFERS" in c.feed_min_market_offers.__doc__  # rule itself untouched
# refresh_multi wiring
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "refresh_multi.py")).read()
assert '("Vast.ai", c.vast)' in src and '"Vast.ai" in SOURCES' or "Vast.ai" in m.SOURCES
assert 'for n in ("Vast.ai", "Oblivus", "Verda", "Clore.ai", "CloudRift", "Hyperstack", "Novita AI", "Thunder Compute")' in src and "c.mark_vast_held(got[\"Vast.ai\"], mmo)" in src
# collect() end to end with all sources stubbed: Vast refreshed, labelled 20m, held marks applied
reads.clear(); c.FIRST_READ.clear()
import tempfile as _tf; c.BACKOFF_FILE = _tf.mktemp()  # T73: backoff state never touches out/
c.runpod = lambda: ([], []); c.oblivus = lambda: []; c.verda = lambda: []; c.clore = lambda: []; c.cloudrift = lambda: []; c.hyperstack = lambda: []; c.novita = lambda: []; c.thunder = lambda: []  # T73 stubs
m.lambda_first = lambda: []
c.second_reads.__defaults__  # (real function, fake clock not needed: sleep stubbed below)
real_sr = c.second_reads; c.second_reads = lambda rows, **kw: real_sr(rows, sleep=lambda s: None, clock=lambda: 10 ** 9)
c.feed_min_market_offers = lambda path=None: 5
errs, meta = {}, {}; got = m.collect(errs, meta); c.second_reads = real_sr
assert "Vast.ai" in got and not errs and meta["feed_min_market_offers"] == 5, (errs, meta.get("feed_min_market_offers"))
assert all(r["availability_refresh"] == "20m" for r in got["Vast.ai"])
assert all(r.get("feed_status") == "held_below_min_offers" for r in got["Vast.ai"] if r["gpu_model"] == "H100 PCIe")
assert {r["confirmation"] for r in got["Vast.ai"] if r["region"] != "all" and r["gpu_model"] in c.VAST_CONFIRM} == {"two_reads"}
# ---- 4a: RunPod empty/None second-read level is NOT confirmed out
RP = lambda lv: {"vendor": "RunPod", "in_stock": False, "confirmation": "two_reads", "second_read_stock_level": lv, "second_read_at": "2026-10-30T20:00:00Z"}
assert not scout_io._out_confirmed(RP(None)) and not scout_io._out_confirmed(RP("")) and not scout_io._out_confirmed(RP("  "))
assert not scout_io._out_confirmed(RP("Low")) and not scout_io._out_confirmed(RP("Unavailable"))  # v35b: not a known level
for lv in ("low", "LOW", "high", "Medium ", "MEDIUM", "out", "Unavailable", "None", 0, False):
    assert not scout_io._out_confirmed(RP(lv)), lv
assert c.RUNPOD_OUT_LEVELS == frozenset()  # API only ever returned High/Medium/Low/null
c.RUNPOD_OUT_LEVELS = frozenset({"OutOfStock"}); assert scout_io._out_confirmed(RP("OutOfStock")) and not scout_io._out_confirmed(RP("outofstock")); c.RUNPOD_OUT_LEVELS = frozenset()
assert not scout_io._out_confirmed(dict(RP("Unavailable"), second_read_at=None))
# ---- 4b: unknown rows never carry 'out of stock' / 'sold out' wording
now = datetime.now(timezone.utc); F = lambda d: (now + d).strftime("%Y-%m-%dT%H:%M:%SZ")
lam = {"vendor": "Lambda", "gpu_model": "H100 SXM", "vram_gb": 80, "tier": "On-demand instance (1x GPU)", "region": "all", "in_stock": False,
       "derived_from_regions": True, "checked_at": F(timedelta(minutes=-5)), "availability_expires_at": F(timedelta(minutes=55)),
       "observation": "authenticated observation: sold out - regions_with_capacity_available empty at check time",
       "availability_note": "offer_count not exposed by Lambda API; in_stock=false means no region listed capacity for this instance type"}
s, en, _ = scout_io.prune_and_rederive({"meta": {}, "rows": [dict(lam)]}, {"rows": [dict(lam, availability_note="was out of stock")]}, now=now, files=[])
o = s["rows"][0]; assert o["in_stock"] is None and o["observation"] is None
for r in s["rows"] + en["rows"]:
    if r.get("in_stock") is None:
        for k, v in r.items():
            if isinstance(v, str) and (k.endswith("note") or k.endswith("observation")): assert "out of stock" not in v.lower() and "sold out" not in v.lower(), (k, v)
s, _, _ = scout_io.prune_and_rederive({"meta": {}, "rows": [dict(lam, zero_capacity_two_reads=True)]}, {"rows": []}, now=now, files=[])
assert s["rows"][0]["in_stock"] is False and "sold out" in s["rows"][0]["observation"]   # confirmed false keeps its evidence
# live copy: no unknown row (snapshot or enriched) mentions out of stock after prune
d = os.path.join(os.environ.get("SCOUT_DIR", os.path.dirname(os.path.abspath(__file__))), "out")
s, en, _ = scout_io.prune_and_rederive(json.load(open(d + "/availability_v2_latest.json")), json.load(open(d + "/feed_enriched_v2_latest.json")), now=now, files=[])
bad = [(r["vendor"], r.get("gpu") or r.get("gpu_model"), k) for r in s["rows"] + en["rows"] if r.get("in_stock") is None
       for k, v in r.items() if isinstance(v, str) and (k.endswith("note") or k.endswith("observation")) and ("out of stock" in v.lower() or "sold out" in v.lower())]
assert not bad, bad
# ---- v35b (1): Vast is a derived vendor in both modules -> overall capped at checked_at+1h and recomputed from regions
assert "Vast.ai" in c.DERIVED_VENDORS and "Vast.ai" in scout_io.DERIVED_VENDORS
V = lambda **k: dict({"vendor": "Vast.ai", "gpu_model": "A100 SXM", "vram_gb": 80, "tier": "Marketplace on-demand (verified)", "source_url": "u", "collected_at": F(timedelta(0))}, **k)
rs = [V(region="all", in_stock=True, offer_count=11, price_usd_hr=1.1), V(region="US", in_stock=True, offer_count=6, confirmation="two_reads", confirmed=False, second_read_offer_count=0)]
c.add_claim_fields(rs); assert P(rs[0]["availability_expires_at"]) - P(rs[0]["checked_at"]) <= timedelta(hours=1) and rs[0]["derived_from_regions"] is True
s1, _, _ = scout_io.prune_and_rederive({"meta": {}, "rows": [dict(r) for r in rs]}, {"rows": []}, now=now, files=[])
o = s1["rows"][0]; assert o["in_stock"] is None and o["offer_count"] == 11 and o["price_usd_hr"] == 1.1  # (b) price kept, no unconfirmed in-stock claim
rs[1]["confirmed"] = True; s1, _, _ = scout_io.prune_and_rederive({"meta": {}, "rows": [dict(r) for r in rs]}, {"rows": []}, now=now, files=[])
assert s1["rows"][0]["in_stock"] is True
old = V(region="all", in_stock=True, offer_count=9, checked_at=F(timedelta(hours=-2)), availability_expires_at=F(timedelta(hours=6)))  # carried 8h row
s1, _, _ = scout_io.prune_and_rederive({"meta": {}, "rows": [old]}, {"rows": []}, now=now, files=[]); assert s1["rows"][0]["in_stock"] is None
# ---- v35b (2): every Vast model is second-read (A100/4090 included), zero-offer models too
assert set(c.VAST_CONFIRM) == set(c.VAST)
reads.clear(); c.FIRST_READ.clear(); rows = c.vast()
c.second_reads(rows, sleep=lambda s: None, clock=lambda: 10 ** 9)
assert {r["gpu_model"] for r in rows if r.get("confirmation") == "two_reads"} == set(c.VAST)
z = [r for r in rows if r.get("offer_count") == 0]; assert z and all(r["zero_capacity_two_reads"] is True and r["second_read_offer_count"] == 0 for r in z)
c.add_claim_fields(rows); s1, _, _ = scout_io.prune_and_rederive({"meta": {}, "rows": [dict(r) for r in rows]}, {"rows": []}, now=datetime.now(timezone.utc), files=[])
assert all(r["in_stock"] is False for r in s1["rows"] if r.get("offer_count") == 0)  # zero on both reads stays false (1h)
# ---- v35b (3): enrich zero-offer Vast row expires 1h after the query, not 8h
import enrich_feed_v2 as e
es = open(e.__file__).read(); assert "timedelta(hours=1)).strftime" in es and "timedelta(hours=8)).strftime" not in es
# ---- v35b (4): merge_snapshot writes fresh meta.queried for refreshed sources, keeps others
old_snap = {"meta": {"queried": {"Vast.ai|H100 SXM": {"queried_at": "2026-10-30T12:00:00Z"}, "Other|X": {"queried_at": "k"}}}, "rows": []}
new = m.merge_snapshot(old_snap, {"Vast.ai": []}, {"_queried_fresh": {"Vast.ai|H100 SXM": {"queried_at": "2026-10-30T21:00:00Z"}}}, "t")
assert new["meta"]["queried"] == {"Vast.ai|H100 SXM": {"queried_at": "2026-10-30T21:00:00Z"}, "Other|X": {"queried_at": "k"}} and "_queried_fresh" not in new["meta"]
new = m.merge_snapshot(old_snap, {"RunPod": []}, {}, "t"); assert new["meta"]["queried"] == old_snap["meta"]["queried"]
assert set(meta["_queried_fresh"]) == {"Vast.ai|" + k for k in c.VAST}  # from collect() above: this run's times
print("test_v35 OK")
