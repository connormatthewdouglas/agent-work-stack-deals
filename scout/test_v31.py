"""Offline tests v3.1: runs the v3.0 chain, then SCOUT_DIR, temp cleanup, generation_id/manifest, RunPod 60s gap, Verda spot 15m, push_hook '== exit' keying."""
import json, os, runpy, subprocess, sys, tempfile, shutil
runpy.run_path("test_v30.py")
import collect_v2 as c, enrich_feed_v2 as e, scout_io
HERE = os.path.dirname(os.path.abspath(__file__))
P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
fmt = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ"); now = c.datetime.now(c.timezone.utc)
# ---- 4: RunPod second reads >= 60s after their own first read; all first reads first, so only the tail waits
H = "NVIDIA H100 80GB HBM3"; clk = [0.0]; slept = []; calls = {}
def slp(s): slept.append(s); clk[0] += s
def fake(url, data=None):
    clk[0] += 1.0; q = json.loads(data)["query"]; sec = "secureCloud:true" in q
    if "dataCenters" in q:
        return {"data": {"dataCenters": [{"id": f"DC-{i}", "location": "X", "gpuAvailability": [{"gpuTypeId": H, "stockStatus": "Low"}]} for i in range(5)]}}
    if "dataCenterId" not in q: return {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": None, "uninterruptablePrice": None}}]}}
    dc = q.split('dataCenterId:"')[1].split('"')[0]; k = (dc, sec); calls[k] = calls.get(k, 0) + 1
    seq = {"DC-0": ["Low", "Low"], "DC-1": ["Low", None]}.get(dc, ["High", "High"]) if sec else [None, None]
    s_ = seq[min(calls[k], 2) - 1]
    return {"data": {"gpuTypes": [{"id": H, "lowestPrice": {"stockStatus": s_, "uninterruptablePrice": 3.0 if s_ else None}}]}}
c.get = fake; c.RP_CLOCK = lambda: clk[0]; c.RP_SLEEP = slp; c.time.sleep = lambda s: None; c.RP_LOG.clear()
c.RP_TRIES = 1  # no null-retries here: isolate the gap logic
rows, _ = c.runpod()
sec = [r for r in rows if r["tier"] == "On-demand (Secure Cloud)" and r["region"] != "all"]
assert len(sec) == 5 and all(r["confirmation"] == "two_reads" for r in sec)
assert all(r["second_read_gap_s"] >= 60 for r in sec), [r["second_read_gap_s"] for r in sec]
assert c.RP_GAPS and min(c.RP_GAPS) >= 60 and sum(slept) < 70  # one wait (~<=60s) total, not 60s per data center
by = {r["region"]: r for r in sec}; assert by["DC-0 (X)"]["confirmed"] is True and by["DC-1 (X)"]["confirmed"] is False
assert all(P(r["second_read_at"]) >= P(r["collected_at"]) for r in sec)
c.RP_TRIES = 3
# ---- 5: Verda spot region claims 15 min; on-demand stays 1h; FIN-01 confirmed only on the spot row in the feed
mk = lambda tier, reg, ins, conf: dict(vendor="Verda", gpu_model="H100 SXM", vram_gb=80, tier=tier, region=reg, in_stock=ins, collected_at=fmt(now),
                                     source_url="v", stock_level=None, price_usd_hr=None, confirmation="two_reads" if reg != "all" else None, confirmed=conf)
vr = [mk("Spot instance (1x GPU)", "all", True, None), mk("Spot instance (1x GPU)", "FIN-01", True, True),
      mk("On-demand instance (1x GPU)", "all", True, None), mk("On-demand instance (1x GPU)", "FIN-01", False, False), mk("On-demand instance (1x GPU)", "FIN-02", True, True)]
for r in vr:
    if r["region"] == "all": r.pop("confirmation"); r.pop("confirmed")
c.add_claim_fields(vr)
assert P(vr[1]["availability_expires_at"]) - P(vr[1]["checked_at"]) == c.timedelta(minutes=15)
assert P(vr[4]["availability_expires_at"]) - P(vr[4]["checked_at"]) == c.timedelta(hours=1)
assert P(vr[0]["availability_expires_at"]) - P(vr[0]["checked_at"]) == c.timedelta(minutes=15)  # v3.2: Verda spot overall row also 15m (was 8h in v3.1)
feed = json.load(open(e.SRC + "/data/gpu_pricing/verda.json"))  # real feed file; only its H100 SXM records are used
feed = dict(feed, records=[r for r in feed["records"] if r["gpu"] == "H100 SXM" and r["vram_gb"] == 80])
assert {r["tier"] for r in feed["records"]} >= {"Spot instance (1x GPU)", "On-demand instance (1x GPU)"}
try:
    out, st = e.enrich([feed], {"collected_at": fmt(now), "rows": vr}, None)
    fr = {r["tier"]: r for r in out}
    spot, od = fr["Spot instance (1x GPU)"], fr["On-demand instance (1x GPU)"]
    assert spot["available_regions"] == ["FIN-01"] and "FIN-01" not in (od["available_regions"] or []) and od["available_regions"] == ["FIN-02"]
    sd = {d["region"]: d for d in spot["available_regions_detail"]}
    assert sd["FIN-01"]["confirmed"] is True and P(sd["FIN-01"]["availability_expires_at"]) - P(sd["FIN-01"]["checked_at"]) == c.timedelta(minutes=15)
    od_fin = [d for d in od["available_regions_detail"] if d["region"] == "FIN-01"]
    assert all(d["confirmed"] is False for d in od_fin)
    ENRICH_JOIN_TESTED = True
except KeyError as ex:  # feed schema differs from this minimal fixture -> fail loudly rather than skip
    raise AssertionError(f"enrich fixture mismatch: {ex}")
# ---- 3: generation_id shared by both latest files + manifest; verify catches mismatch / tampering
s = {"version": "3.1", "collected_at": fmt(now), "meta": {}, "rows": [{"vendor": "RunPod", "region": "all", "availability_expires_at": fmt(now + c.timedelta(hours=7))}]}
en = {"version": "3.1", "stats": {}, "rows": [{"vendor": "RunPod", "gpu": "H100 SXM", "availability_expires_at": fmt(now + c.timedelta(hours=7))}]}
d = tempfile.mkdtemp(); gid = scout_io.write_latest(s, en, d)
man = json.load(open(d + "/latest_manifest.json"))
assert man["generation_id"] == gid == json.load(open(d + "/availability_v2_latest.json"))["generation_id"] == json.load(open(d + "/feed_enriched_v2_latest.json"))["generation_id"]
assert set(man["files"]) == set(scout_io.LATEST) and scout_io.verify_generation(d) == []
gid2 = scout_io.write_latest(s, en, d); assert gid2 != gid and scout_io.verify_generation(d) == []
x = json.load(open(d + "/feed_enriched_v2_latest.json")); x["generation_id"] = gid; json.dump(x, open(d + "/feed_enriched_v2_latest.json", "w"))
pr = scout_io.verify_generation(d); assert any("generation_id" in p for p in pr) and any("sha256" in p for p in pr)
open(d + "/cron.log", "w").write("== exit 0\n")
env = dict(os.environ, SCOUT_OUT=d, SCOUT_DIR=HERE, PUSH_DRY_RUN="1", LOCK_WAIT="2"); env.pop("SCOUT_LOCK_HELD", None)
p = subprocess.run(["bash", "push_hook.sh"], env=env, capture_output=True, text=True, timeout=30)
assert p.returncode == 3 and "not a matched set" in p.stdout, (p.returncode, p.stdout, p.stderr)
os.remove(d + "/latest_manifest.json"); p = subprocess.run(["bash", "push_hook.sh"], env=env, capture_output=True, text=True, timeout=30)
assert p.returncode == 3 and "manifest missing" in p.stdout
# ---- 2: failed write removes its temp files; stray temps are swept (and by prepush)
d2 = tempfile.mkdtemp(); scout_io.write_latest(s, en, d2); before = {f: open(f"{d2}/{f}").read() for f in os.listdir(d2)}
try: scout_io.write_latest(s, dict(en, rows=[{"x": object()}]), d2); assert False
except TypeError: pass
assert not [f for f in os.listdir(d2) if ".tmp" in f] and {f: open(f"{d2}/{f}").read() for f in before} == before
open(d2 + "/.availability_v2_latest.json.tmp.999", "w").write("x"); open(d2 + "/.feed_enriched_v2_latest.csv.tmp.1", "w").write("x")
assert sorted(scout_io.sweep_tmp(d2)) == [".availability_v2_latest.json.tmp.999", ".feed_enriched_v2_latest.csv.tmp.1"] and not [f for f in os.listdir(d2) if ".tmp" in f]
# ---- 6: push_hook keys on the last '== exit' line, not the last line (Gauge NOTE after it)
d3 = tempfile.mkdtemp(); scout_io.write_latest(s, en, d3)
open(d3 + "/cron.log", "w").write("== exit 0\n== 2026-10-30T14:40:19Z NOTE (Gauge QA): something\n")
p = subprocess.run(["bash", "push_hook.sh"], env=dict(env, SCOUT_OUT=d3), capture_output=True, text=True, timeout=30)
assert p.returncode == 0 and "dry run" in p.stdout and "matched" in p.stdout, (p.returncode, p.stdout, p.stderr)
open(d3 + "/cron.log", "w").write("== exit 0\n== exit 1\n== NOTE x\n")
p = subprocess.run(["bash", "push_hook.sh"], env=dict(env, SCOUT_OUT=d3), capture_output=True, text=True, timeout=30)
assert p.returncode == 1 and "last cycle not ok" in p.stdout
open(d3 + "/cron.log", "w").write("== exit 0\n== exit 10\n")  # 'exit 10' must not count as 'exit 0'... nor 'exit 0' substring tricks
p = subprocess.run(["bash", "push_hook.sh"], env=dict(env, SCOUT_OUT=d3), capture_output=True, text=True, timeout=30); assert p.returncode == 1
# ---- 1: SCOUT_DIR honoured by both scripts (sandbox copy never touches the real folder); stray temps swept under the lock
sb = tempfile.mkdtemp(); os.makedirs(sb + "/out")
for f in ("run_runpod_refresh.sh", "run_cycle.sh"): shutil.copy(f, sb)
open(sb + "/refresh_runpod.py", "w").write("print('fake refresh')\n")
open(sb + "/collect_v2.py", "w").write("print('fake collect')\n"); open(sb + "/enrich_feed_v2.py", "w").write("print('fake enrich')\n")
open(sb + "/out/.feed_enriched_v2_latest.json.tmp.42", "w").write("x"); open(sb + "/out/availability_v2_staged.json", "w").write("{}")
real_log = os.path.getmtime("/workspace/lantern-scout/out/cron.log")
envs = {k: v for k, v in os.environ.items() if k not in ("SCOUT_LOCK_HELD", "SCOUT_OUT")}
p = subprocess.run(["bash", sb + "/run_runpod_refresh.sh"], env=dict(envs, SCOUT_DIR=sb, NO_PUSH="1"), capture_output=True, text=True, timeout=30, cwd="/")
lg = open(sb + "/out/cron.log").read(); assert p.returncode == 0 and "fake refresh" in lg and lg.rstrip().endswith("== exit 0"), (p.returncode, lg)
assert not os.path.exists(sb + "/out/.feed_enriched_v2_latest.json.tmp.42")
p = subprocess.run(["bash", sb + "/run_cycle.sh"], env=dict(envs, SCOUT_DIR=sb), capture_output=True, text=True, timeout=30, cwd="/")
lg = open(sb + "/out/cron.log").read(); assert "fake collect" in lg and "fake enrich" in lg and not os.path.exists(sb + "/out/availability_v2_staged.json")
assert os.path.getmtime("/workspace/lantern-scout/out/cron.log") == real_log  # real out/ untouched
for f in ("run_runpod_refresh.sh", "run_cycle.sh"):
    t = open(f).read(); assert 'SCOUT_DIR="${SCOUT_DIR:-$(cd "$(dirname "$0")" && pwd)}"' in t and "cd /workspace/lantern-scout" not in t
assert e.SRC.endswith("/feed-src")
# ---- 9: RUN_LOG note
assert "v3.1" in open("out/RUN_LOG.txt").read()
print("test_v31 OK")
