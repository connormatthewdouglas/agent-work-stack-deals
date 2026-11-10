#!/usr/bin/env python3
"""T73: Novita GPU products collector — mocked API only (no network, no key)."""
import os, sys, json, tempfile, inspect, importlib
os.environ["SCOUT_BACKOFF_FILE"] = tempfile.mktemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_v2 as c, enrich_feed_v2 as e, refresh_multi as m
def P(id_, ad, inv, regs, name="RTX 4090 24GB", price="67000"):
    return {"id": id_, "name": name, "availableDeploy": ad, "inventoryState": inv, "regions": regs, "price": price, "billingMethods": ["onDemand", "spot"]}
OUT = {"data": [P("26", False, "none", ["US-01 (Dallas)"]), P("nas", False, "none", ["US-01 (Dallas)", "US-02"]), P("x", True, "high", [], name="RTX 4090D 24GB")]}
IN = {"data": [P("26", True, "normal", ["US-01 (Dallas)"]), P("nas", True, "high", ["US-01 (Dallas)", "US-02"])]}
MIX = {"data": [P("26", False, "low", ["US-01 (Dallas)"])]}  # contradictory -> unknown
assert c._nv_state(OUT)[("RTX 4090", 24)]["in_stock"] is False and len(c._nv_state(OUT)) == 1  # 4090D not matched
assert c._nv_state(IN)[("RTX 4090", 24)] == {"regions": {"US-01 (Dallas)"}, "prices": {0.67}, "in_stock": True}
assert c._nv_state(MIX)[("RTX 4090", 24)]["in_stock"] is None
c._nv_get = lambda: MIX; assert c.novita() == []  # unknown -> no row
c._nv_get = lambda: OUT; rows = c.novita()
assert [r["region"] for r in rows] == ["all"] and rows[0]["in_stock"] is False and rows[0]["source_url"] == c.NV_DOCS and rows[0]["price_usd_hr"] == 0.67
c.SECOND_READ_MIN_GAP = 0; c.time.sleep = lambda s: None; c.FIRST_READ["Novita AI"] = 0
assert c.second_reads(rows, first_read_at=0, sleep=lambda s: None) == []
assert rows[0]["zero_capacity_two_reads"] is True and rows[0]["confirmed"] is True and "Novita AI" in c.SECOND_READ_GAPS
c._nv_get = lambda: IN; rows = c.novita(); assert {r["region"] for r in rows} == {"all", "US-01 (Dallas)"}
c._nv_get = lambda: OUT; c.second_reads(rows, first_read_at=0, sleep=lambda s: None)  # stock vanished on read 2
o = [r for r in rows if r["region"] == "all"][0]; g = [r for r in rows if r["region"] != "all"][0]
assert o["in_stock"] is None and o["confirmed"] is False and g["confirmed"] is False
c.add_claim_fields(rows)
from datetime import datetime
for r in rows:
    if r.get("checked_at"):
        d = datetime.strptime(r["availability_expires_at"], "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(r["checked_at"], "%Y-%m-%dT%H:%M:%SZ")
        assert d.total_seconds() <= 3600, d
meta = {}; out = c.after_second_reads(rows, meta, [{"source": "Novita AI", "key": "Novita AI", "error": "URLError"}])
assert out == [] and "second_read_gap_s" in meta and meta["nonfatal_errors"]["Novita AI"]
assert e.key("Novita AI", "RTX 4090", 24, "On-demand")[3] == "On-demand" and e.key("Novita AI", "RTX 4090", 24, "Spot")[3].startswith("?")
os.environ["NOVITA_API_KEY"] = "envkey\n"; assert c._nv_key() == "envkey"; del os.environ["NOVITA_API_KEY"]
f = tempfile.NamedTemporaryFile("w", delete=False); f.write("filekey\n"); f.close()
c2 = importlib.reload(c); c2.NV_KEY_FILE = f.name; assert c2._nv_key() == "filekey"
def boom(*a, **k): raise c2.urllib.error.HTTPError(c2.NV_URL, 401, "Unauthorized", {"Authorization": "Bearer filekey"}, None)
c2.urllib.request.urlopen = boom
try: c2.with_backoff("Novita AI", c2.novita); raise AssertionError
except RuntimeError as ex: assert "filekey" not in str(ex) and "401" in str(ex)
assert "timeout=NV_TIMEOUT" in inspect.getsource(c2._nv_get) and c2.NV_TIMEOUT == 20 and "create" not in c2.NV_URL
assert 'c.with_backoff("Novita AI", c.novita)' in inspect.getsource(m.collect)
os.unlink(f.name); print("test_novita OK")
