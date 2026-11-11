"""P44: importer KEEP whitelist carries Scout vendor-native ids; missing stays null."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("imp", ROOT / "scripts/import_scout_availability.py")
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)


def test_keep_includes_vendor_native_ids_and_copies_recorded_values():
    assert "machine_ids" in imp.KEEP and "listing_ids" in imp.KEEP
    src = {"vendor": "Vast.ai", "gpu": "H100 SXM", "vram_gb": 80, "tier": "Marketplace on-demand (verified)",
           "region": "all", "in_stock": True, "machine_ids": [111, 222],
           "available_regions_detail": [{"region": "US", "machine_ids": [111]}]}
    row = {k: src.get(k) for k in imp.KEEP}
    assert row["machine_ids"] == [111, 222] and row["listing_ids"] is None
    assert row["available_regions_detail"][0]["machine_ids"] == [111]


def test_missing_ids_stay_null_and_are_not_invented():
    row = {k: {"vendor": "Civo", "gpu": "H100 SXM", "tier": "On-demand"}.get(k) for k in imp.KEEP}
    assert row["machine_ids"] is None and row["listing_ids"] is None
