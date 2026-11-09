"""T113 Lambda fix: the 4h cycle must give Lambda rows a second read so rederive keeps real claims (staged)."""
import collect_v2 as c, refresh_multi as rm, scout_io, copy
from datetime import datetime, timezone, timedelta
def data(regs):
    return {"gpu_1x_h100_sxm5": {"instance_type": {"gpu_description": "H100 (80 GB SXM5)", "price_cents_per_hour": 329}, "regions_with_capacity_available": [{"name": r} for r in regs]}}
def run(r1, r2):
    reads = iter([data(r1), data(r2)]); rows = rm.lambda_first(fetch=lambda: next(reads))
    rows = [r for r in rows if r["gpu_model"] == "H100 SXM" and r["tier"].startswith("On-demand instance (1x")]
    rm.lambda_second(rows, sleep=lambda s: None); c.add_claim_fields(rows)
    snap = {"rows": rows}; scout_io.rederive_overall(snap, set(), datetime.now(timezone.utc))
    return [r for r in snap["rows"] if r["region"] == "all"][0]["in_stock"]
def test_soldout_two_reads_kept_false(): assert run([], []) is False
def test_instock_two_reads_kept_true(): assert run(["us-east-1"], ["us-east-1"]) is True
def test_flip_is_unknown(): assert run(["us-east-1"], []) is None
def test_without_second_read_is_unknown():  # documents the old bug: no second read -> nulled
    rows = rm._map_lambda(data([])); rows = [r for r in rows if r["region"] == "all"]; c.add_claim_fields(rows)
    snap = {"rows": rows}; scout_io.rederive_overall(snap, set(), datetime.now(timezone.utc)); assert snap["rows"][0]["in_stock"] is None
def test_cycle_wires_second_read(): s = open("collect_v2.py").read(); assert "lambda_second(rows)" in s and "lambda_first()" in s
if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("ok", n)
def test_wider_pro_series():
    import wider_gpu as w
    for k, v in {"NVIDIA RTX PRO 5000 Blackwell": 48, "NVIDIA RTX PRO 4000 Blackwell": 24, "NVIDIA RTX PRO 4500 Blackwell": 32}.items(): assert w.RP_NEW[k][2] == v
    old = w.c.get; w.c.get = lambda *a, **k: {"data": {"gpuTypes": [{"id": "NVIDIA RTX PRO 5000 Blackwell", "memoryInGb": 48, "secureCloud": True, "communityCloud": True, "securePrice": 0.96, "communityPrice": 0.82},
                                                                    {"id": "NVIDIA RTX PRO 4000 Blackwell", "memoryInGb": 20, "secureCloud": True, "communityCloud": False, "securePrice": 0.57, "communityPrice": 0.5}]}}
    try: rows = w.runpod()
    finally: w.c.get = old
    assert sorted((r["gpu_model"], r["vram_gb"], r["price_usd_hr"]) for r in rows) == [("RTX PRO 5000", 48, 0.82), ("RTX PRO 5000", 48, 0.96)]  # VRAM mismatch skipped; communityCloud False -> no row
if __name__ == "__main__": test_wider_pro_series(); print("ok test_wider_pro_series")
def test_t65_vast_focus_cells():
    import wider_gpu as w
    offs = [{"gpu_name": "RTX 5090", "num_gpus": 1, "gpu_ram": 32607, "dph_total": 0.5 + i / 100, "machine_id": i} for i in range(6)] + \
           [{"gpu_name": "H100 SXM", "num_gpus": 1, "gpu_ram": 81559, "dph_total": 2.0, "machine_id": 100 + i} for i in range(4)]
    old = w.c.get; w.c.get = lambda *a, **k: {"offers": offs}
    try: rows = {r["gpu_model"]: r for r in w.vast(min_machines=5)}
    finally: w.c.get = old
    assert rows["RTX 5090"]["vram_gb"] == 32 and rows["RTX 5090"]["price_usd_hr"] == 0.525 and rows["RTX 5090"].get("feed_status") is None
    assert rows["H100 SXM"]["price_usd_hr"] is None and rows["H100 SXM"]["feed_status"] == "held_below_min_offers"  # 4 machines < 5: held
if __name__ == "__main__": test_t65_vast_focus_cells(); print("ok test_t65_vast_focus_cells")
def test_t65_oblivus_listed():
    import wider_gpu as w
    pg = "<p>RTX 4090</p><p>12 vCPU 70GB</p><p>On-Demand: $0.64/hr</p><p>H200 141GB SXM5</p><p>224 vCPU</p><p>On-Demand: $3.99/hr</p>"
    assert w.parse_obl_pricing(pg) == {"RTX 4090": (0.64, "On-Demand: $0.64/hr"), "H200 141GB SXM5": (3.99, "On-Demand: $3.99/hr")}
    av = "<h2>GPU Availability</h2><table><tr><th>GPU</th><th>MON1</th><th>OSL1</th></tr><tr><td>RTX 4090</td><td>0</td><td>3</td></tr><tr><td>H200 141GB SXM5</td><td>0</td><td>0</td></tr></table>"
    old = w.c._get_text
    def run(avpage, pricing=pg):
        def g(u):
            if u == w.OBL_PRICING_URL: return pricing
            if avpage is None: raise IOError("down")
            return avpage
        w.c._get_text = g
        try: return {r["gpu_model"]: r for r in w.oblivus_listed(ts="t")}
        finally: w.c._get_text = old
    rs = run(av)
    assert rs["RTX 4090"]["availability_status"] == "in_stock" and rs["RTX 4090"]["in_stock"] is True and "MON1: 0, OSL1: 3" in rs["RTX 4090"]["availability_reason_detail"]
    assert rs["RTX 4090"]["price_usd_hr"] == 0.64  # restocked row keeps its price
    h = [r for k, r in rs.items() if k.startswith("H200")][0]
    assert h["availability_status"] == h["availability_reason"] == "out_of_stock" and h["in_stock"] is False and h["price_usd_hr"] == 3.99
    rs = run(None)
    assert len(rs) == 2 and all(r["availability_status"] == "unknown" and r["in_stock"] is None and r["price_usd_hr"] for r in rs.values())
    assert all(r["source_url"] == w.OBL_PRICING_URL for r in rs.values())
    assert run(av, "<p>RTX 4090</p><p>x</p><p>Contact sales</p>") == {}  # price gone -> skipped
if __name__ == "__main__": test_t65_oblivus_listed(); print("ok test_t65_oblivus_listed")
