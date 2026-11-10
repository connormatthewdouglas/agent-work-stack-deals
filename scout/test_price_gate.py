#!/usr/bin/env python3
"""T73 rev4: price + VRAM join gate for Hyperstack (pricebook), Novita and Thunder — mocked, no network, no keys."""
import os, sys, tempfile
os.environ["SCOUT_BACKOFF_FILE"] = tempfile.mktemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_v2 as c, enrich_feed_v2 as e
c.SECOND_READ_MIN_GAP = 0; c.time.sleep = lambda s: None
def snap(rows):
    for v in {r["vendor"] for r in rows}: c.FIRST_READ[v] = 0
    assert c.second_reads(rows, first_read_at=0, sleep=lambda s: None) == []
    c.add_claim_fields(rows); return {"rows": rows, "meta": {}}
def enr(vendor, gpu, vram, tier, price, s):
    return e.enrich([{"vendor": vendor, "records": [dict(gpu=gpu, vram_gb=vram, tier=tier, hourly_usd=price, source_url="u", checked_at="x")]}], s, None)[0][0]
# Hyperstack: stock + live pricebook
STOCK = {"stocks": [{"region": "US-1", "stock-type": "GPU", "models": [{"model": "A100-80G-SXM4", "available": "10+"}]}]}
BOOK = [{"name": "A100-80G-SXM4", "value": "1.600000000"}, {"name": "A100-80G-SXM4-spot", "value": "1.28"}]
c._hs_get = lambda url=None: BOOK if url == c.HS_PRICE_URL else STOCK
s = snap(c.hyperstack())
assert enr("Hyperstack", "A100 SXM", 80, "On-demand", 1.60, s)["in_stock"] is True
assert enr("Hyperstack", "A100 SXM", 80, "On-demand", 1.70, s)["in_stock"] is None        # price mismatch -> empty
assert enr("Hyperstack", "A100 SXM", 40, "On-demand", 1.60, s)["in_stock"] is None        # VRAM mismatch -> empty
assert enr("Hyperstack", "A100 SXM", 80, "On-demand", 1.604, s)["in_stock"] is True       # within $0.005
def nobook(url=None):
    if url == c.HS_PRICE_URL: raise OSError("pricebook down")
    return STOCK
c._hs_get = nobook; s = snap(c.hyperstack())
assert all(r["price_usd_hr"] is None for r in s["rows"])
assert enr("Hyperstack", "A100 SXM", 80, "On-demand", 1.60, s)["in_stock"] is None        # no live price -> empty
assert "INFERRED" in c.HS_NOTE and "On-demand" in c.HS_NOTE
# Novita
P = lambda price: {"data": [{"name": "RTX 4090 24GB", "availableDeploy": False, "inventoryState": "none", "regions": ["US-01"], "price": price, "billingMethods": ["onDemand"]}]}
c._nv_get = lambda: P("67000"); s = snap(c.novita())
assert enr("Novita AI", "RTX 4090", 24, "On-demand", 0.67, s)["in_stock"] is False
assert enr("Novita AI", "RTX 4090", 24, "On-demand", 0.69, s)["in_stock"] is None         # price mismatch -> empty
assert enr("Novita AI", "RTX 4090", 48, "On-demand", 0.67, s)["in_stock"] is None         # VRAM mismatch -> empty
# Thunder
ST = {"specs": {"h100_x1": "available", "a100xl_x1": "unavailable"}}; PR = {"pricing": {"h100_x1": 3.2, "a100xl_x1": 1.09}}
c._tc_get = lambda p: ST if p == "/v2/status" else PR; s = snap(c.thunder())
assert enr("Thunder Compute", "H100 SXM", 80, "On-demand", 3.20, s)["in_stock"] is True
assert enr("Thunder Compute", "A100", 80, "On-demand", 1.09, s)["in_stock"] is False
assert enr("Thunder Compute", "H100 SXM", 80, "On-demand", 2.99, s)["in_stock"] is None   # price mismatch -> empty
assert enr("Thunder Compute", "A100", 40, "On-demand", 1.09, s)["in_stock"] is None       # VRAM mismatch -> empty
print("test_price_gate OK")
