"""T73 offline tests (rev 2, Gauge NO-GO fixes): CloudRift A100 SXM 80 only, Dedicated non-MIG variants only, price+VRAM-gated join,
gap meta always written, backoff, Clore/CloudRift in the 20-min refresh, RunPod H100 NVL. No network."""
import os; os.environ["LANTERN_VENDOR_OVERRIDES"] = "off"  # pre-override logic; overrides covered by test_cloudrift_overrides.py
import json, io, os, tempfile, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
import collect_v2 as c, enrich_feed_v2 as e, scout_io, refresh_multi as m
G = 2**30
def V(n, gb, avail, per, cph=105.0, pol="Dedicated", mig=None):
    return {"name": f"x.{n}", "gpu_count": n, "vram": gb * G, "available_nodes": avail, "available_nodes_per_dc": per, "cost_per_hour": cph * n,
            "cpu_sharing_policy": pol, "mig_profile": mig}
DOC = {"data": {"instance_types": [
    {"brand_short": "A100 SXM4", "variants": [V(1, 80, 1, {"dc-a": 1}), V(8, 80, 0, {})]},
    {"brand_short": "A100 SXM4", "variants": [V(1, 80, 3, {"dc-p": 3}, pol="Packed")]},          # Packed -> never counted
    {"brand_short": "A100 SXM4", "variants": [V(1, 80, 2, {"dc-m": 2}, mig="1g.10gb")]},         # MIG slice -> never counted
    {"brand_short": "RTX 4090", "variants": [V(1, 24, 2, {"dc-a": 2}, 40.56)]},                   # out of scope
    {"brand_short": "RTX 4090", "variants": [V(1, 24, 2, {"dc-k": 2}, 39.0, pol="Packed")]},
    {"brand_short": "H100 SXM5", "variants": [V(1, 80, 1, {"dc-h": 1}, 200.0)]}]}}
ZERO = json.loads(json.dumps(DOC)); ZERO["data"]["instance_types"][0]["variants"][0].update(available_nodes=0, available_nodes_per_dc={})
c.time.sleep = lambda s: None
def run(doc1, doc2):
    c._cr_get = lambda: doc1; rows = c.cloudrift(); c._cr_get = lambda: doc2; c.FIRST_READ["CloudRift"] = 0
    log = c.second_reads(rows, sleep=lambda s: None, clock=lambda: 10 ** 9); c.add_claim_fields(rows); return rows, log
# Fix 2: scope + Packed/MIG filter
rows, log = run(DOC, DOC)
assert not log and {r["gpu_model"] for r in rows} == {"A100 SXM"} and c.CR_GPU == {("A100 SXM4", 80): ("A100 SXM", 80)}
assert not any(r["gpu_model"].startswith(("RTX 4090", "H100")) for r in rows)
k = {r["region"]: r for r in rows}
assert set(k) == {"all", "dc-a"}, set(k)  # dc-p (Packed) and dc-m (MIG) excluded
assert k["all"]["in_stock"] is True and k["dc-a"]["confirmed"] is True and k["all"]["price_usd_hr"] == 1.05
only_packed = {"data": {"instance_types": [DOC["data"]["instance_types"][1]]}}
assert c._cr_count(only_packed) == {} and c._cr_count({"data": {"instance_types": [DOC["data"]["instance_types"][4]]}}) == {}
# Fix 3: inferred tier stated; join only at matching price + 80 GB
assert "INFERRED" in k["all"]["availability_note"]
zr, _ = run(ZERO, ZERO); z = {r["region"]: r for r in zr}
assert z["all"]["in_stock"] is False and z["all"]["zero_capacity_two_reads"] is True
def feed(price, vram=80): return [{"vendor": "CloudRift", "records": [dict(gpu="A100 SXM", vram_gb=vram, tier=t, hourly_usd=price, source_url="u", checked_at="x")
                                    for t in ("On-demand", "1-month commitment")]}]
by = {r["tier"]: r for r in e.enrich(feed(1.05), {"rows": zr, "meta": {}}, None)[0]}
assert by["On-demand"]["in_stock"] is False and by["On-demand"]["availability_source"].startswith(c.CR_URL) and by["1-month commitment"]["in_stock"] is None
for bad in (e.enrich(feed(0.99), {"rows": zr, "meta": {}}, None)[0], e.enrich(feed(1.05, 40), {"rows": zr, "meta": {}}, None)[0]):
    assert all(r["in_stock"] is None and r["availability_source"] is None for r in bad)  # price/VRAM mismatch -> unknown
np = [dict(r, price_usd_hr=None) for r in zr]
assert all(r["in_stock"] is None for r in e.enrich(feed(1.05), {"rows": np, "meta": {}}, None)[0])  # no API price -> unknown
# second read disagrees -> unknown, never inferred
r2, _ = run(DOC, ZERO); now = datetime.now(timezone.utc); s2 = {"rows": r2}; scout_io.rederive_overall(s2, set(), now)
assert [r for r in r2 if r["region"] == "all"][0]["in_stock"] is None
# Fix 1: gap meta present when CloudRift SUCCEEDS (and when it fails)
c.SECOND_READ_GAPS.clear(); c.SECOND_READ_GAPS.update({"CloudRift": 61.0}); c.RP_GAPS[:] = [70.0]
meta = {}; out = c.after_second_reads(list(rows), meta, [])
assert meta["second_read_gap_s"] == {"CloudRift": 61.0} and meta["runpod_second_read_gap_s"] == {"min": 70.0, "max": 70.0, "n": 1} and len(out) == len(rows) and "nonfatal_errors" not in meta
meta = {}; out = c.after_second_reads(list(rows), meta, [{"source": "CloudRift", "key": "CloudRift", "error": "URLError"}])
assert "second_read_gap_s" in meta and "runpod_second_read_gap_s" in meta and not out and meta["nonfatal_errors"]["CloudRift"]
src = open("collect_v2.py").read(); assert "rows = after_second_reads(rows, meta, second_reads(rows, t_first))" in src
# Advisory: backoff (429 -> skip 3 runs, other error -> skip 1, success clears)
bf = tempfile.mktemp(); calls = []
def boom429(): calls.append(1); raise urllib.error.HTTPError("u", 429, "too many", {}, None)
for _ in range(1):
    try: c.with_backoff("CloudRift", boom429, bf)
    except urllib.error.HTTPError: pass
skips = 0
for _ in range(3):
    try: c.with_backoff("CloudRift", lambda: calls.append(2), bf)
    except RuntimeError as ex: skips += "backoff" in str(ex)
assert skips == 3 and calls == [1]
assert c.with_backoff("CloudRift", lambda: "ok", bf) == "ok" and "CloudRift" not in json.load(open(bf))
try: c.with_backoff("Clore.ai", lambda: (_ for _ in ()).throw(ValueError("x")), bf)
except ValueError: pass
assert json.load(open(bf))["Clore.ai"] == 1
# wiring + rules unchanged
assert c.RP["NVIDIA H100 NVL"] == ("H100 NVL", 94) and "CloudRift" in c.DERIVED_VENDORS and "CloudRift" in scout_io.DERIVED_VENDORS and {"Clore.ai", "CloudRift"} <= set(m.SOURCES)
assert 'meta["nonfatal_errors"]' in src and 'errs["cloudrift"]' not in src and '"version": "3.2"' in src
assert "min_machines" in open("wider_gpu.py").read()
seen = {}
class R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *x): pass
urllib.request.urlopen = lambda req, timeout=None: seen.update(t=timeout) or R(json.dumps(DOC).encode())
import importlib; c2 = importlib.reload(c); c2._cr_get(); assert seen["t"] == c2.CR_TIMEOUT == 20
print("test_t73 OK")
