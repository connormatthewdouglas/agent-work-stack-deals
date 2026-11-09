"""RTX 5090 D / Laptop stay out of the Clore RTX 5090 headline (same D guard the RTX 4090 pattern already had).

Fixture is hand-cut from the 2026-11-09 marketplace read: real ids, gpu strings, gpuram and on-demand USD, with the
other server fields dropped. Listing 117751 is "1x NVIDIA GeForce RTX 5090 D" at 32GB, the same VRAM as the desktop 5090.
"""
import copy
import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_clore", ROOT / "scripts" / "build_clore.py")
bc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bc)
FIXTURE = ROOT / "tests" / "fixtures" / "clore_rtx5090_guard.json"
AT = "2026-11-09T03:51:49Z"


def _servers():
    return json.loads(FIXTURE.read_text())["servers"]


def _ids(snap, gpu):
    return [l["id"] for l in snap["listings"] if l["gpu"] == gpu]


def test_rtx_5090_d_is_not_counted_as_rtx_5090():
    assert bc.MIN_MACHINES == 5
    assert bc.SPEC[0][1] == r"RTX 4090(?! ?D)(?! Laptop)" and bc.SPEC[1][1] == r"RTX 5090(?! ?D)(?! Laptop)"
    snap = bc.build(_servers(), AT)
    assert _ids(snap, "RTX 5090") == [124001, 123887, 124062]
    assert 117751 not in {l["id"] for l in snap["listings"]}
    assert all("Laptop" not in l["gpu_string"] and " D" not in l["gpu_string"] for l in snap["listings"] if l["gpu"] == "RTX 5090")
    s = snap["summary"]["RTX 5090"]
    assert (s["listings_total"], s["listings_available"], s["available_with_usd_price"], s["distinct_machines"]) == (3, 2, 2, 2)
    assert s["median"] == 0.3729 and s["range_on_demand"] == [0.3333, 0.4125]
    rented = next(l for l in snap["listings"] if l["id"] == 124062)
    assert rented["status"] == "rented" and rented["on_demand_usd_gpu_hr"] == 0.3542
    assert _ids(snap, "RTX 4090") == [124010, 124009]
    assert {119060, 119900, 120989, 122780}.isdisjoint({l["id"] for l in snap["listings"]})
    a = snap["summary"]["RTX 4090"]
    assert (a["listings_total"], a["available_with_usd_price"]) == (2, 2)
    assert a["median"] == 0.2978 and a["range_on_demand"] == [0.2917, 0.3038]
    assert all("Laptop" not in l["gpu_string"] and " D" not in l["gpu_string"] for l in snap["listings"] if l["gpu"] == "RTX 4090")


def test_same_vram_laptop_and_d_still_excluded():
    # Marketplace laptops and the 5090 D v2 miss the desktop gpuram filter on their own. Raise them to the desktop
    # figure so only the D / Laptop lookahead keeps them out of the headline.
    servers = copy.deepcopy(_servers())
    for s in servers:
        gpu = s["specs"]["gpu"]
        if "RTX 5090" in gpu and ("Laptop" in gpu or " D" in gpu):
            s["specs"]["gpuram"] = 32
        if "RTX 4090" in gpu and ("Laptop" in gpu or " D" in gpu):
            s["specs"]["gpuram"] = 24
    snap = bc.build(servers, AT)
    assert _ids(snap, "RTX 5090") == [124001, 123887, 124062]
    assert _ids(snap, "RTX 4090") == [124010, 124009]
    assert {117751, 122780, 120989, 119060, 119900}.isdisjoint({l["id"] for l in snap["listings"]})
    assert snap["summary"]["RTX 5090"]["available_with_usd_price"] == 2
    assert snap["summary"]["RTX 4090"]["available_with_usd_price"] == 2


def test_offline_cli_writes_the_importer_snapshot(tmp_path):
    raw = tmp_path / "clore_raw_20261109T035149.json"
    shutil.copy(FIXTURE, raw)
    out, summary = tmp_path / "clore_snapshot_latest.json", tmp_path / "clore_summary_latest.json"
    assert bc.main([str(raw), "--out", str(out), "--summary", str(summary)]) == 0
    text = out.read_bytes()
    snap = bc.build(_servers(), AT)
    assert text == (json.dumps(snap, indent=2) + "\n").encode()
    assert json.loads(text)["checked_at"] == AT and json.loads(summary.read_text())["summary"]["RTX 5090"]["median"] == 0.3729
