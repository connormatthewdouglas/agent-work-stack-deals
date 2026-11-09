"""Offline tests v3.3 (staged multi-source refresh; schema stays 3.2): Lambda two reads, vendor-scoped merges, failed source kept,
claim TTLs, run script marker pairs with push_hook, live path untouched, Lambda GET-only."""
import json, os, re, runpy, subprocess
import tempfile as _tf0; os.environ["SCOUT_BACKOFF_FILE"] = _tf0.mktemp()  # T73: tests never write backoff state into out/
runpy.run_path("test_v32.py")
import collect_v2 as c, enrich_feed_v2 as e, scout_io, refresh_multi as m
P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
fmt = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ"); now = c.datetime.now(c.timezone.utc)
LT = lambda regs, cents=299: {"instance_type": {"price_cents_per_hour": cents, "gpu_description": "H100 (80 GB SXM5)"},
                              "regions_with_capacity_available": [{"name": x} for x in regs]}
# ---- 1: Lambda two reads, >=60s gap from Lambda's own first read; confirmed only if listed on both; type missing -> unknown
reads = [{"gpu_1x_h100_sxm5": LT(["us-east-1", "us-west-1"]), "gpu_8x_h100_sxm5": LT(["us-east-1"], 2392)},
         {"gpu_1x_h100_sxm5": LT(["us-east-1"])}]
clk = [1000.0]; slept = []
rows = m.lambda_first(fetch=lambda: reads.pop(0)); c.FIRST_READ["Lambda"] = clk[0]
gap = m.lambda_second(rows, sleep=lambda s: (slept.append(s), clk.__setitem__(0, clk[0] + s)), clock=lambda: clk[0])
assert gap >= 60 and slept == [60]
by = {(r["tier"], r["region"]): r for r in rows}
one, eight = "On-demand instance (1x GPU)", "On-demand instance (8x GPU)"
assert by[(one, "us-east-1")]["confirmed"] is True and by[(one, "us-east-1")]["confirmation"] == "two_reads"
assert by[(one, "us-west-1")]["confirmed"] is False and by[(one, "us-west-1")]["second_read_in_stock"] is False
assert by[(eight, "us-east-1")]["confirmed"] is False and by[(eight, "us-east-1")]["second_read_in_stock"] is None  # not invented
assert by[(eight, "us-east-1")]["price_usd_hr"] == 2.99 and by[(one, "all")]["in_stock"] is True
c.add_claim_fields(rows)
assert P(by[(one, "us-east-1")]["availability_expires_at"]) - P(by[(one, "us-east-1")]["checked_at"]) == c.timedelta(hours=1)
assert all(k in c.FIELDS for k in ("second_read_in_stock", "second_read_gap_s", "confirmed"))
# ---- 2: snapshot merge replaces only refreshed vendors; version stays 3.2
R = lambda v, reg="all", **k: dict(vendor=v, gpu_model="H100 SXM", vram_gb=80, tier="t", region=reg, in_stock=True, **k)
snap = {"version": "3.2", "meta": {"x": 1}, "rows": [R("Vast.ai", old=1), R("Clore.ai", old=1), R("Oblivus", old=1), R("Verda", old=1), R("RunPod", old=1)]}
s2 = m.merge_snapshot(snap, {"RunPod": [R("RunPod")], "Oblivus": [R("Oblivus")]}, {"y": 2}, "T")
assert s2["version"] == "3.2" and s2["meta"]["x"] == 1 and s2["meta"]["y"] == 2 and s2["meta"]["multi_refreshed_at"] == {"RunPod": "T", "Oblivus": "T"}
kept = {r["vendor"]: r.get("old") for r in s2["rows"]}
assert kept == {"Vast.ai": 1, "Clore.ai": 1, "Verda": 1, "RunPod": None, "Oblivus": None}  # Verda failed -> old rows kept
# ---- 3: enriched merge in place, by normalized vendor; in_live_feed kept; other vendors untouched objects
ER = lambda v, **k: dict(vendor=v, gpu="H100 SXM", vram_gb=80, tier="On-demand", in_live_feed=True, **k)
old = {"rows": [ER("Verda (formerly DataCrunch)", a=0), ER("Vast.ai", a=0), ER("Lambda", a=0)]}
new = [dict(ER("Verda (formerly DataCrunch)", a=1), in_live_feed=None), dict(ER("Vast.ai", a=1)), dict(ER("Lambda", a=1), in_live_feed=None)]
mr = m.merge_enriched(old, new, {"Verda"})
assert [r["a"] for r in mr] == [1, 0, 0] and mr[0]["in_live_feed"] is True and mr[1] is old["rows"][1]
# v3.3b/c: rows new in the join are appended (in_live_feed from this run's live read); refreshed rows with an availability join say 20m
new2 = [dict(ER("Lambda", a=2, availability_source="L"), tier="On-demand instance (2x GPU)"), dict(ER("Lambda", a=1, availability_source="L"))]
mr2 = m.merge_enriched(old, new2, {"Lambda"})
assert len(mr2) == 4 and mr2[2]["a"] == 1 and mr2[2]["availability_refresh"] == "20m" and mr2[2]["in_live_feed"] is True
assert mr2[3]["tier"] == "On-demand instance (2x GPU)" and mr2[3]["in_live_feed"] is True and mr2[0] is old["rows"][0]  # v3.3c: flag from the live read
# ---- 4: collect(): a failing source is reported and not replaced; RunPod still refreshed; no key in errors
c.runpod = lambda: ([R("RunPod")], ["Low"]); c.oblivus = lambda: (_ for _ in ()).throw(RuntimeError("down"))
c.verda = lambda: []; c._VERDA.clear()
key = c._verda_env("secrets/lambda.env")["LAMBDA_API_KEY"]
c.lambda_ = lambda path="x": (_ for _ in ()).throw(OSError("HTTP 401"))
import tempfile as _tf; c.BACKOFF_FILE = _tf.mktemp()  # T73: backoff state never touches out/
c.clore = c.cloudrift = c.hyperstack = c.novita = c.thunder = lambda: (_ for _ in ()).throw(OSError("offline test"))  # T73: new multi-refresh sources, offline here
errs, meta = {}, {}
got = m.collect(errs, meta)
assert set(got) == {"RunPod", "Verda"} and "Oblivus" in errs and "Clore.ai" in errs and "CloudRift" in errs and "Lambda" in errs and key not in json.dumps(errs)
# ---- 5: run script: marker pairs with push_hook's awk, same lock, timeout < 20 min, NO_PUSH honoured; live path untouched
sh = open("run_multi_refresh.sh").read()
assert re.search(r"(cycle start|runpod refresh start)$", "== 2026-10-30T00:00:00Z multi-source runpod refresh start")
assert "out/.scout.lock" in sh and "SCOUT_LOCK_HELD=1" in sh and 'NO_PUSH:-0' in sh and "MULTI_TIMEOUT:-900" in sh
assert "refresh_multi" not in open("run_runpod_refresh.sh").read() and "refresh_multi" not in open("run_cycle.sh").read()
# ---- 6: Lambda access is GET-only (no data= / method= / launch endpoints anywhere in the new module)
src = open("refresh_multi.py").read()
assert "instance-operations" not in src and "launch\"" not in src and "method=" not in src and "data=" not in src
assert json.load(open("out/availability_v2_latest.json"))["version"] == "3.2"

# ======== v3.3b (Gauge scout-v33 fixes) ========
import tempfile, shutil, time as _t, importlib
c = importlib.reload(c); m = importlib.reload(m)  # undo the monkeypatches above
SP, OD1 = "Spot instance (1x GPU)", "On-demand instance (1x GPU)"
# ---- 7: Lambda overall rows are derived_from_regions (both collectors); outage -> overall unknown, never stale in stock
class _R:
    def __init__(s, d): s.b = json.dumps({"data": d}).encode()
    def __enter__(s): return s
    def __exit__(s, *a): return False
    def read(s, *a): return s.b
orig = c.urllib.request.urlopen
c.urllib.request.urlopen = lambda *a, **k: _R({"gpu_1x_h100_sxm5": LT(["us-east-1"]), "gpu_1x_h100_pcie": LT([])})
try: live = c.lambda_()
finally: c.urllib.request.urlopen = orig
assert all(r.get("derived_from_regions") is True for r in live if r["region"] == "all")
staged = m._map_lambda({"gpu_1x_h100_sxm5": LT(["us-east-1", "us-west-1"]), "gpu_1x_h100_pcie": LT([])})
assert all(r.get("derived_from_regions") is True for r in staged if r["region"] == "all")
def outage(rows, hours_ago):
    t = fmt(now - c.timedelta(hours=hours_ago))
    for r in rows: r["collected_at"] = t
    c.add_claim_fields(rows); snap = {"collected_at": t, "meta": {}, "rows": rows}
    feed = json.load(open(e.SRC + "/data/gpu_pricing/lambda.json"))
    en, _ = e.enrich([feed], snap, None); en = [dict(r, in_live_feed=True) for r in en]
    return scout_io.prune_and_rederive(snap, {"stats": {}, "rows": en}, files=[feed]) + (feed,)
# 7a: refresh stops for 1h05 (Lambda unreachable): regions expire -> overall in_stock None (unknown), claim fields cleared
s7, e7, _, feed = outage([dict(r) for r in staged], 1.1)
ov = {(r["gpu_model"], r["tier"]): r for r in s7["rows"] if r["region"] == "all"}
assert not [r for r in s7["rows"] if r["vendor"] == "Lambda" and r["region"] != "all"]
assert ov[("H100 SXM", OD1)]["in_stock"] is None and ov[("H100 SXM", OD1)]["availability_expires_at"] is None and "overall_recomputed_at" in ov[("H100 SXM", OD1)]
assert ov[("H100 PCIe", OD1)]["in_stock"] is not True  # was sold out: stays false (observed) until its own claim expires
assert scout_io.expired_left(s7, e7) == []
for r in e7["rows"]:
    if r["vendor"] == "Lambda" and r["gpu"] == "H100 SXM" and r["tier"] == OD1: assert r["in_stock"] is None and not r["available_regions"]
# 7b: one of two regions expired -> overall stays true, follows the live region
rows = [dict(r) for r in staged]; c.add_claim_fields(rows)
s7u, _, _ = scout_io.prune_and_rederive({"meta": {}, "rows": [dict(r) for r in rows]}, {"rows": []}, files=[])  # v3.4: single read only
assert [r for r in s7u["rows"] if r["region"] == "all" and r["gpu_model"] == "H100 SXM"][0]["in_stock"] is None  # unconfirmed regions -> unknown
for r in rows:
    if r["region"] != "all": r["confirmed"], r["confirmation"] = r["in_stock"], "two_reads"  # v3.4: as after a second read
    if r["region"] == "us-west-1": r["availability_expires_at"] = fmt(now - c.timedelta(minutes=1))
s7b, _, _ = scout_io.prune_and_rederive({"meta": {}, "rows": rows}, {"rows": []}, files=[])
o = [r for r in s7b["rows"] if r["region"] == "all" and r["gpu_model"] == "H100 SXM"][0]
assert o["in_stock"] is True and o["availability_expires_at"] == [r for r in s7b["rows"] if r["region"] == "us-east-1"][0]["availability_expires_at"]
# 7c: overall rows themselves expired (8h) with no regions -> unknown, not stale false/true
s7c, _, _, _ = outage([dict(r) for r in staged], 8.5)
assert all(r["in_stock"] is None for r in s7c["rows"] if r["region"] == "all")
# ---- 8: Verda spot 15m: between reads (16 min later) region + overall go unknown, never false or stale in stock
V = lambda reg, ins, ago: dict(vendor="Verda", gpu_model="H100 SXM", vram_gb=80, tier=SP, region=reg, in_stock=ins, collected_at=fmt(now - c.timedelta(minutes=ago)),
                               source_url="v", stock_level=None, price_usd_hr=2.397, **({"derived_from_regions": True} if reg == "all" else {"confirmation": "two_reads", "confirmed": ins}))
rows = [V("all", True, 16), V("FIN-02", True, 16), V("FIN-01", False, 16)]; c.add_claim_fields(rows)
s8, _, _ = scout_io.prune_and_rederive({"meta": {}, "rows": rows}, {"rows": []}, files=[])
assert [(r["region"], r["in_stock"], r["availability_expires_at"]) for r in s8["rows"]] == [("all", None, None)]
rows = [V("all", True, 10), V("FIN-02", True, 10)]; c.add_claim_fields(rows)  # within 15m: still in stock
assert scout_io.prune_and_rederive({"meta": {}, "rows": rows}, {"rows": []}, files=[])[0]["rows"][0]["in_stock"] is True
# ---- 9: availability_refresh 20m on rows the multi refresh covers (snapshot rows via collect())
c.runpod = lambda: ([dict(vendor="RunPod", gpu_model="H100 SXM", vram_gb=80, tier="On-demand (Secure Cloud)", region="all", in_stock=True,
                          collected_at=fmt(now), availability_refresh="4h", stock_level="Low", price_usd_hr=3.99)], ["Low"])
c.oblivus = lambda: []; c.verda = lambda: []; c._VERDA.clear(); m.lambda_first = lambda: []
got = m.collect({}, {}); assert got["RunPod"][0]["availability_refresh"] == "20m"
# ---- 10: lock: run A starts, run B skips ('== skip lock busy', no '== exit'), A exits 0 and still pushes
for sh_ in ("run_cycle.sh", "run_runpod_refresh.sh", "run_multi_refresh.sh"):
    t = open(sh_).read(); assert "skip lock busy" in t and '"== exit 75"' not in t and "grep '^== exit '" not in t, sh_
d = tempfile.mkdtemp(); os.mkdir(d + "/out")
for f in ("collect_v2.py", "enrich_feed_v2.py", "scout_io.py", "push_hook.sh", "run_multi_refresh.sh"): shutil.copy(f, d)
shutil.copytree("feed-src", d + "/feed-src", ignore=shutil.ignore_patterns(".git"))
open(d + "/refresh_multi.py", "w").write("import time, scout_io\ntime.sleep(4)\nscout_io.write_latest({'collected_at': None, 'meta': {}, 'rows': []}, {'stats': {}, 'rows': [{'vendor': 'x'}]}, 'out')\nprint('fake multi')\n")
env = dict(os.environ, SCOUT_DIR=d, PUSH_DRY_RUN="1", LOCK_WAIT="1"); env.pop("SCOUT_LOCK_HELD", None); env.pop("NO_PUSH", None)
A = subprocess.Popen(["bash", "run_multi_refresh.sh"], cwd=d, env=env)
_dl = _t.time() + 20  # T73: wait until run A actually holds the lock (no fixed sleep)
while subprocess.run(["flock", "-n", d + "/out/.scout.lock", "true"]).returncode == 0:
    assert _t.time() < _dl and A.poll() is None, "run A never took the lock"; _t.sleep(0.05)
B = subprocess.run(["bash", "run_multi_refresh.sh"], cwd=d, env=env, timeout=30)
assert A.wait(timeout=60) == 0 and B.returncode == 75
log = open(d + "/out/cron.log").read(); L = log.splitlines()
assert any(x.startswith("== skip lock busy") for x in L) and "== exit 75" not in log, log
ia = [i for i, x in enumerate(L) if x.endswith("runpod refresh start")][0]
assert [x for x in L[ia:] if x.startswith("== exit ")][0] == "== exit 0"
assert [i for i, x in enumerate(L) if x.startswith("== skip lock busy")][0] > ia  # B's skip landed inside A's run
assert "dry run: would push" in log, log  # A's push_hook keyed on A's real exit line
# push_hook alone, with a skip line between start and exit, still sees exit 0
open(d + "/out/cron.log", "w").write("== 2026-10-30T19:00:57Z multi-source runpod refresh start\n== skip lock busy 2026-10-30T19:01:00Z multi-source runpod refresh: >2s, skipped (exit 75; not an exit line)\nfake multi\n== exit 0\n")
p = subprocess.run(["bash", "push_hook.sh"], cwd=d, env=dict(env, SCOUT_OUT=d + "/out"), capture_output=True, text=True, timeout=30)
assert p.returncode == 0 and "would push" in p.stdout, p.stdout
shutil.rmtree(d)

# ======== v3.3c (Gauge scout-v33b fixes; run against the staged overlay) ========
c = importlib.reload(c); e = importlib.reload(e); scout_io = importlib.reload(scout_io); m = importlib.reload(m)
FX = json.load(open("fixtures/gauge_v33_base_1835Z_snapshot.json"))  # Gauge's 18:35Z data (cycle 17:43Z, RunPod refresh 18:35Z)
T = lambda s_: c.datetime.strptime(s_, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=c.timezone.utc)
# ---- 11 (1a): Lambda read fails -> old Lambda rows kept WITHOUT derived flag; once regions expire the overall row is unknown
assert not any(r.get("derived_from_regions") for r in FX["rows"] if r["vendor"] == "Lambda")  # the old-collector shape Gauge found
lam_ov = [r for r in FX["rows"] if r["vendor"] == "Lambda" and r["region"] == "all" and r["in_stock"] is True]
assert lam_ov and lam_ov[0]["gpu_model"] == "A100 SXM"
at = T("2026-10-30T19:00:00Z")  # regions (checked 17:4xZ, +1h) expired; overall's old 8h claim not yet
s11, _, _ = scout_io.prune_and_rederive(FX, {"rows": []}, now=at, files=[])
L = [r for r in s11["rows"] if r["vendor"] == "Lambda"]
assert not [r for r in L if r["region"] != "all"]
assert all(r["in_stock"] is not True for r in L), [(r["gpu_model"], r["in_stock"]) for r in L]
a1 = [r for r in L if r["gpu_model"] == "A100 SXM" and r["tier"] == "On-demand instance (1x GPU)"][0]
assert a1["in_stock"] is None and a1["availability_expires_at"] is None and "overall_recomputed_at" in a1
assert scout_io.expired_left(s11, {"rows": []}, now=at) == []
# enriched row follows (re-join from the pruned snapshot)
feeds = [json.load(open(f)) for f in sorted(__import__("glob").glob(e.SRC + "/data/gpu_pricing/*.json"))]
en11, _ = e.enrich(feeds, s11, None)
assert all(r["in_stock"] is not True for r in en11 if r["vendor"] == "Lambda")
# ---- 12 (1b): no derived overall row (Verda/Oblivus/RunPod/Lambda) is written with more than 1h; in stock -> latest region expiry
rows = [dict(r) for r in FX["rows"]]
stamp = fmt(now)
for r in rows: r["collected_at"] = stamp; r.pop("availability_expires_at", None); r.pop("derived_from_regions", None)
c.add_claim_fields(rows)
ov = [r for r in rows if r["region"] == "all" and r["vendor"] in c.DERIVED_VENDORS and r.get("availability_expires_at")]
assert ov and all(T(r["availability_expires_at"]) - T(r["checked_at"]) <= c.timedelta(hours=1) for r in ov)
assert all(r.get("derived_from_regions") is True for r in ov)
for r in ov:
    regs = [x["availability_expires_at"] for x in rows if x["region"] != "all" and (x["vendor"], x["gpu_model"], x["vram_gb"], x["tier"]) == (r["vendor"], r["gpu_model"], r["vram_gb"], r["tier"]) and x.get("in_stock") is True]
    if r["in_stock"] is True and regs: assert r["availability_expires_at"] == max(regs)
    else: assert T(r["availability_expires_at"]) - T(r["checked_at"]) == (c.timedelta(minutes=15) if r["vendor"] == "Verda" and "Spot" in r["tier"] else c.timedelta(hours=1))
vast_ov = [r for r in rows if r["region"] == "all" and r["vendor"] == "Vast.ai" and r.get("availability_expires_at")]
assert vast_ov and all(T(r["availability_expires_at"]) - T(r["checked_at"]) <= c.timedelta(hours=1) for r in vast_ov)  # v3.5b (Gauge a): Vast overall now capped 1h
# ---- 13 (3): enrich copies availability_refresh from the snapshot row (no hardcoded 4h)
s13 = {"meta": {}, "rows": [dict(r, availability_refresh="20m") if r["vendor"] == "RunPod" else r for r in FX["rows"]]}
en13, _ = e.enrich(feeds, s13, None)
rp13 = [r for r in en13 if r["vendor"] == "RunPod" and r.get("availability_source")]
assert rp13 and all(r["availability_refresh"] == "20m" for r in rp13)
assert all(r["availability_refresh"] == "4h" for r in en13 if r["vendor"] == "Vast.ai" and r.get("availability_source"))
# ---- 14 (3b): the multi refresh reads the live feed; in_live_feed never None for refreshed rows when the feed is readable
old_en = {"rows": [dict(ER("Lambda", a=0), in_live_feed=None)]}
nr = [dict(ER("Lambda", a=1, availability_source="L"), in_live_feed=True), dict(ER("Lambda", a=2, availability_source="L"), tier="X", in_live_feed=False)]
mm = m.merge_enriched(old_en, nr, {"Lambda"}, live_ok=True)
assert [r["in_live_feed"] for r in mm] == [True, False]
mm = m.merge_enriched({"rows": [ER("Lambda", a=0)]}, [dict(ER("Lambda", a=1), in_live_feed=None), dict(ER("Lambda", a=2), tier="X", in_live_feed=None)], {"Lambda"}, live_ok=False)
assert len(mm) == 1 and mm[0]["in_live_feed"] is True  # unreadable: keep last cycle's flag, append nothing
src = open("refresh_multi.py").read(); assert "e.fetch_live_keys()" in src and "e.enrich(files, snap2, live_keys)" in src
# end-to-end main() in a temp out/ with collectors and the live feed stubbed
d = tempfile.mkdtemp(); os.mkdir(d + "/out"); cwd = os.getcwd()
for f in ("availability_v2_latest.json", "feed_enriched_v2_latest.json"): shutil.copy("out/" + f, d + "/out/" + f)
calls = []
_cf = lambda r: dict(r, confirmed=r["in_stock"], confirmation="two_reads") if r["region"] != "all" else r  # v3.4: as after the second read
m.collect = lambda errs, meta: {"Lambda": [dict(r, availability_refresh="20m") for r in c.add_claim_fields([_cf(x) for x in m._map_lambda({"gpu_1x_a100_sxm4": {"instance_type": {"price_cents_per_hour": 129, "gpu_description": "A100 (40 GB SXM4)"}, "regions_with_capacity_available": [{"name": "us-east-1"}]}})])]}
real_live = e.fetch_live_keys
e.fetch_live_keys = lambda url=e.LIVE: (calls.append(url), ({e.live_key("Lambda", "A100 SXM", 40, "On-demand instance (1x GPU)")}, "T"))[1]
try:
    os.chdir(d); m.main()
finally:
    os.chdir(cwd); e.fetch_live_keys = real_live
en14 = json.load(open(d + "/out/feed_enriched_v2_latest.json"))
lam14 = [r for r in en14["rows"] if r["vendor"] == "Lambda"]
assert calls and lam14 and all(r["in_live_feed"] is not None for r in lam14), [(r["tier"], r["in_live_feed"]) for r in lam14]
a14 = [r for r in lam14 if r["gpu"] == "A100 SXM" and r["vram_gb"] == 40 and "1x" in r["tier"]][0]
assert a14["in_live_feed"] is True and a14["availability_refresh"] == "20m" and a14["in_stock"] is True
shutil.rmtree(d)
# ---- 15 (minor): run_cycle.sh pushes only on its own exit code
t = open("run_cycle.sh").read(); assert '[ "$rc" = "0" ] && [ -x ./push_hook.sh ]' in t
d = tempfile.mkdtemp(); os.mkdir(d + "/out")
for f in ("run_cycle.sh", "push_hook.sh", "scout_io.py", "collect_v2.py", "enrich_feed_v2.py"): shutil.copy(f, d)
open(d + "/collect_v2.py", "w").write("import sys; sys.exit(2)\n")
open(d + "/cron.log", "w").write("")
env = dict(os.environ, SCOUT_DIR=d, PUSH_DRY_RUN="1"); env.pop("SCOUT_LOCK_HELD", None)
p = subprocess.run(["bash", "run_cycle.sh"], cwd=d, env=env, capture_output=True, text=True, timeout=60)
log = open(d + "/out/cron.log").read()
assert p.returncode == 2 and "== exit 2" in log and "skip push" not in log and "would push" not in log, (p.returncode, log)
shutil.rmtree(d)
# ---- 16: scout-data commit message = current generation time + generation_id (not the 4h cycle's collected_at)
ps = open(os.environ.get("SCOUT_MART_PUSH_SCRIPT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "push_scout_snapshot.sh"))).read()  # repo script; was bin/push_scout_snapshot.sh on the work box
if "SCOUT_MSG_PY" not in ps: print("test 16 skipped: commit-label change not in this deploy (Mart follow-up)")
else:
  assert 'commit -qm "$(python3 "$SCOUT_MSG_PY" latest)"' in ps and '["collected_at"])\')"' not in ps
  py = ps.split("cat > \"$SCOUT_MSG_PY\" <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
  d = tempfile.mkdtemp(); open(d + "/msg.py", "w").write(py)
  def msg(doc):
      json.dump(doc, open(d + "/availability_v2_latest.json", "w"))
      return subprocess.run(["python3", d + "/msg.py", d], capture_output=True, text=True, check=True).stdout.strip()
  assert msg({"collected_at": "2026-10-30T17:43:31Z", "generation_id": "20261030T190002Z-36bf9620"}) == "scout snapshot 2026-10-30T19:00:02Z gen 20261030T190002Z-36bf9620"
  assert msg({"collected_at": "2026-10-30T17:43:31Z"}) == "scout snapshot gen unknown (collected_at 2026-10-30T17:43:31Z)"
  gid = scout_io.write_latest({"collected_at": "2026-10-30T17:43:31Z", "meta": {}, "rows": []}, {"stats": {}, "rows": [{"vendor": "x"}]}, d)
  assert msg(json.load(open(d + "/availability_v2_latest.json"))).endswith("gen " + gid) and "17:43:31" not in msg(json.load(open(d + "/availability_v2_latest.json")))
  shutil.rmtree(d)
# ---- 17 (v3.3c 1a): carried-over Lambda overall rows with the old 8h expiry (18:35Z fixture, no derived flag)
import copy as _cp
from datetime import datetime, timedelta, timezone
_b = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures/gauge_v33_base_1835Z_snapshot.json")))
_P = lambda t: datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
_lam = [r for r in _b["rows"] if r["vendor"] == "Lambda" and r["region"] == "all" and r.get("in_stock") is False]
assert len(_lam) == 5 and all(_P(r["availability_expires_at"]) - _P(r["checked_at"]) == timedelta(hours=8) for r in _lam)
_ck = max(_P(r["checked_at"]) for r in _lam)
# (i) still inside the 1h cap: expiry normalized to checked_at + 1h, the false claim kept (it is still within 1h of its check)
_s, _, _ = scout_io.prune_and_rederive(_cp.deepcopy(_b), {"rows": []}, now=_ck + timedelta(minutes=30), files=[])
for r in [x for x in _s["rows"] if x["vendor"] == "Lambda" and x["region"] == "all" and x.get("checked_at")]:
    assert _P(r["availability_expires_at"]) - _P(r["checked_at"]) <= timedelta(hours=1) and _P(r["availability_expires_at"]) > _P(r["checked_at"]), r
# (ii) Gauge's case: fixture time + 65m -> no 8h expiry, no stale false; Lambda has no region rows (us-east-1/us-west-2 expired 18:42Z) so every overall becomes unknown
_now = _P(_b["meta"]["generated_at"]) + timedelta(minutes=65) if _b.get("meta", {}).get("generated_at") else _ck + timedelta(minutes=65)
_s, _, _ = scout_io.prune_and_rederive(_cp.deepcopy(_b), {"rows": []}, now=_now, files=[])
_la = [x for x in _s["rows"] if x["vendor"] == "Lambda" and x["region"] == "all"]
assert len(_la) == 6 and all(x.get("in_stock") is None for x in _la), [(x["gpu_model"], x.get("in_stock")) for x in _la]
assert not any(x.get("availability_expires_at") and _P(x["availability_expires_at"]) - _P(x["checked_at"] or x["availability_expires_at"]) > timedelta(hours=1) for x in _la)
# v3.5e: Clore overall rows are derived now too: at +65m none keeps an 8h expiry or an unconfirmed in-stock claim (was: untouched)
_o = lambda sn: [x for x in sn["rows"] if x["vendor"] in ("Clore.ai",) and x["region"] == "all"]
assert _o(_s) and all(x.get("in_stock") is not True and x.get("availability_expires_at") is None for x in _o(_s)), _o(_s)
# v3.5b (Gauge a): Vast overall rows are derived now: at +65m none keeps an 8h expiry or an unconfirmed in-stock claim
_v = [x for x in _s["rows"] if x["vendor"] == "Vast.ai" and x["region"] == "all"]
assert _v and all(x.get("in_stock") is not True and not (x.get("availability_expires_at") and _P(x["availability_expires_at"]) - _P(x["checked_at"]) > timedelta(hours=1)) for x in _v)
# ---- 18 (v3.3d): tampered file + expired row -> prepush exits 3 BEFORE any rewrite (no laundering through a new manifest)
import hashlib as _hl
_here = os.path.dirname(os.path.abspath(__file__)); _src = os.path.join(os.environ.get("SCOUT_DIR", _here), "out")
_d = tempfile.mkdtemp()
for _f in ("availability_v2_latest.json", "feed_enriched_v2_latest.json", "availability_v2_latest.csv", "feed_enriched_v2_latest.csv", "latest_manifest.json"):
    if os.path.exists(os.path.join(_src, _f)): shutil.copy(os.path.join(_src, _f), _d)
assert scout_io.verify_generation(_d) == [], "precondition: copied set must verify"
_a = json.load(open(_d + "/availability_v2_latest.json"))
_reg = [r for r in _a["rows"] if r.get("region") not in (None, "all")]
_a["rows"][0]["hourly_usd"] = 0.01  # tamper
(_reg[0] if _reg else _a["rows"][1])["availability_expires_at"] = "2020-01-01T00:00:00Z"  # expired row prepush would prune
json.dump(_a, open(_d + "/availability_v2_latest.json", "w"))
_snap = lambda: {f: (_hl.sha256(open(os.path.join(_d, f), "rb").read()).hexdigest(), os.stat(os.path.join(_d, f)).st_mtime_ns) for f in sorted(os.listdir(_d))}
_before = _snap()
_p = subprocess.run(["python3", os.path.join(_here, "scout_io.py"), _d], capture_output=True, text=True, timeout=60, env=dict(os.environ, NO_PUSH="1", PUSH_DRY_RUN="1"))
assert _p.returncode == 3 and "not a matched set" in _p.stdout and "dropped" not in _p.stdout, (_p.returncode, _p.stdout, _p.stderr)
assert _snap() == _before, "files were rewritten"
assert scout_io.verify_generation(_d) != []  # still detectably tampered
shutil.rmtree(_d)
print("test_v33 OK")
