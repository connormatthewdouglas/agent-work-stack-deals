#!/usr/bin/env python3
"""T73: Hyperstack stock collector — mocked API only (no network, no key)."""
import os, sys, json, tempfile, inspect
os.environ["SCOUT_BACKOFF_FILE"] = tempfile.mktemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_v2 as c, enrich_feed_v2 as e, refresh_multi as m, scout_io
DOC = {"stocks": [
  {"region": "CANADA-1", "stock-type": "GPU", "models": [
    {"model": "H100-80G-PCIe", "available": "10+"}, {"model": "H100-80G-SXM5", "available": "0"},
    {"model": "A100-80G-PCIe-spot", "available": "4"}, {"model": "A100-80G-PCIe", "available": "1"},
    {"model": "H100-80G-PCIe-NVLink", "available": "?"},          # unparseable -> unknown
    {"model": "H100-PCIe", "available": "5"},                      # no VRAM in name -> ambiguous -> unknown
    {"model": "A100-40G-PCIe", "available": "5"}]},                # wrong VRAM -> ignored
  {"region": "US-1", "stock-type": "GPU", "models": [{"model": "A100-80G-SXM4", "available": "10+"}, {"model": "H100-80G-SXM5", "available": "0"}]}]}
cnt = c._hs_count(DOC)
assert cnt[("H100 PCIe", 80, "On-demand")] == {"CANADA-1": 10}
assert cnt[("H100 SXM", 80, "On-demand")] == {"CANADA-1": 0, "US-1": 0}
assert cnt[("A100 PCIe", 80, "Spot VM")] == {"CANADA-1": 4}
assert ("H100 NVLink", 80, "On-demand") not in cnt and not any(k[1] != 80 for k in cnt)
c._hs_get = lambda url=None: [] if url == c.HS_PRICE_URL else DOC
rows = c.hyperstack()
allr = {(r["gpu_model"], r["tier"]): r for r in rows if r["region"] == "all"}
assert allr[("H100 SXM", "On-demand")]["in_stock"] is False and allr[("H100 PCIe", "On-demand")]["in_stock"] is True
assert ("H100 NVLink", "On-demand") not in allr  # unknown stays unknown: no row
assert all(r["source_url"] == c.HS_DOCS and "nexgencloud" not in r["source_url"] for r in rows)
assert {r["region"] for r in rows if r["gpu_model"] == "H100 SXM"} == {"all"}  # zero regions not emitted
# two reads: confirmed only when the second read still shows stock
c.FIRST_READ["Hyperstack"] = 0
DOC2 = json.loads(json.dumps(DOC)); DOC2["stocks"][0]["models"][3]["available"] = "0"  # A100 PCIe on-demand gone
c._hs_get = lambda url=None: [] if url == c.HS_PRICE_URL else DOC2; c.SECOND_READ_MIN_GAP = 0; c.time.sleep = lambda s: None
log = c.second_reads(rows, first_read_at=0, sleep=lambda s: None)
assert log == [], log
reg = {(r["gpu_model"], r["tier"], r["region"]): r for r in rows}
assert reg[("H100 PCIe", "On-demand", "CANADA-1")]["confirmed"] is True
assert reg[("A100 PCIe", "On-demand", "CANADA-1")]["confirmed"] is False
assert reg[("H100 SXM", "On-demand", "all")]["zero_capacity_two_reads"] is True
assert "Hyperstack" in c.SECOND_READ_GAPS
# second-read failure: Hyperstack rows dropped, gap meta still written
meta = {}; out = c.after_second_reads(rows + [{"vendor": "X"}], meta, [{"source": "Hyperstack", "key": "Hyperstack", "error": "URLError"}])
assert out == [{"vendor": "X"}] and "second_read_gap_s" in meta and meta["nonfatal_errors"]["Hyperstack"]
# expiry: region claims 1h, overall rows capped 1h (derived vendor)
c.add_claim_fields(rows)
assert "Hyperstack" in c.DERIVED_VENDORS and "Hyperstack" in scout_io.DERIVED_VENDORS
# join key: On-demand + Spot VM join; Reservation never
assert e.key("Hyperstack", "H100 SXM", 80, "On-demand")[3] == "On-demand" and e.key("Hyperstack", "A100 PCIe", 80, "Spot VM")[3] == "Spot VM"
assert e.key("Hyperstack", "H100 SXM", 80, "Reservation (starting from)")[3].startswith("?")
# key: env first, file second; stripped; errors never contain it
os.environ["HYPERSTACK_API_KEY"] = "envkey\n"; assert c._hs_key() == "envkey"
del os.environ["HYPERSTACK_API_KEY"]
f = tempfile.NamedTemporaryFile("w", delete=False); f.write("filekey\n"); f.close(); c.HS_KEY_FILE = f.name; assert c._hs_key() == "filekey"
c.HS_KEY_FILE = "/nonexistent"
# failure never fails the cycle; backoff applies; message has no key
import importlib; c2 = importlib.reload(c); c2.HS_KEY_FILE = f.name
def boom(*a, **k): raise c2.urllib.error.HTTPError(c2.HS_URL, 403, "Forbidden", {"api_key": "filekey"}, None)
c2.urllib.request.urlopen = boom
try: c2.with_backoff("Hyperstack", c2.hyperstack); raise AssertionError("should raise")
except RuntimeError as ex: assert "filekey" not in str(ex) and "403" in str(ex)
assert json.load(open(os.environ["SCOUT_BACKOFF_FILE"]))["Hyperstack"] == 1
src = inspect.getsource(c2._hs_get); assert "timeout=HS_TIMEOUT" in src and c2.HS_TIMEOUT == 20
msrc = inspect.getsource(m.collect); assert 'c.with_backoff("Hyperstack", c.hyperstack)' in msrc
assert 'with_backoff("Hyperstack", hyperstack)' in open("collect_v2.py").read()
os.unlink(f.name); print("test_hyperstack OK")
