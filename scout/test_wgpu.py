"""Offline tests for wider_gpu.py rev 4 + optional-file push handling (no network, fake keys). Run: python3 test_wgpu.py"""
import json, os, io, sys, tempfile, subprocess, urllib.request
from datetime import datetime, timezone, timedelta
import collect_v2 as c, wider_gpu as w, scout_io
RP = {"data": {"gpuTypes": [
    {"id": "NVIDIA B200", "memoryInGb": 180, "secureCloud": True, "communityCloud": True, "securePrice": 7.99, "communityPrice": 5.98},
    {"id": "NVIDIA B300 SXM6 AC", "memoryInGb": 288, "secureCloud": True, "communityCloud": True, "securePrice": 8.99, "communityPrice": 6.94},
    {"id": "NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition", "memoryInGb": 96, "secureCloud": False, "communityCloud": True, "securePrice": 0.5, "communityPrice": 1.64},
    {"id": "NVIDIA L4", "memoryInGb": 23, "secureCloud": True, "communityCloud": False, "securePrice": 0.59, "communityPrice": 0.44},
    {"id": "NVIDIA H100 80GB HBM3", "memoryInGb": 80, "secureCloud": True, "communityCloud": True, "securePrice": 3.99, "communityPrice": 2.69}]}}
def off(name, gb, n, price, mids): return [{"gpu_name": name, "gpu_ram": gb * 1024, "num_gpus": 1, "dph_total": price, "machine_id": m} for m in mids][:n]
VAST = {"offers": off("B200", 179, 6, 9.0, [1, 2, 3, 4, 5, 6]) +
        off("RTX 6000Ada", 48, 6, 0.7, [7, 7, 7, 8, 8, 9]) +                       # 6 offers but 3 machines -> held
        off("A40", 45, 3, 0.4, [10, 11, 12]) + off("A40", 48, 3, 0.6, [13, 14, 10]) +  # merged: 6 offers, 5 machines -> publishable
        off("L4", 22, 2, 0.6, [20, 21]) + off("RTX A4000", 15, 2, 0.1, [30, 31]) + off("RTX A4000", 16, 2, 0.1, [32, 33]) +
        off("B300", 269, 3, 15.0, [40, 41, 42])}
CLORE = {"servers": [{"rented": False, "specs": {"gpu": "4x NVIDIA L4", "gpuram": 23}}, {"rented": True, "specs": {"gpu": "1x Tesla T4", "gpuram": 15}},
                     {"rented": False, "specs": {"gpu": "1x NVIDIA L4", "gpuram": 48}}]}
def fake_get(url, data=None):
    for k, v in (("runpod", RP), ("vast", VAST), ("clore", CLORE), ("oauth2", {"access_token": "x"})):
        if k in url: return v
    raise AssertionError(url)
c.get = fake_get
c._get_text = lambda u: "GPU Availability<table><tr><th>GPU</th><th>MON1 (CA)</th></tr><tr><td>B200 SXM</td><td>2</td></tr><tr><td>RTX PRO6000 SE</td><td>0</td></tr></table>"
VT = [{"instance_type": i, "gpu": {"number_of_gpus": 1, "description": dsc}, "gpu_memory": {"size_in_gigabytes": gb}, "price_per_hour": p, "spot_price": sp} for i, dsc, gb, p, sp in (
      ("1B200.30V", "1x B200 SXM6 180GB", 180, 8.869, 4.435), ("1B200CC.30V", "1x B200 SXM6 180GB", 180, 9.9, 5), ("1B300.30V", "1x B300 SXM6 268GB", 268, 11.35, 5.675),
      ("1GB300.32V", "1x GB300 SXM6 288GB", 288, 13.05, 6.526), ("1V100.4V", "1x Tesla V100 16GB", 16, 0.236, 0.118),
      ("1RTXPRO6000.30V", "1x RTX PRO 6000 96GB", 96, 2.645, 1.323), ("1H100.80S.30V", "1x H100 SXM5 80GB", 80, 4.79, 2.4))]
class R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
urllib.request.urlopen = lambda req, timeout=40: R(json.dumps(VT).encode())
d = tempfile.mkdtemp(); open(d + "/verda.env", "w").write("VERDA_CLIENT_ID=a\nVERDA_CLIENT_SECRET=b\n")

# items 1-2 (Mart rev 4): official VRAM, bare names
rp = {(x["gpu_model"], x["tier"]): x for x in w.runpod()}
b = rp[("B200", "On-demand (Secure Cloud)")]; assert b["vram_gb"] == 180 and "one exception" in b["vram_note"] and "vendor reports" not in b["vram_note"] and b["price_usd_hr"] == 7.99
assert rp[("B300", "On-demand (Secure Cloud)")]["vram_gb"] == 288 and rp[("B300", "On-demand (Secure Cloud)")]["vram_note"] is None
assert ("RTX PRO 6000 Max-Q", "On-demand (Secure Cloud)") not in rp and ("RTX PRO 6000 Max-Q", "On-demand (Community Cloud)") in rp
assert not any(k[0].startswith(("L4", "H100")) for k in rp)
assert b["source_url"] == "https://www.runpod.io/pricing" and "gpuTypes.securePrice" in b["source_detail"]  # item 8
# items 6-7: Vast hold by distinct machine_id, held price blanked
v = {x["gpu_model"]: x for x in w.vast(5)}
assert all("GB" not in k for k in v), "bare names"
assert v["B200"]["vram_gb"] == 180 and v["B200"]["price_usd_hr"] == 9.0 and v["B200"]["distinct_machines"] == 6 and "vendor reports 179GB (6 offers); listed as 180GB" in v["B200"]["vram_note"] and "one exception" in v["B200"]["vram_note"]
a = v["RTX 6000 Ada"]; assert a["offer_count"] == 6 and a["distinct_machines"] == 3 and a["feed_status"] == "held_below_min_offers" and a["price_usd_hr"] is None and a["price_basis"] is None
assert "6 offers on 3 distinct machine_id" in a["availability_note"] and "price withheld" in a["availability_note"]
a40 = v["A40"]; assert a40["vram_gb"] == 48 and a40["offer_count"] == 6 and a40["distinct_machines"] == 5 and a40["feed_status"] is None and a40["price_usd_hr"] == 0.5
assert "45GB (3 offers)" in a40["vram_note"]
assert v["L4"]["vram_gb"] == 24 and "22GB" in v["L4"]["vram_note"] and v["L4"]["price_usd_hr"] is None
assert v["RTX A4000"]["vram_gb"] == 16 and v["RTX A4000"]["offer_count"] == 4 and "15GB (2 offers)" in v["RTX A4000"]["vram_note"] and v["RTX A4000"]["price_usd_hr"] is None
assert v["B300"]["vram_gb"] == 288 and "269GB" in v["B300"]["vram_note"] and v["B300"]["price_usd_hr"] is None
assert v["B200"]["source_url"] == "https://vast.ai/pricing" and v["B200"]["source_detail"].startswith("https://console.vast.ai/api/v0/bundles/?q=")
cl = {x["gpu_model"]: x for x in w.clore()}
assert cl["L4"]["unrented_servers"] == 1 and cl["L4"]["vram_gb"] == 24 and "23GB" in cl["L4"]["vram_note"] and cl["T4"]["vram_gb"] == 16
ob = {x["gpu_model"]: x for x in w.oblivus()}
assert ob["B200"]["vram_gb"] == 180 and ob["B200"]["available_gpus"] == 2 and ob["RTX PRO 6000 Server"]["vram_gb"] == 96
assert ob["RTX PRO 6000 Server"]["vram_note"] == "vendor page lists no VRAM; 96GB is the official spec" and ob["B200"]["source_url"] == "https://oblivus.com/availability/"
vd = {(x["gpu_model"], x["tier"]): x for x in w.verda(d + "/verda.env")}
assert vd[("B200", "On-demand instance (1x GPU)")]["price_usd_hr"] == 8.869, "CC variant excluded"
assert vd[("B300", "On-demand instance (1x GPU)")]["vram_gb"] == 288 and "268GB" in vd[("B300", "On-demand instance (1x GPU)")]["vram_note"]
assert vd[("GB300", "Spot instance (1x GPU)")]["price_usd_hr"] == 6.526
p6 = vd[("RTX PRO 6000", "On-demand instance (1x GPU)")]; assert "does not state the edition" in p6["vram_note"] and p6["vram_gb"] == 96  # item 11
assert vd[("V100", "On-demand instance (1x GPU)")]["source_url"] == "https://verda.com/pricing" and not any(k[0].startswith("H100") for k in vd)
# item 3: Lambda rows already live are dropped; setting switches
assert w.is_live_dupe({"vendor": "Lambda", "gpu_model": "B200", "vram_gb": 192, "tier": "On-demand instance (8x GPU)"})
# vast_alloc waits on wider_gpu._sleep / _mono (bound at import to time.sleep / time.monotonic). Advance a fake
# clock by the full requested gap so the 180s check still applies and no real sleep runs.
_vast_clk, _vast_slept = {"t": 0.0}, []
# Epoch is one gap behind wall time so collect()'s collected_at (after the fake wait) stays current.
_vast_t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=w.VAST_READ_GAP_S)
_real_now = c.NOW
def _vast_mono():
    return _vast_clk["t"]
def _vast_sleep(sec):
    _vast_slept.append(sec)
    if sec > 0: _vast_clk["t"] += sec
def _vast_now():
    return (_vast_t0 + timedelta(seconds=_vast_clk["t"])).isoformat().replace("+00:00", "Z")
w._mono, w._sleep, c.NOW = _vast_mono, _vast_sleep, _vast_now
doc = w.collect(d)
assert not doc["errors"] and doc["version"] == "3.2" and not any(r["vendor"] == "Lambda" for r in doc["rows"])
cn = doc["meta"]["counts"]; assert cn["total_rows"] == len(doc["rows"]) == cn["publishable_rows"] + cn["stock_only_rows"] + cn["held_rows"]
for x in doc["rows"]:
    assert x["source_url"].startswith("https://") and "?" not in x["source_url"] and x["source_detail"] and x["verified_at"].endswith("Z") and x["in_stock"] is None
    assert not (x.get("feed_status") and x["price_usd_hr"] is not None), "held row with price"
va = doc["meta"]["vast_allocation"]
_gap = (datetime.fromisoformat(va["read2_at"].replace("Z", "+00:00")) - datetime.fromisoformat(va["read1_at"].replace("Z", "+00:00"))).total_seconds()
assert _gap >= w.VAST_READ_GAP_S and _vast_clk["t"] >= w.VAST_READ_GAP_S and _vast_slept and min(_vast_slept) >= w.VAST_READ_GAP_S, va
assert va["min_machines"] >= w.VAST_ALLOC_MIN_MACHINES and va["sizes"] and all(
    s["status"].startswith("held:") and "fewer than" in s["status"] and s["machines1"] < va["min_machines"] and s["machines2"] < va["min_machines"] for s in va["sizes"]), va
# A clock that does not move is still rejected: the second read must be >= VAST_READ_GAP_S later.
w._sleep = lambda sec: _vast_slept.append(sec)
assert w.vast_alloc() == [] and "minimum gap" in w.VAST_ALLOC_META.get("read2_error", "")
w._sleep = _vast_sleep
# Stability at the 7-machine floor: medians within 5% publish; medians beyond 5% hold and emit no row.
def _alloc_offers(price, n=8):
    return {"offers": [{"gpu_name": "B200", "gpu_ram": 179 * 1024, "num_gpus": 1, "dph_total": price, "machine_id": i} for i in range(n)]}
_prices = []
def _alloc_get(url, data=None):
    if "vast" in url: return _alloc_offers(_prices.pop(0))
    return fake_get(url, data)
c.get = _alloc_get
_vast_clk["t"], _prices[:] = 0.0, [10.0, 10.0]
_stable = w.vast_alloc(); _smeta = dict(w.VAST_ALLOC_META)
assert len(_stable) == 1 and _stable[0]["price_usd_hr"] == 10.0 and _stable[0]["gpu_count"] == 1 and _stable[0]["distinct_machines"] == 8
assert _smeta["sizes"][0]["status"] == "published (read 2)"
assert (datetime.fromisoformat(_smeta["read2_at"].replace("Z", "+00:00")) - datetime.fromisoformat(_smeta["read1_at"].replace("Z", "+00:00"))).total_seconds() >= w.VAST_READ_GAP_S
_vast_clk["t"], _prices[:] = 0.0, [10.0, 12.0]
assert w.vast_alloc() == [] and "medians differ" in w.VAST_ALLOC_META["sizes"][0]["status"]
c.get, c.NOW = fake_get, _real_now
w.NAME_MODE = "with_vram"; assert w.canon("B200", None, 180)[0] == "B200 180GB"; assert w.canon("B300", None, 269)[2] == "vendor reports 269GB; official spec 288GB"; w.VRAM_MODE = "vendor"; assert w.canon("B200", None, 180)[1] == 180
w.NAME_MODE, w.VRAM_MODE = "bare", "official"

# items 4, 10: optional file handling
sys.path.insert(0, "bin"); import check_expiry
o = tempfile.mkdtemp(); WF = "wider_gpu_prices_latest.json"; now = datetime.now(timezone.utc)
snap = {"version": "3.2", "collected_at": c.NOW(), "rows": [{"vendor": "X", "gpu_model": "H100 SXM", "vram_gb": 80, "tier": "t", "region": "all", "in_stock": None}]}
enr = {"version": "3.2", "stats": {}, "rows": [{"vendor": "X", "gpu": "H100 SXM", "vram_gb": 80, "tier": "t"}]}
scout_io.write_latest(snap, enr, o)
assert scout_io.verify_generation(o) == [] and scout_io.screen_optional(o) == [], "missing file: left out"
json.dump(doc, open(f"{o}/{WF}", "w"))
assert scout_io.verify_generation(o) == [], "unregistered optional must not refuse the snapshot"
lg = scout_io.screen_optional(o); assert len(lg) == 1 and "unregistered" in lg[0] and not os.path.exists(f"{o}/{WF}")
json.dump(doc, open(f"{o}/{WF}", "w")); scout_io.register_optional(WF, o)
assert scout_io.verify_generation(o) == [] and scout_io.screen_optional(o) == [] and os.path.exists(f"{o}/{WF}")
scout_io.write_latest(snap, enr, o); assert WF in json.load(open(o + "/latest_manifest.json"))["files"]
assert scout_io.prepush(o)[1] == [] and check_expiry.expired(o) == []
assert len(scout_io.screen_optional(o, now + timedelta(hours=6, minutes=1))) == 1 and not os.path.exists(f"{o}/{WF}"), "stale >6h moved aside"
json.dump(doc, open(f"{o}/{WF}", "w")); scout_io.register_optional(WF, o)
open(f"{o}/{WF}", "a").write(" "); assert scout_io.verify_generation(o) == [f"{WF} sha256 differs from manifest"], "registered mismatch still refused"
# wider_gpu.main: failed run / failed register move the file aside
o2 = tempfile.mkdtemp(); json.dump(doc, open(f"{o2}/{WF}", "w"))
real = w.collect; w.collect = lambda s: dict(doc, errors={"Vast.ai": "boom"})
assert w.main(o2, d) == 1 and not os.path.exists(f"{o2}/{WF}") and any("REJECTED" in f for f in os.listdir(o2))
w.collect = lambda s: dict(doc); assert w.main(o2, d) == 1 and not os.path.exists(f"{o2}/{WF}"), "register fails (no manifest) -> aside"
w.collect = real
names = {w.stamp() for _ in range(3)}; assert len(names) == 3 and str(os.getpid()) in names.pop(), "(a) unique set-aside names"
for ts in ("Z", "+00:00"):  # (b) both offsets in screen_optional and the push-script age check
    o3 = tempfile.mkdtemp(); scout_io.write_latest(snap, enr, o3); dd = dict(doc, collected_at=(now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S") + ts)
    json.dump(dd, open(f"{o3}/{WF}", "w")); scout_io.register_optional(WF, o3); assert scout_io.screen_optional(o3) == [], ts
    chk = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "push_scout_snapshot.sh")).read().split("python3 -c '", 1)[1].split("' \"$WG\"", 1)[0]
    assert subprocess.run([sys.executable, "-c", chk, f"{o3}/{WF}"]).returncode == 0, ts
    json.dump(dict(dd, collected_at=(now - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S") + ts), open(f"{o3}/{WF}", "w"))
    assert subprocess.run([sys.executable, "-c", chk, f"{o3}/{WF}"]).returncode == 1, ts
# item 9/10/11: push script uses -s, the 6h age check, and SCOUT_TEST gating
ps = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "push_scout_snapshot.sh")).read()
assert '[ -s "$WG" ]' in ps and "6*3600" in ps and '"${SCOUT_TEST:-0}" = "1"' in ps and "REPO_URL=\"${SCOUT_PUSH_REPO_URL" not in ps
assert "timeout -k 10" in open("run_cycle.sh").read()
print("test_wgpu OK:", cn)
