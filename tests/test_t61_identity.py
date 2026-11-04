"""T61: sourced identity/memory registry; usable memory never silently falls back to nominal."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import gpu_identity as gi  # noqa: E402
from mcp_server import server as s  # noqa: E402

DATA = json.loads((ROOT / "core/assets/gpu_identity.json").read_text())


def test_every_known_value_has_a_source():
    for m in DATA["models"]:
        for k in ("nominal_memory", "usable_memory"):
            v = m[k]
            if v["value"] != "unknown":
                assert v["source_url"].startswith("https://") and v["quote"], (m["model"], k)
    for name, a in DATA["amd_identity_specs"].items():
        assert a["source_url"].startswith("https://www.amd.com/") and a["quotes"]


def test_usable_unknown_everywhere_and_never_nominal():
    for m in DATA["models"]:
        ident = gi.identity(m["model"])
        assert ident["usable_memory"]["value"] == "unknown" and ident["usable_memory"]["gb"] is None


def test_unknown_nominal_stays_unknown():
    for m in ("B300", "GB300", "T4", "V100", "H100 PCIe"):
        assert gi.identity(m)["nominal_memory"]["gb"] is None
    assert gi.identity("A100")["nominal_memory"]["gb"] is None  # '40GB or 80GB' is not one figure
    assert "40GB and 80GB" in gi.identity("A100 SXM")["note"]


def test_aliases_do_not_collide():
    assert gi.identity("H100 NVL")["nominal_memory"]["gb"] == 94 and gi.identity("H100 NVLink")["nominal_memory"]["gb"] == 80
    assert gi.identity("L40")["model"] == "L40" and gi.identity("L40S")["model"] == "L40S"
    assert gi.identity("A10")["model"] == "A10" and gi.identity("A10")["nominal_memory"]["gb"] == 24
    assert gi.identity("RTX PRO 6000")["model"] != gi.identity("RTX 6000 Ada")["model"]
    assert gi.identity("MI250") is None and gi.identity("Nonexistent") is None


def test_amd_tbp_not_tdp():
    for m, gb, tbp in (("MI325X", 256, "1000W"), ("MI350X", 288, "1000W"), ("MI355X", 288, "1400W")):
        i = gi.identity(m)
        assert i["nominal_memory"]["gb"] == gb and i["amd_identity"]["manufacturer"] == "AMD"
        assert i["amd_identity"]["tdp"].startswith("unknown") and tbp in i["amd_identity"]["tdp"]
        assert "TBP" in i["amd_identity"]["power_note"]


def test_filter_reports_unknown():
    f = gi.filter_usable([{"gpu": "H100 SXM", "vram_gb": 80}, {"gpu": "Mystery", "vram_gb": 999}], 40)
    assert f["matched"] == [] and len(f["unknown"]) == 2 and "nominal" in f["note"]


def test_mcp_usable_filter_and_identity():
    o = s.compare_gpu_prices("H100", min_usable_memory_gb=40)
    assert "error" not in o, o
    assert o["results"] == [] and o["usable_memory_filter"]["matched"] == 0 and o["usable_memory_filter"]["unknown"] > 0
    assert "not used as usable" in o["summary"]
    full = s.compare_gpu_prices("H100", mode="full")
    assert full["model_identity"]["usable_memory"]["value"] == "unknown"
    plain = s.compare_gpu_prices("H100")
    assert plain["results"] and "usable_memory_filter" not in plain
    assert s.compare_gpu_prices("H100", min_usable_memory_gb=-1)["error"]
