"""Offline tests v2.5: runs v2.4 (+v2.3), then Clore unrented_servers, enrich Clore guard + live/repo split, Vast zero-offer fallback."""
import json, runpy
runpy.run_path("test_v24.py")
import collect_v2 as c, enrich_feed_v2 as e
# S1: Clore rows never carry offer_count; unrented_servers int; in_stock = unrented_servers > 0; exact note
c.get = lambda url, data=None: {"servers": [
  {"rented": False, "specs": {"gpu": "2x NVIDIA A100SXM440GB", "gpuram": 40, "net": {"cc": "DE"}}},
  {"rented": False, "specs": {"gpu": "1x NVIDIA A100SXM440GB", "gpuram": 40, "net": {"cc": "DE"}}},
  {"rented": True, "specs": {"gpu": "1x NVIDIA GeForce RTX 4090", "gpuram": 24, "net": {"cc": "US"}}}]}
cl = c.clore()
for r in cl:
    assert "offer_count" not in r, r
    assert isinstance(r["unrented_servers"], int) and r["in_stock"] == ((None if r["region"] == "all" else True) if r["unrented_servers"] > 0 else False), r  # v3.5c: overall unknown until a region is two-read confirmed
    assert r["availability_note"] == "unrented servers (one server may hold several GPUs), any currency", r
cr = {(r["gpu_model"], r["region"]): r for r in cl}
assert cr[("A100 SXM", "all")]["unrented_servers"] == 2 and cr[("A100 SXM", "DE")]["unrented_servers"] == 2  # servers, not GPUs (3)
assert cr[("RTX 4090", "all")]["unrented_servers"] == 0 and cr[("RTX 4090", "all")]["in_stock"] is False
# enrich must not copy a Clore value into offer_count, even if a snapshot row (old/bad) carries one
bad = dict(cr[("A100 SXM", "all")], offer_count=99)
feed = [{"vendor": "Clore.ai", "records": [
  {"gpu": "A100 SXM", "vram_gb": 40, "tier": "Marketplace on-demand (host USD listings; median per GPU)", "hourly_usd": 1.0, "source_url": "x", "offer_count": 7},
  {"gpu": "RTX 4090", "vram_gb": 24, "tier": "Marketplace on-demand (host USD listings; median per GPU)", "hourly_usd": 0.5, "source_url": "x", "offer_count": 109}]}]
live = {("Clore.ai", "RTX 4090", 24, "Marketplace on-demand (host USD listings; median per GPU)")}
for snaprows in ([bad] + [r for r in cl if r["gpu_model"] != "A100 SXM"], cl):
    out, st = e.enrich(feed, {"rows": snaprows, "errors": {}}, live)
    o = {r["gpu"]: r for r in out}
    assert all(r["offer_count"] is None for r in out), out
    assert o["A100 SXM"]["unrented_servers"] == 2 and o["A100 SXM"]["in_stock"] is None  # v3.5c: no confirmed region
    assert o["RTX 4090"]["unrented_servers"] == 0 and o["RTX 4090"]["in_stock"] is False
    # S2: live vs repo-only split
    assert o["RTX 4090"]["in_live_feed"] is True and o["A100 SXM"]["in_live_feed"] is False
    assert st["current_rows_split"] == {"live_feed": 1, "repo_only": 1, "live_feed_unknown": 0}, st
    assert st["repo_only_rows"] == ["Clore.ai A100 SXM 40GB | Marketplace on-demand (host USD listings; median per GPU)"]
out, st = e.enrich(feed, {"rows": cl, "errors": {}}, None)
assert st["current_rows_split"]["live_feed_unknown"] == 2  # live feed unreadable -> unknown, not guessed
# Nice-to-have: Vast zero-offer fallback (queried, no offers -> in_stock false, offer_count 0)
c.time.sleep = lambda s: None
c.get = lambda url, data=None: {"offers": []}
c.QUERIED.clear()
vr = c.vast()
assert len(vr) == len(c.VAST) and all(r["in_stock"] is False and r["offer_count"] == 0 and r["region"] == "all" and r["vram_gb"] is None for r in vr), vr
assert set(c.QUERIED) == {"Vast.ai|" + m for m in c.VAST}
vfeed = [{"vendor": "Vast.ai", "records": [{"gpu": "H100 SXM", "vram_gb": 80, "tier": "Marketplace on-demand (verified)", "hourly_usd": 2.0, "source_url": "x"}]}]
out, _ = e.enrich(vfeed, {"rows": vr, "errors": {}, "meta": {"queried": dict(c.QUERIED)}}, set())
assert out[0]["in_stock"] is False and out[0]["offer_count"] == 0 and out[0]["availability_source"], out
out, _ = e.enrich(vfeed, {"rows": [], "errors": {"vast": "x"}, "meta": {"queried": dict(c.QUERIED)}}, set())
assert out[0]["in_stock"] is None and out[0]["offer_count"] is None  # errored run: unknown, not 0
print("test_v25 OK")
