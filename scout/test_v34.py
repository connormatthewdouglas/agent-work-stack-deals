#!/usr/bin/env python3
"""v3.4: derived overall rows always agree with their regions; real data shapes (stage-only)."""
import json, os, sys, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scout_io, refresh_multi as m, collect_v2 as c
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc); F = lambda d: (now + d).strftime("%Y-%m-%dT%H:%M:%SZ")
G = lambda r: (r["vendor"], r["gpu_model"], r["vram_gb"], r["tier"])
def reg(i, st, kind="verda", sr=None, conf="two_reads"):
    r = dict(region=f"R{i}", in_stock=st, confirmation=conf, confirmed=bool(st) and sr is True if kind == "verda" else bool(st) and bool(sr),
             checked_at=F(timedelta(minutes=-5)), availability_expires_at=F(timedelta(minutes=55 - i)), second_read_at=F(timedelta(minutes=-4)))
    r[{"verda": "second_read_in_stock", "oblivus": "second_read_available_gpus"}[kind]] = sr
    if conf == "single_read": r.pop("second_read_at"); r.pop({"verda": "second_read_in_stock", "oblivus": "second_read_available_gpus"}[kind])
    return r
def run(regs, ov=True, vendor="Verda", **ovx):
    base = {"vendor": vendor, "gpu_model": "H100 SXM", "vram_gb": 80, "tier": "On-demand instance (1x GPU)", "derived_from_regions": True}
    rows = [dict(base, region="all", in_stock=ov, checked_at=F(timedelta(minutes=-5)), availability_expires_at=F(timedelta(minutes=55)), **ovx)] + [dict(base, **r) for r in regs]
    s, _, _ = scout_io.prune_and_rederive({"meta": {}, "rows": rows}, {"rows": []}, now=now, files=[])
    return s["rows"][0]
# real shapes: out of stock everywhere = in_stock False, confirmed False, confirmation two_reads, second read negative
assert run([reg(0, False, sr=False), reg(1, False, sr=False)], ov=False)["in_stock"] is False  # stays out of stock
o = run([reg(0, False, sr=False), reg(1, False, sr=False)], ov=None); assert o["in_stock"] is False and o["availability_expires_at"] == F(timedelta(minutes=54)), o  # recomputed: earliest out-of-stock expiry
o = run([reg(0, False, "oblivus", 0), reg(1, False, "oblivus", 0)], ov=False, vendor="Oblivus"); assert o["in_stock"] is False, o
assert run([reg(0, False, sr=True)], ov=False)["in_stock"] is None            # 2nd read showed stock -> not confirmed out
assert run([reg(0, False, sr=None)], ov=False)["in_stock"] is None            # location missing on 2nd read -> unknown
assert run([reg(0, False, conf="single_read")], ov=False)["in_stock"] is None # single read -> unknown
assert run([reg(0, False, sr=False), reg(1, None, sr=None)], ov=False)["in_stock"] is None  # one unknown region -> unknown
o = run([reg(0, True, sr=True), reg(1, False, sr=False)], ov=None); assert o["in_stock"] is True and o["availability_expires_at"] == F(timedelta(minutes=55))
assert run([reg(0, True, sr=False)])["in_stock"] is None                      # in stock on one read only
assert run([])["in_stock"] is None                                            # Gauge's case: true with no regions -> unknown
# Lambda zero capacity: overall false, no region rows
LZ = dict(observation="authenticated observation: sold out - regions_with_capacity_available empty at check time")
assert run([], ov=False, vendor="Lambda", confirmation="two_reads", second_read_region_count=0, zero_capacity_two_reads=True, **LZ)["in_stock"] is False
assert run([], ov=False, vendor="Lambda", confirmation="single_read", zero_capacity_two_reads=False, **LZ)["in_stock"] is None
assert run([], ov=False, vendor="Lambda", **LZ)["in_stock"] is None                # old collector, no marker = single read
# ...and a zero-capacity false still expires: at check + 61m it is unknown
rows = [{"vendor": "Lambda", "gpu_model": "H100 SXM", "vram_gb": 80, "tier": "t", "region": "all", "in_stock": False, "derived_from_regions": True,
         "zero_capacity_two_reads": True, "checked_at": F(timedelta(minutes=-61)), "availability_expires_at": F(timedelta(minutes=-1))}]
assert scout_io.prune_and_rederive({"meta": {}, "rows": rows}, {"rows": []}, now=now, files=[])[0]["rows"][0]["in_stock"] is None
# collector: lambda_second marks the overall row from both reads (sold out on both / back on 2nd / type missing on 2nd)
T = lambda regs: {"instance_type": {"price_cents_per_hour": 299, "gpu_description": "H100"}, "regions_with_capacity_available": [{"name": x} for x in regs]}
it1 = [k for k, v in c.LAMBDA.items() if v == ("H100 SXM", 80, 1)][0]; it2 = [k for k, v in c.LAMBDA.items() if v == ("H100 PCIe", 80, 1)][0]
reads = [{it1: T([]), it2: T([])}, {it1: T([]), it2: T(["us-east-1"])}]
rows = m.lambda_first(fetch=lambda: reads.pop(0)); assert all(r["region"] == "all" and r["in_stock"] is False for r in rows)
gap = m.lambda_second(rows, sleep=lambda s: None, clock=lambda: c.FIRST_READ["Lambda"] + 61); assert gap == 61
by = {r["gpu_model"]: r for r in rows}
assert by["H100 SXM"]["zero_capacity_two_reads"] is True and by["H100 SXM"]["confirmation"] == "two_reads" and by["H100 SXM"]["second_read_region_count"] == 0
assert by["H100 PCIe"]["zero_capacity_two_reads"] is False and by["H100 PCIe"]["second_read_region_count"] == 1
reads = [{it1: T([])}, {}]; rows = m.lambda_first(fetch=lambda: reads.pop(0)); m.lambda_second(rows, sleep=lambda s: None, clock=lambda: c.FIRST_READ["Lambda"] + 61)
assert rows[0]["confirmation"] == "single_read" and rows[0]["zero_capacity_two_reads"] is False
c.add_claim_fields(rows)
# live copy
lp = os.path.join(os.environ.get("SCOUT_DIR", os.path.dirname(os.path.abspath(__file__))), "out/availability_v2_latest.json")
src = json.load(open(lp)); s, _, _ = scout_io.prune_and_rederive(copy.deepcopy(src), {"rows": []}, now=now, files=[])
after = {G(r): r for r in s["rows"] if r["region"] == "all"}
for o in [r for r in s["rows"] if r["region"] == "all" and scout_io._derived(r)]:
    regs = [r for r in s["rows"] if r["region"] != "all" and G(r) == G(o)]
    if o["in_stock"] is True: assert any(r["in_stock"] is True and r.get("confirmed") is True for r in regs), G(o)
    if o["in_stock"] is False: assert (regs and all(scout_io._out_confirmed(r) for r in regs)) or (not regs and o.get("zero_capacity_two_reads")), G(o)
    if regs and all(scout_io._out_confirmed(r) for r in regs) or (not regs and o.get("zero_capacity_two_reads") and not scout_io._exp(o, now)):
        assert o["in_stock"] is False, ("out of stock everywhere slipped to unknown", G(o))
want_out = [("Oblivus", "H100 NVLink"), ("Oblivus", "H100 PCIe"), ("Oblivus", "H100 SXM")]
want_out += [("Verda", g) for g in ("H100 SXM", "A100 SXM")]
for k, o in after.items():
    if (k[0], k[1]) in want_out and (k[0] == "Oblivus" or "On-demand" in k[3]):
        regs = [r for r in s["rows"] if r["region"] != "all" and G(r) == k]
        why = ("out on both reads everywhere" if all(scout_io._out_confirmed(r) for r in regs) else
               "in stock: " + ",".join(r["region"] for r in regs if r["in_stock"] is True and r.get("confirmed") is True) if o["in_stock"] is True else
               "not confirmed out: " + ",".join(f'{r["region"]} 2nd read in stock' for r in regs if not scout_io._out_confirmed(r)))
        print("live", k, o["in_stock"], "|", why)
        assert o["in_stock"] is (False if why == "out on both reads everywhere" else o["in_stock"]) and (o["in_stock"] is not None or "not confirmed" in why), k
    if k[0] == "RunPod" and "Community" in k[3] and k[1].startswith("A100"): print("live", k, o["in_stock"]); assert o["in_stock"] is None, k
    if k[0] == "Lambda" and k[1].startswith("H100"):
        marked = any(r.get("zero_capacity_two_reads") for r in src["rows"] if r["region"] == "all" and G(r) == k)
        print("live", k, o["in_stock"], "zero_capacity_two_reads" if marked else "no two-read marker (pre-v3.4 collector)")
        regs = [r for r in s["rows"] if r["region"] != "all" and G(r) == k]
        conf_in = any(r["in_stock"] is True and r.get("confirmed") is True for r in regs)  # Lambda can genuinely have H100 stock
        assert o["in_stock"] is (True if conf_in else False if marked else None), k
print("test_v34 OK")
