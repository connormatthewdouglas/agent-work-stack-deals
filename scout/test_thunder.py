#!/usr/bin/env python3
"""T73: Thunder Compute collector — mocked API only (no network, no token)."""
import os, sys, json, tempfile, inspect, importlib
os.environ["SCOUT_BACKOFF_FILE"] = tempfile.mktemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_v2 as c, enrich_feed_v2 as e, refresh_multi as m
ST = {"gpu_type": {}, "specs": {"h100_x1": "available", "a100xl_x1": "unavailable", "a6000_x1": "available", "h100_x8": "available"}}
PR = {"pricing": {"h100_x1": 3.2, "a100xl_x1": 1.09, "a6000_x1": 0.35}}
st = c._tc_state(ST, PR)
assert st == {("H100 SXM", 80): {"in_stock": True, "price": 3.2}, ("A100", 80): {"in_stock": False, "price": 1.09}}
assert c._tc_state({"specs": {"h100_x1": "limited"}}, {})[("H100 SXM", 80)] == {"in_stock": None, "price": None}  # unknown stays null
assert not any("4090" in g for g, _ in c.TC_SPECS.values())
calls = []
def fake(path): calls.append(path); return {"/v2/status": ST, "/v2/pricing": PR}[path]
c._tc_get = fake; rows = c.thunder()
assert all(p in ("/v2/status", "/v2/pricing") for p in calls)  # read-only GETs only
assert {r["gpu_model"]: (r["in_stock"], r["price_usd_hr"]) for r in rows} == {"H100 SXM": (True, 3.2), "A100": (False, 1.09)}
assert all(r["region"] == "all" and r["source_url"] == c.TC_DOCS for r in rows)
c.SECOND_READ_MIN_GAP = 0; c.time.sleep = lambda s: None; c.FIRST_READ["Thunder Compute"] = 0
ST2 = {"specs": {"h100_x1": "unavailable", "a100xl_x1": "unavailable"}}
c._tc_get = lambda p: ST2 if p == "/v2/status" else PR
assert c.second_reads(rows, first_read_at=0, sleep=lambda s: None) == []
h = [r for r in rows if r["gpu_model"] == "H100 SXM"][0]; a = [r for r in rows if r["gpu_model"] == "A100"][0]
assert h["in_stock"] is None and h["confirmed"] is False and h["price_usd_hr"] == 3.2   # disagreement -> unknown, price kept
assert a["in_stock"] is False and a["zero_capacity_two_reads"] is True and "Thunder Compute" in c.SECOND_READ_GAPS
c.add_claim_fields(rows)
from datetime import datetime
for r in rows:
    d = datetime.strptime(r["availability_expires_at"], "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(r["checked_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert d.total_seconds() == 3600
meta = {}; assert c.after_second_reads(rows, meta, [{"source": "Thunder Compute", "key": "Thunder Compute", "error": "URLError"}]) == [] and "second_read_gap_s" in meta
assert e.key("Thunder Compute", "A100", 80, "On-demand")[3] == "On-demand"
c2 = importlib.reload(c)
assert not hasattr(c2, "_tc_key") and not hasattr(c2, "TC_KEY_FILE") and "thunder_api_key" not in open("collect_v2.py").read()  # rev4: no key use
seen = {}
def boom(req, timeout=None):
    seen["m"] = req.get_method(); seen["t"] = timeout; seen["auth"] = req.has_header("Authorization")
    raise c2.urllib.error.HTTPError(req.full_url, 500, "err", {}, None)
c2.urllib.request.urlopen = boom
try: c2.with_backoff("Thunder Compute", c2.thunder); raise AssertionError
except RuntimeError as ex: assert "500" in str(ex)
assert seen == {"m": "GET", "t": 20, "auth": False}  # no Bearer token sent
assert json.load(open(os.environ["SCOUT_BACKOFF_FILE"]))["Thunder Compute"] == c2.BACKOFF_429
assert 'c.with_backoff("Thunder Compute", c.thunder)' in inspect.getsource(m.collect)
print("test_thunder OK")
