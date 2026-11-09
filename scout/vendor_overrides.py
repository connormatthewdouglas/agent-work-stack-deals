"""Vendor overrides loader (additive fields only; schema 3.2 unchanged)."""
import json, os

# ---- Vendor overrides (CloudRift 2026-11-04): additive fields, applied at row-build time so they survive every refresh ----
VENDOR_OVERRIDES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor_overrides.json")
PRICE_FIELDS = ("hourly_usd", "price_usd", "price_usd_hr")
def load_vendor_overrides(path=None):
    if os.environ.get("LANTERN_VENDOR_OVERRIDES") == "off": return []  # legacy tests (T73/T113) check pre-override logic
    try:
        with open(path or VENDOR_OVERRIDES_PATH) as f: return json.load(f).get("overrides") or []
    except FileNotFoundError: return []
def apply_vendor_overrides(row, overrides=None):
    """Feed rows (vendor/gpu/vram_gb/tier) and snapshot rows (vendor/gpu_model/vram_gb/tier) both match. Only sets listed
    fields; null_price nulls price fields that exist (never invents a value). Returns row (mutated)."""
    ov = load_vendor_overrides() if overrides is None else overrides
    for o in ov:
        m = o.get("match") or {}
        if all((row.get(k) if k != "gpu" else row.get("gpu", row.get("gpu_model"))) == v for k, v in m.items()):
            if o.get("null_price"):
                for k in PRICE_FIELDS:
                    if k in row: row[k] = None
                if "price_basis" in row: row["price_basis"] = None
            row.update(o.get("set") or {})
    return row
