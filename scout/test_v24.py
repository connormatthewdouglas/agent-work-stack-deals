"""Offline tests v2.4 (Clore asserts updated for v2.5 unrented_servers): v2.3 null-region test + Lambda parsing (no network, no key)."""
import io, json, os, tempfile, runpy
runpy.run_path("test_v23.py")
import collect_v2 as c
fake = {"data": {
  "gpu_1x_a100_sxm4": {"instance_type": {"gpu_description": "A100 (40 GB SXM4)", "price_cents_per_hour": 199}, "regions_with_capacity_available": [{"name": "us-east-1"}]},
  "gpu_1x_h100_sxm5": {"instance_type": {"gpu_description": "H100 (80 GB SXM5)", "price_cents_per_hour": 429}, "regions_with_capacity_available": []},
  "gpu_8x_h100_sxm5": {"instance_type": {"gpu_description": "H100 (80 GB SXM5)", "price_cents_per_hour": 3192}, "regions_with_capacity_available": []}}}
class R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
seen = []
def fake_open(req, timeout=None):
    seen.append((req.get_method(), req.full_url)); return R(json.dumps(fake).encode())
c.urllib.request.urlopen = fake_open
env = tempfile.NamedTemporaryFile("w", delete=False); env.write("LAMBDA_API_KEY=testkey\n"); env.close()
rows = c.lambda_(env.name); os.unlink(env.name)
assert seen == [("GET", c.LBASE)], seen  # read-only, single endpoint
a40 = [r for r in rows if r["gpu_model"] == "A100 SXM" and r["vram_gb"] == 40]
assert [(r["region"], r["in_stock"]) for r in a40] == [("all", True), ("us-east-1", True)], a40
h = [r for r in rows if r["gpu_model"] == "H100 SXM" and r["region"] == "all"]
assert sorted((r["tier"], r["in_stock"], r["price_usd_hr"]) for r in h) == [("On-demand instance (1x GPU)", False, 4.29), ("On-demand instance (8x GPU)", False, 3.99)], h
assert all(r["source"] == "authenticated vendor API (not publicly reproducible)" and r["availability_refresh"] == "4h" for r in rows)
assert "testkey" not in json.dumps(rows)
assert not any(r["gpu_model"] == "A100 PCIe" for r in rows)  # unlisted type -> no row (unknown), not false
# Clore: exact name + VRAM; rented excluded; 4090 D / 23 GB not coerced
c.get = lambda url, data=None: {"servers": [
  {"rented": False, "specs": {"gpu": "2x NVIDIA A100SXM440GB", "gpuram": 40, "net": {"cc": "DE"}}},
  {"rented": True, "specs": {"gpu": "1x NVIDIA A100SXM440GB", "gpuram": 40, "net": {"cc": "US"}}},
  {"rented": False, "specs": {"gpu": "1x NVIDIA GeForce RTX 4090 D", "gpuram": 24, "net": {"cc": "CN"}}},
  {"rented": False, "specs": {"gpu": "1x NVIDIA GeForce RTX 4090", "gpuram": 23, "net": {"cc": "CN"}}}]}
cr = {(r["gpu_model"], r["region"]): r for r in c.clore()}
assert cr[("A100 SXM", "all")]["in_stock"] is None and cr[("A100 SXM", "all")]["unrented_servers"] == 1 and ("A100 SXM", "US") not in cr
assert cr[("RTX 4090", "all")]["in_stock"] is False and cr[("RTX 4090", "all")]["unrented_servers"] == 0
assert "not listed" in cr[("H100 NVL", "all")]["observation"]
print("test_v24 OK")
