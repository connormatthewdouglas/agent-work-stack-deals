"""CloudRift vendor overrides (2026-11-04): A100 SXM 80 On-demand price null + held; L40S/RTX 5090 vendor_confirmed. No network."""
import os; os.environ.pop("LANTERN_VENDOR_OVERRIDES", None)
import json, vendor_overrides as vo, collect_v2 as c, enrich_feed_v2 as e
ov = vo.load_vendor_overrides(); assert len(ov) == 3
# feed-row build (enrich)
recs = [dict(gpu=g, vram_gb=v, tier=t, hourly_usd=p, source_url="https://www.cloudrift.ai/pricing", checked_at="x")
        for g, v, t, p in (("A100 SXM", 80, "On-demand", 1.05), ("A100 SXM", 80, "1-month commitment", 0.95), ("L40S", 48, "On-demand", 0.63), ("RTX 5090", 32, "On-demand", 0.65), ("H100 SXM", 80, "On-demand", 2.0))]
out, _ = e.enrich([{"vendor": "CloudRift", "records": recs}], {"rows": [], "meta": {}}, None)
R = {(r["gpu"], r["tier"]): r for r in out}
a = R[("A100 SXM", "On-demand")]
assert a["hourly_usd"] is None and a["price_status"] == "price_on_request" and a["feed_status"] == "held_price_on_request" and "2026-11-04" in a["vendor_confirmation"]
assert R[("A100 SXM", "1-month commitment")]["hourly_usd"] == 0.95 and "price_status" not in R[("A100 SXM", "1-month commitment")]
assert ("L40S", "On-demand") not in R  # enrich only builds H100/A100/4090 rows (GPUS); tag checked at override level below
for g, v, p in (("L40S", 48, 0.63), ("RTX 5090", 32, 0.65)):
    r = vo.apply_vendor_overrides(dict(vendor="CloudRift", gpu=g, vram_gb=v, tier="On-demand", hourly_usd=p), ov); assert r["vendor_confirmed"] == "CloudRift, 2026-11-04" and r["hourly_usd"] in (0.63, 0.65)
assert "vendor_confirmed" not in R[("H100 SXM", "On-demand")]
# collector row build (survives every refresh)
c._cr_get = lambda: {"data": {"instance_types": [{"brand_short": "A100 SXM4", "variants": [{"gpu_count": 1, "vram": 80 * 2**30, "cpu_sharing_policy": "Dedicated",
    "mig_profile": None, "available_nodes": 1, "available_nodes_per_dc": {"us-east": 1}, "cost_per_hour": 105}]}]}}
rows = c.cloudrift(); assert rows and all(r["price_usd_hr"] is None and r["price_basis"] is None and r["price_status"] == "price_on_request" for r in rows)
# other vendors untouched
assert vo.apply_vendor_overrides({"vendor": "Lambda", "gpu": "A100 SXM", "vram_gb": 80, "tier": "On-demand", "hourly_usd": 1.1}, ov)["hourly_usd"] == 1.1
print("test_cloudrift_overrides OK")
