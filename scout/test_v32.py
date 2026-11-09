"""Offline tests v3.2: Verda spot overall 15m, derived overall rows recomputed on prune, push_hook start/exit pairing, Vast held marking."""
import json, os, runpy, subprocess, tempfile
runpy.run_path("test_v31.py")
import collect_v2 as c, enrich_feed_v2 as e, scout_io
HERE = os.path.dirname(os.path.abspath(__file__))
P = lambda t: c.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
fmt = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ"); now = c.datetime.now(c.timezone.utc)
# ---- 1a: Verda spot OVERALL row 15m; on-demand overall stays 8h
V = lambda tier, reg, ins, t=now: dict(vendor="Verda", gpu_model="H100 SXM", vram_gb=80, tier=tier, region=reg, in_stock=ins, collected_at=fmt(t), source_url="v",
                                      stock_level=None, price_usd_hr=None, **({"derived_from_regions": True} if reg == "all" else {"confirmation": "two_reads", "confirmed": ins}))
SP, OD = "Spot instance (1x GPU)", "On-demand instance (1x GPU)"
rows = [V(SP, "all", True), V(SP, "FIN-01", True), V(OD, "all", True), V(OD, "FIN-02", True)]
c.add_claim_fields(rows)
assert P(rows[0]["availability_expires_at"]) - P(rows[0]["checked_at"]) == c.timedelta(minutes=15)
assert P(rows[2]["availability_expires_at"]) == P(rows[3]["availability_expires_at"])  # v3.3: on-demand overall = its in-stock region expiry (was 8h)
# ---- 1b: prune recomputes derived overall rows: in_stock True only if a remaining region is in stock, else null
old = now - c.timedelta(minutes=20)
rows = [V(SP, "all", True, old), V(SP, "FIN-01", True, old), V(SP, "FIN-03", True, old),
        V(OD, "all", True), V(OD, "FIN-02", True), V(OD, "FIN-01", True, now - c.timedelta(hours=2)), V(OD, "FIN-03", False)]
c.add_claim_fields(rows)
snap = {"version": "3.2", "collected_at": fmt(now), "meta": {}, "rows": rows}
s2, _, n = scout_io.prune_and_rederive(snap, {"rows": []}, files=[])
by = {(r["tier"], r["region"]): r for r in s2["rows"]}
assert (SP, "FIN-01") not in by and by[(SP, "all")]["in_stock"] is None and by[(SP, "all")]["availability_expires_at"] is None and by[(SP, "all")]["checked_at"] is None
assert by[(OD, "all")]["in_stock"] is True and by[(OD, "all")]["availability_expires_at"] == by[(OD, "FIN-02")]["availability_expires_at"]  # FIN-02 still live
assert (OD, "FIN-01") not in by and "overall_recomputed_at" in by[(OD, "all")]
assert scout_io.expired_left(s2, {"rows": []}) == []  # nothing expired left -> push not blocked by the 15m spot overall row
# no region left in stock -> null, never false
rows = [V(OD, "all", True), V(OD, "FIN-02", True, now - c.timedelta(hours=2)), V(OD, "FIN-03", False)]; c.add_claim_fields(rows)
s3, _, _ = scout_io.prune_and_rederive({"rows": rows, "meta": {}}, {"rows": []}, files=[])
assert [r["in_stock"] for r in s3["rows"] if r["region"] == "all"] == [None]
# non-derived overall rows (e.g. RunPod aggregate) are untouched
rp = dict(vendor="RunPod", gpu_model="H100 SXM", vram_gb=80, tier="On-demand (Secure Cloud)", region="all", in_stock=True, collected_at=fmt(now), stock_level="Low", price_usd_hr=1.0)
rpr = dict(rp, region="US-1 (X)", collected_at=fmt(now - c.timedelta(hours=2)), confirmation="two_reads", confirmed=True)
c.add_claim_fields([rp, rpr]); s4, _, _ = scout_io.prune_and_rederive({"rows": [rp, rpr], "meta": {}}, {"rows": []}, files=[])
assert [r["region"] for r in s4["rows"]] == ["all"] and s4["rows"][0]["in_stock"] is None  # v3.3: RunPod overall is re-derived -> unknown
va = dict(rp, vendor="Vast.ai", tier="Marketplace on-demand (verified)"); va.pop("derived_from_regions", None); var = dict(rpr, vendor="Vast.ai", tier=va["tier"])
c.add_claim_fields([va, var]); s4b, _, _ = scout_io.prune_and_rederive({"rows": [va, var], "meta": {}}, {"rows": []}, files=[])
assert [r["region"] for r in s4b["rows"]] == ["all"] and s4b["rows"][0]["in_stock"] is None  # v3.5b (Gauge a): Vast is derived now -> re-derived like RunPod
# enriched feed follows the recomputed overall row (re-joined from the pruned snapshot; in_live_feed kept)
feed = json.load(open(e.SRC + "/data/gpu_pricing/verda.json")); feed = dict(feed, records=[r for r in feed["records"] if r["gpu"] == "H100 SXM" and r["vram_gb"] == 80])
rows = [V(SP, "all", True, old), V(SP, "FIN-01", True, old), V(OD, "all", True), V(OD, "FIN-02", True)]; c.add_claim_fields(rows)
sn = {"collected_at": fmt(now), "meta": {}, "rows": rows}
en_rows, _ = e.enrich([feed], sn, None); en_rows = [dict(r, in_live_feed=True) for r in en_rows]
s5, en5, _ = scout_io.prune_and_rederive(sn, {"stats": {}, "rows": en_rows}, files=[feed])
fr = {r["tier"]: r for r in en5["rows"]}
assert fr[SP]["in_stock"] is None and not fr[SP]["available_regions"] and fr[SP]["in_live_feed"] is True
assert fr[OD]["in_stock"] is True and fr[OD]["available_regions"] == ["FIN-02"]
assert scout_io.expired_left(s5, en5) == []
# ---- 2: push_hook refuses when the latest run start has no '== exit' after it
d = tempfile.mkdtemp(); scout_io.write_latest({"collected_at": fmt(now), "meta": {}, "rows": []}, {"stats": {}, "rows": [{"vendor": "x"}]}, d)
env = dict(os.environ, SCOUT_OUT=d, SCOUT_DIR=HERE, PUSH_DRY_RUN="1", LOCK_WAIT="2"); env.pop("SCOUT_LOCK_HELD", None)
def hook(log, *a):
    open(d + "/cron.log", "w").write(log); return subprocess.run(["bash", "push_hook.sh", *a], env=env, capture_output=True, text=True, timeout=30)
p = hook("== 2026-10-30T13:00:00Z cycle start\n== exit 0\n== 2026-10-30T14:40:03Z runpod refresh start\n== 2026-10-30T14:40:19Z NOTE (Gauge QA): killed\n")
assert p.returncode == 1 and "no '== exit'" in p.stdout, p.stdout
p = hook("== 2026-10-30T13:00:00Z cycle start\n== exit 0\n== 2026-10-30T14:00:00Z runpod refresh start\nprepush ok\n== exit 0\n== NOTE x\n"); assert p.returncode == 0, p.stdout
p = hook("== 2026-10-30T14:00:00Z cycle start\n== exit 1\nskip push\n"); assert p.returncode == 1 and "not ok" in p.stdout
p = hook("== 2026-10-30T14:00:00Z cycle start\n"); assert p.returncode == 1
# ---- 4: Vast group below the feed's MIN_MARKET_OFFERS is marked held (readings kept, never invented)
assert c.feed_min_market_offers() == 5  # read from feed-src core/gpu.py
VA = lambda reg, n, m="H100 SXM": dict(vendor="Vast.ai", gpu_model=m, vram_gb=80, tier="Marketplace on-demand (verified)", region=reg, in_stock=True, offer_count=n)
vr = [VA("all", 4), VA("US", 3), VA("DE", 1), VA("all", 9, "A100 SXM"), VA("all", 5, "H100 PCIe")]
c.mark_vast_held(vr, 5)
assert all(r["feed_status"] == "held_below_min_offers" for r in vr[:3]) and all("feed_status" not in r for r in vr[3:])
assert vr[0]["in_stock"] is True and vr[0]["offer_count"] == 4
assert c.mark_vast_held([VA("all", 1)], None)[0].get("feed_status") is None  # threshold unreadable -> mark nothing
assert c.feed_min_market_offers("/nonexistent") is None and "feed_status" in c.FIELDS
assert "v3.2" in open("out/RUN_LOG.txt").read()
print("test_v32 OK")
