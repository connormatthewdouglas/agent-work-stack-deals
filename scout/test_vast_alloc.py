"""Vast wider-gpu rows are one per allocation size. The live file was wider_gpu.py (not wider_gpu.py.vastalloc_staged)."""
import wider_gpu as w

def offer(name, gb, n_gpu, price, mid):
    return {"gpu_name": name, "gpu_ram": gb * 1024, "num_gpus": n_gpu, "dph_total": price * n_gpu, "machine_id": mid}

# 1x at $1 and $3 per GPU (median 2) on 6 machines; 8x at $10 per GPU on 6 other machines; a thin 4x on 2 machines.
offers = []
offers += [offer("B200", 180, 1, p, i) for i, p in enumerate([1, 3, 1, 3, 1, 3], start=1)]
offers += [offer("B200", 180, 8, 10, 100 + i) for i in range(6)]
offers += [offer("B200", 180, 4, 4, 200 + i) for i in range(2)]
w.c.get = lambda url, data=None: {"offers": offers}
rows = {(r["gpu_count"], r["gpu_model"]): r for r in w.vast(5)}
one, eight, four = rows[(1, "B200")], rows[(8, "B200")], rows[(4, "B200")]
assert one["price_usd_hr"] == 2.0 and one["offer_count"] == 6 and one["distinct_machines"] == 6 and one["feed_status"] is None
assert one["tier"] == "Marketplace on-demand (verified) (1x GPU)" and one["min_gpus"] == 1
assert eight["price_usd_hr"] == 10.0 and eight["gpu_count"] == 8 and eight["min_gpus"] == 8 and eight["offer_count"] == 6
assert eight["tier"] == "Marketplace on-demand (verified) (8x GPU)" and "offers on 6 distinct machine_id" in eight["availability_note"]
assert four["feed_status"] == "held_below_min_offers" and four["price_usd_hr"] is None and four["gpu_count"] == 4
assert four["price_basis"] is None and "price withheld" in four["availability_note"]
# 1-GPU medians are not pulled toward the 8-GPU whole-server price
assert one["price_usd_hr"] != eight["price_usd_hr"]
print("test_vast_alloc OK")
