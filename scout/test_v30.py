"""Offline tests v3.0: runs v2.9 chain, then Oblivus parsing/rows, Vast+Oblivus two reads, Oblivus join, RunPod-only refresh merge."""
import json, runpy, sys
runpy.run_path("test_v29.py")
import collect_v2 as c, enrich_feed_v2 as e, refresh_runpod as rr
def EXPV(o, rows):  # v3.3c: exact expected expiry of a derived overall row (latest in-stock region expiry, capped at checked_at + 1h / 15m spot)
    _P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
    g = lambda r: (r.get("vendor"), r.get("gpu_model"), r.get("vram_gb"), r.get("tier"))
    cap = _P(o["checked_at"]) + (c.SPOT_REGION_TTL if o["vendor"] == "Verda" and "Spot" in o["tier"] else c.REGION_TTL)
    regs = [_P(r["availability_expires_at"]) for r in rows if r.get("region") != "all" and g(r) == g(o) and r.get("in_stock") is True and r.get("availability_expires_at")]
    return min(max(regs), cap) if o.get("in_stock") is True and regs else cap
P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
def page(pcie_mon, sxm_osl):
    return f"""<h2>GPU Availability</h2><p>x</p><table><tr><th>GPU</th><th>MON1 (CANADA, MONTREAL)</th><th>OSL1 (NORWAY, OSLO)</th><th>TXS1 (USA, TEXAS)</th></tr>
<tr><td>H100 80GB SXM5</td><td>0</td><td>{sxm_osl}</td><td>0</td></tr><tr><td>H100 80GB PCIE</td><td>{pcie_mon}</td><td>0</td><td>0</td></tr>
<tr><td>H100 80GB NVLINK</td><td>0</td><td>-</td><td>0</td></tr><tr><td>RTX 4090</td><td>5</td><td>0</td><td>0</td></tr></table>"""
# parse: only H100 rows, only integer cells ('-' -> no value, not 0)
d, lab = c.parse_oblivus(page(3, 2))
assert d[("H100 PCIe", 80)] == {"MON1": 3, "OSL1": 0, "TXS1": 0} and d[("H100 NVLink", 80)] == {"MON1": 0, "TXS1": 0}
assert ("RTX 4090", 24) not in d and lab["MON1"] == "MON1 (CANADA, MONTREAL)"
try: c.parse_oblivus("<html>no table</html>"); assert False
except ValueError: pass
# rows + two reads: PCIe MON1 3 -> 1 (confirmed), SXM OSL1 2 -> 0 (not confirmed)
pages = iter([page(3, 2), page(1, 0)]); c._get_text = lambda url: next(pages)
ob = c.oblivus(); by = {(r["gpu_model"], r["region"]): r for r in ob}
assert by[("H100 PCIe", "all")]["in_stock"] is True and by[("H100 PCIe", "all")]["available_gpus"] == 3
assert by[("H100 SXM", "OSL1 (NORWAY, OSLO)")]["in_stock"] is True and by[("H100 PCIe", "OSL1 (NORWAY, OSLO)")]["in_stock"] is False
# Vast H100 two reads matched by (vram, location)
H = {"offers": [{"num_gpus": 1, "gpu_ram": 81920, "geolocation": "Texas, US", "dph_total": 2.0}, {"num_gpus": 1, "gpu_ram": 81920, "geolocation": "Oslo, NO", "dph_total": 2.5}]}
H2 = {"offers": [{"num_gpus": 2, "gpu_ram": 81920, "geolocation": "Ohio, US", "dph_total": 4.0}]}
c.time.sleep = lambda s: None
vr = iter([H, {"offers": []}, {"offers": []}, {"offers": []}, {"offers": []}, H2] + [{"offers": []}] * 4); c.get = lambda url, data=None: next(vr)  # v3.5b: zero-offer models second-read too
c.VAST = {"H100 SXM": "H100 SXM", "H100 PCIe": "H100 PCIE", "A100 SXM": "A100 SXM4", "A100 PCIe": "A100 PCIE", "RTX 4090": "RTX 4090"}
vast = c.vast(); rows = vast + ob
slept = []; log = c.second_reads(rows, first_read_at=100.0, sleep=slept.append, clock=lambda: 130.0, first={})
assert slept == [30.0] * 6 and log == []  # v3.5b: H100 SXM + 4 zero-offer Vast models + Oblivus;  # v3.0 (Gauge #5): waits per source (Vast H100 SXM, Oblivus) so each 2nd read is >= 60s after ITS 1st
v = {(r["gpu_model"], r["region"]): r for r in rows if r["vendor"] == "Vast.ai"}
assert v[("H100 SXM", "US")]["confirmed"] is True and v[("H100 SXM", "US")]["second_read_offer_count"] == 1
assert v[("H100 SXM", "NO")]["confirmed"] is False and v[("H100 SXM", "NO")]["confirmation"] == "two_reads"
by = {(r["gpu_model"], r["region"]): r for r in rows if r["vendor"] == "Oblivus"}
assert by[("H100 PCIe", "MON1 (CANADA, MONTREAL)")]["confirmed"] is True and by[("H100 PCIe", "MON1 (CANADA, MONTREAL)")]["second_read_available_gpus"] == 1
assert by[("H100 SXM", "OSL1 (NORWAY, OSLO)")]["confirmed"] is False
assert by[("H100 PCIe", "OSL1 (NORWAY, OSLO)")]["confirmed"] is False  # out of stock is never confirmed in stock
assert all("_loc" not in r for r in rows)
c.add_claim_fields(rows)
for r in rows:
    if r["checked_at"]: assert (P(r["availability_expires_at"]) > P(r["checked_at"]) and P(r["availability_expires_at"]) == EXPV(r, rows)) if r["region"] == "all" and r["vendor"] in c.DERIVED_VENDORS else P(r["availability_expires_at"]) - P(r["checked_at"]) == c.timedelta(hours=8 if r["region"] == "all" else 1)  # v3.3c exact
# enrich: Oblivus H100 PCIe gets MON1 in available_regions (confirmed); Vast H100 has no feed record -> no feed row invented
feed = [{"vendor": "Oblivus", "records": [{"gpu": "H100 PCIe", "vram_gb": 80, "tier": "On-demand", "hourly_usd": 2.0, "source_url": "x"}]},
        {"vendor": "Vast.ai", "records": [{"gpu": "RTX 4090", "vram_gb": 24, "tier": "Marketplace on-demand (verified; median per GPU)", "hourly_usd": 0.3, "source_url": "x"}]}]
out, _ = e.enrich(feed, {"rows": rows, "errors": {}}, None)
o = {(r["vendor"], r["gpu"]): r for r in out}
assert ("Vast.ai", "H100 SXM") not in o
ob1 = o[("Oblivus", "H100 PCIe")]
assert ob1["in_stock"] is True and ob1["available_gpus"] == 3 and ob1["available_regions"] == ["MON1 (CANADA, MONTREAL)"]
assert ob1["available_regions_detail"][0]["available_gpus"] == 3 and ob1["available_regions_detail"][0]["second_read_available_gpus"] == 1
# RunPod refresh merge: only RunPod rows replaced, others identical, in_live_feed kept
snap = {"version": "2.9", "errors": {}, "meta": {"queried": {"q": 1}}, "rows": [{"vendor": "Vast.ai", "x": 1}, {"vendor": "RunPod", "old": True}]}
s2 = rr.merge_snapshot(snap, [{"vendor": "RunPod", "new": True}], [{"l": 1}], ["Low"], "2026-10-30T15:00:00Z")
assert s2["rows"] == [{"vendor": "Vast.ai", "x": 1}, {"vendor": "RunPod", "new": True}] and s2["meta"]["queried"] == {"q": 1}
assert s2["meta"]["runpod_refreshed_at"] == "2026-10-30T15:00:00Z" and snap["rows"][1] == {"vendor": "RunPod", "old": True}
old = {"rows": [{"vendor": "Lambda", "gpu": "H100 SXM", "vram_gb": 80, "tier": "t", "in_live_feed": True, "z": 1},
                {"vendor": "RunPod", "gpu": "H100 SXM", "vram_gb": 80, "tier": "On-demand (Secure Cloud)", "in_live_feed": True, "in_stock": None}]}
new = [{"vendor": "Lambda", "gpu": "H100 SXM", "vram_gb": 80, "tier": "t", "in_live_feed": None, "z": 2},
       {"vendor": "RunPod", "gpu": "H100 SXM", "vram_gb": 80, "tier": "On-demand (Secure Cloud)", "in_live_feed": None, "in_stock": True}]
m = rr.merge_enriched(old, new)
assert m[0] is old["rows"][0] and m[1]["in_stock"] is True and m[1]["in_live_feed"] is True

# ---- (a) Verda second read: confirmed only when both reads list the type in that location ----
c.SECOND_READ_MIN_GAP = 0
reads = {"true": [{"location_code": "FIN-01", "availabilities": ["1H100.80S.30V"]}, {"location_code": "ICE-01", "availabilities": []}],
         "false": [{"location_code": "FIN-01", "availabilities": []}, {"location_code": "ICE-01", "availabilities": []}]}
c._VERDA.clear(); c._VERDA.update(aget=lambda path: reads[path.split("is_spot=")[1]], its={("H100 SXM", 80): ["1H100.80S.30V"]})
mk = lambda tier, reg, ins: dict(vendor="Verda", gpu_model="H100 SXM", vram_gb=80, tier=tier, region=reg, in_stock=ins, collected_at="2026-10-30T14:00:00Z", source_url="v", stock_level=None, price_usd_hr=None)
vrows = [mk("Spot instance (1x GPU)", "all", True), mk("Spot instance (1x GPU)", "FIN-01", True), mk("Spot instance (1x GPU)", "ICE-01", False),
         mk("On-demand instance (1x GPU)", "FIN-01", True)]  # on-demand FIN-01: first read in stock, second read not -> unconfirmed
assert c.second_reads(vrows, 0, sleep=lambda s: None, clock=lambda: 0) == []
fin, ice, od = vrows[1], vrows[2], vrows[3]
assert fin["confirmation"] == "two_reads" and fin["confirmed"] is True and fin["second_read_in_stock"] is True
assert ice["confirmed"] is False and od["confirmed"] is False and od["second_read_in_stock"] is False
assert "confirmation" not in vrows[0]  # overall row untouched
c.add_claim_fields(vrows)
assert P(fin["availability_expires_at"]) - P(fin["checked_at"]) in (c.timedelta(hours=1), c.timedelta(minutes=15)) and P(od["availability_expires_at"]) - P(od["checked_at"]) == c.timedelta(hours=1) and P(vrows[0]["availability_expires_at"]) > P(vrows[0]["checked_at"]) and P(vrows[0]["availability_expires_at"]) == EXPV(vrows[0], vrows)  # v3.3c exact; v3.2: Verda spot overall 15m
vf = [{"vendor": "Verda (formerly DataCrunch)", "records": [{"gpu": "H100 SXM", "vram_gb": 80, "tier": "Spot instance (1x GPU)", "hourly_usd": 1.0, "source_url": "x"}]}]
vo, _ = e.enrich(vf, {"rows": vrows, "errors": {}}, None)
assert vo[0]["available_regions"] == ["FIN-01"] and vo[0]["available_regions_detail"][0]["confirmation"] == "two_reads"
# second-read failure is logged, rows stay single_read (never invented)
c._VERDA["aget"] = lambda path: (_ for _ in ()).throw(OSError("boom"))
vr2 = [mk("Spot instance (1x GPU)", "FIN-01", True)]
lg = c.second_reads(vr2, 0, sleep=lambda s: None, clock=lambda: 0)
assert lg and lg[0]["source"] == "Verda" and "confirmation" not in vr2[0]
c.add_claim_fields(vr2); assert vr2[0]["confirmation"] == "single_read"
c._VERDA.clear()
# ---- (b) push_hook.sh --force refuses when any availability_expires_at is past ----
import os, subprocess, tempfile, importlib.util
spec = importlib.util.spec_from_file_location("ce", "bin/check_expiry.py"); ce = importlib.util.module_from_spec(spec); spec.loader.exec_module(ce)
d_ = tempfile.mkdtemp()
json.dump({"rows": [{"availability_expires_at": "2099-01-01T00:00:00Z", "available_regions_detail": [{"availability_expires_at": "2020-01-01T00:00:00Z"}]}]}, open(d_ + "/feed_enriched_v2_latest.json", "w"))
assert len(ce.expired(d_)) == 1
before = os.path.getmtime("bin/push_scout_snapshot.sh") if os.path.exists("bin/push_scout_snapshot.sh") else None
json.dump({"rows": [{"region": "all", "availability_expires_at": "2020-01-01T00:00:00Z"}]}, open(d_ + "/availability_v2_latest.json", "w"))  # v3.0: overall (8h) rows are never pruned -> refuse
p = subprocess.run(["bash", "push_hook.sh", "--force"], env=dict(os.environ, SCOUT_OUT=d_, PUSH_DRY_RUN="1"), capture_output=True, text=True, timeout=30)
assert p.returncode == 3 and "refuse push" in p.stdout and ("2020-01-01T00:00:00Z" in p.stdout or "not a matched set: manifest missing" in p.stdout), (p.returncode, p.stdout, p.stderr)  # v3.3d: unmatched set is now refused first, before prepush
assert (os.path.getmtime("bin/push_scout_snapshot.sh") if before is not None else None) == before  # refused before any fetch/push
d2 = tempfile.mkdtemp(); json.dump({"rows": [{"availability_expires_at": "2099-01-01T00:00:00Z"}]}, open(d2 + "/availability_v2_latest.json", "w"))
assert ce.expired(d2) == []
q = subprocess.run([sys.executable, "bin/check_expiry.py", d2], capture_output=True, text=True); assert q.returncode == 0

# ======== Gauge v3.0 fixes ========
import scout_io, glob, fcntl, time as _time
NOWT = c.datetime(2026, 10, 30, 16, 0, 0, tzinfo=c.timezone.utc)
def det(reg, exp, conf=True): return {"region": reg, "stock_level": "High", "checked_at": "x", "availability_expires_at": exp, "confirmed": conf, "confirmation": "two_reads"}
def mk():
    snap = {"version": "3.0", "collected_at": "2026-10-30T15:30:00Z", "meta": {"runpod_refreshed_at": "2026-10-30T15:50:00Z"}, "rows": [
        {"vendor": "RunPod", "region": "all", "availability_expires_at": "2026-10-30T23:00:00Z"},
        {"vendor": "RunPod", "region": "US-TX-3", "availability_expires_at": "2026-10-30T16:50:00Z"},
        {"vendor": "Vast.ai", "region": "US", "availability_expires_at": "2026-10-30T15:59:00Z"},
        {"vendor": "Oblivus", "region": "MON1 (CANADA, MONTREAL)", "availability_expires_at": "2026-10-30T15:00:00Z"}]}
    base = {"vram_gb": 80, "in_live_feed": True, "availability_source": "x", "available_regions_label": "L", "availability_expires_at": "2026-10-30T23:00:00Z"}
    enr = {"version": "3.0", "stats": {"feed_source": "f", "dropped_stale": [], "region_conflicts": ["stale"]}, "rows": [
        dict(base, vendor="RunPod", gpu="H100 SXM", tier="Secure", in_stock=True, available_regions=["US-TX-3"], available_regions_detail=[det("US-TX-3", "2026-10-30T16:50:00Z")], region_conflicts=None),
        dict(base, vendor="Verda", gpu="H100 SXM", tier="Spot", in_stock=None, available_regions=["FIN-01"], available_regions_detail=[det("FIN-01", "2026-10-30T15:10:00Z")],
             region_conflicts=[det("FIN-01", "2026-10-30T15:10:00Z")]),
        dict(base, vendor="Oblivus", gpu="A100 PCIe", tier="On-demand", in_stock=None, available_regions=None, available_regions_detail=None, region_conflicts=[det("MON1", "2026-10-30T16:30:00Z")])]}
    return snap, enr
# 1/2: prune drops expired region rows + detail (+ available_regions, conflicts), keeps live ones and overall rows
s, en = mk(); s2, en2, n = scout_io.prune_expired(s, en, NOWT)
assert [r["region"] for r in s2["rows"]] == ["all", "US-TX-3"] and n == 2 + 2
vr = en2["rows"][1]; assert vr["available_regions"] is None and vr["available_regions_detail"] is None and vr["region_conflicts"] is None and vr["available_regions_label"] is None
assert en2["rows"][0]["available_regions"] == ["US-TX-3"] and scout_io.expired_left(s2, en2, NOWT) == []
# 3: stats recomputed incl. region_conflicts (stale entry gone; only the live Oblivus conflict) + stats_recomputed_at
en3 = scout_io.restat(en2); st = en3["stats"]
assert [x["vendor"] for x in st["region_conflicts"]] == ["Oblivus"] and st["current_rows"] == 3 and st["in_stock_true"] == 1 and "stats_recomputed_at" in st and st["feed_source"] == "f"
# 7: refresh time visible in snapshot + enriched, with precedence note
s4, en4 = scout_io.stamp_freshness(s2, en3)
assert s4["runpod_refreshed_at"] == en4["runpod_refreshed_at"] == "2026-10-30T15:50:00Z" and "takes precedence" in s4["freshness_note"] and en4["snapshot_collected_at"] == "2026-10-30T15:30:00Z"
assert "runpod_refreshed_at" in open("README.md").read() and "takes precedence" in open("README.md").read()
# 4: atomic pair write: no temp left; if a write fails midway, old latest files are untouched
d = tempfile.mkdtemp(); scout_io.write_latest(s4, en4, d)
assert [f for f in sorted(os.listdir(d)) if f != "latest_manifest.json"] == ["availability_v2_latest.csv", "availability_v2_latest.json", "feed_enriched_v2_latest.csv", "feed_enriched_v2_latest.json"]  # v3.1 adds the manifest
old = {f: open(f"{d}/{f}").read() for f in os.listdir(d)}
bad = dict(en4, rows=[{"x": object()}])  # json.dump fails on the enriched file (3rd of 4)
try: scout_io.write_latest(dict(s4, rows=[]), bad, d); assert False
except TypeError: pass
assert {f: open(f"{d}/{f}").read() for f in old} == old  # snapshot NOT replaced alone
# 1: every push path prunes first; non-force cycle/refresh path with expired region claims passes after prune (dry run)
real_now = c.datetime.now(c.timezone.utc); fmt = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
s, en = mk(); s["rows"][0]["availability_expires_at"] = fmt(real_now + c.timedelta(hours=7)); s["rows"][1]["availability_expires_at"] = fmt(real_now + c.timedelta(minutes=30))
for r in en["rows"]: r["availability_expires_at"] = fmt(real_now + c.timedelta(hours=7))
en["rows"][0]["available_regions_detail"][0]["availability_expires_at"] = fmt(real_now + c.timedelta(minutes=30))
past = fmt(real_now - c.timedelta(minutes=1)); s["rows"][2]["availability_expires_at"] = s["rows"][3]["availability_expires_at"] = past
en["rows"][1]["available_regions_detail"][0]["availability_expires_at"] = en["rows"][1]["region_conflicts"][0]["availability_expires_at"] = past
en["rows"][2]["region_conflicts"][0]["availability_expires_at"] = fmt(real_now + c.timedelta(minutes=30))
d = tempfile.mkdtemp(); scout_io.write_latest(s, en, d); open(d + "/cron.log", "w").write("== exit 0\n")
env = dict(os.environ, SCOUT_OUT=d, PUSH_DRY_RUN="1", LOCK_WAIT="2"); env.pop("SCOUT_LOCK_HELD", None)
p = subprocess.run(["bash", "push_hook.sh"], env=env, capture_output=True, text=True, timeout=30)
assert p.returncode == 0 and "dropped 4 expired" in p.stdout and "dry run" in p.stdout, (p.returncode, p.stdout, p.stderr)
assert scout_io.expired_left(json.load(open(d + "/availability_v2_latest.json")), json.load(open(d + "/feed_enriched_v2_latest.json"))) == []
# ...and refuses (exit 3) when an expired non-derived OVERALL claim remains (v3.3: row 0 relabelled Vast.ai; RunPod overall is now re-derived -> unknown), on the non-force path too
s0 = json.load(open(d + "/availability_v2_latest.json")); s0["rows"][0]["availability_expires_at"] = "2020-01-01T00:00:00Z"; s0["rows"][0]["vendor"] = "Vast.ai"; json.dump(s0, open(d + "/availability_v2_latest.json", "w"))
p = subprocess.run(["bash", "push_hook.sh"], env=env, capture_output=True, text=True, timeout=30); assert p.returncode == 3 and "refuse push" in p.stdout
# 8: standalone push_hook takes out/.scout.lock (busy -> exit 75), and does not re-lock when SCOUT_LOCK_HELD=1 (no deadlock)
fh = open(d + "/.scout.lock", "w"); fcntl.flock(fh, fcntl.LOCK_EX)
t0 = _time.time(); p = subprocess.run(["bash", "push_hook.sh"], env=env, capture_output=True, text=True, timeout=30)
assert p.returncode == 75 and "busy" in p.stdout and _time.time() - t0 >= 1.5
p = subprocess.run(["bash", "push_hook.sh"], env=dict(env, SCOUT_LOCK_HELD="1"), capture_output=True, text=True, timeout=30); assert p.returncode == 3  # ran (refused on the expired row), didn't block
fcntl.flock(fh, fcntl.LOCK_UN); fh.close()
assert "SCOUT_LOCK_HELD=1" in open("run_cycle.sh").read() and "SCOUT_LOCK_HELD=1" in open("run_runpod_refresh.sh").read()
# 5: 60s gap measured per source: Oblivus read last must still wait its full 60s; logged gaps all >= 60
c.SECOND_READ_MIN_GAP = 60; clk = [1000.0]; sl = []
def slp(x): sl.append(round(x, 1)); clk[0] += x
first = {"Vast.ai|H100 SXM": 1000.0, "Oblivus": 1053.0}  # Oblivus first read 53s after Vast's (the 7s-gap bug case)
first.update({"Vast.ai|" + m: 1000.0 for m in c.VAST})  # v3.5b: every Vast model is second-read, all first-read at 1000
pages = iter([page(1, 0)]); c._get_text = lambda url: next(pages); c.get = lambda url, data=None: H
rows5 = [dict(r, confirmation=None) for r in rows]
c.second_reads(rows5, sleep=slp, clock=lambda: clk[0], first=first)
assert sl == [60.0, 53.0] and c.SECOND_READ_GAPS == dict({"Vast.ai|" + m: 60.0 for m in c.VAST}, Oblivus=60.0), (sl, c.SECOND_READ_GAPS)
assert all(g >= c.SECOND_READ_MIN_GAP for g in c.SECOND_READ_GAPS.values())
# 6: Oblivus A100 80GB PCIe collected (exact row; 'Spot' variant not matched)
pg = page(0, 0).replace("</table>", "<tr><td>A100 80GB PCIE</td><td>1</td><td>0</td><td>0</td></tr><tr><td>A100 80GB PCIE Spot</td><td>4</td><td>0</td><td>0</td></tr></table>")
d6, _ = c.parse_oblivus(pg); assert d6[("A100 PCIe", 80)] == {"MON1": 1, "OSL1": 0, "TXS1": 0}
c._get_text = lambda url: pg; ob6 = {(r["gpu_model"], r["region"]): r for r in c.oblivus()}
assert ob6[("A100 PCIe", "all")]["in_stock"] is True and ob6[("A100 PCIe", "MON1 (CANADA, MONTREAL)")]["available_gpus"] == 1
# 9: RUN_LOG notes
rl = open("out/RUN_LOG.txt").read(); assert "Gauge v3.0 fixes" in rl and "Verda second read" in rl and "Oblivus" in rl
print("test_v30 OK")
