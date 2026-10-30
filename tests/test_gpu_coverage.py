"""0.3.51: wider GPU model coverage (Bjorn) and /coverage/."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "hosted" / "src"), str(ROOT / "scripts")]

from core.gpu import FAMILIES, family_of  # noqa: E402
from core.deals import compare_gpu_prices, DealError  # noqa: E402
from core.cost_per_job import estimate_job_cost, JobCostError  # noqa: E402
from core import eligibility as EL  # noqa: E402
import watch as W  # noqa: E402
import coverage_page  # noqa: E402

BASE = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
NAMES = [("B200 SXM", 192), ("B300 SXM", 288), ("MI300X", 192), ("MI250", 128), ("L4", 24), ("L40", 48), ("L40S", 48),
         ("A10", 24), ("A10G", 24), ("A100", 80), ("A40", 48), ("A4000", 16), ("V100 SXM2", 32), ("V100 PCIe", 16),
         ("RTX 6000 Ada", 48), ("RTX A6000", 48), ("RTX A4000", 16), ("RTX PRO 6000", 96), ("T4", 16), ("GH200", 96),
         ("H100 SXM", 80), ("H100 NVL", 94), ("H200 NVL", 141), ("GB300 SXM", 288), ("Quadro RTX 6000", 24), ("V100", 16), ("RTX 3090", 24), ("RTX 4090", 24)]


def _doc():
    r0 = next(r for r in BASE["rates"] if r["gpu"] == "A100 SXM" and r["tier_class"] == "on-demand")
    rates = []
    for i, (g, v) in enumerate(NAMES):
        r = copy.deepcopy(r0)
        r.update(gpu=g, vram_gb=v, advertiser=f"V{i}", deal_id=f"d{i}", price_usd=1 + i / 10, hourly_equiv_usd=1 + i / 10,
                 availability={"status": "unknown", "in_stock": None, "checked_at": None})
        r.pop("region", None)
        rates.append(r)
    return dict(BASE, rates=rates, held_stale=[])


def _gpus(out):
    return sorted({(r["gpu"], r["vram_gb"]) for r in out["results"]})


@pytest.mark.parametrize("slug", ["b200", "b300", "gh200", "mi300x", "mi250", "l4", "a10", "a10g", "a40", "rtx-6000-ada",
                                  "t4", "v100", "rtx-pro-6000", "rtx-a4000", "h200-nvl", "h100-nvl", "l40s", "l40",
                                  "rtx-a6000", "rtx-3090", "rtx-4090", "h200"])
def test_family_exists(slug):
    assert slug in FAMILIES


@pytest.mark.parametrize("gpu,fam", [("L4", "l4"), ("L4 24GB", "l4"), ("L40", "l40"), ("L40S", "l40s"), ("A10", "a10"),
                                     ("A100 SXM", "a100"), ("A10G", "a10g"), ("A40", "a40"), ("H100 NVL", "h100-nvl"),
                                     ("H100 NVLink", "h100"), ("H100 SXM", "h100"), ("H200 NVL", "h200-nvl"),
                                     ("RTX A4000", "rtx-a4000"), ("RTX PRO 6000", "rtx-pro-6000"),
                                     ("RTX 6000 Ada", "rtx-6000-ada"), ("Quadro RTX 6000", "quadro-rtx-6000"), ("Quadro RTX 6000 24GB", "quadro-rtx-6000"), ("GB300 SXM 288GB", "gb300"), ("B300 SXM", "b300"), ("V100 16GB", "v100"), ("B200 SXM 192GB", "b200"),
                                     ("V100 PCIe 16GB", "v100"), ("MI300X 192GB", "mi300x"), ("MI250X", None)])
def test_family_collisions(gpu, fam):
    assert family_of(gpu) == fam


@pytest.mark.parametrize("q,want", [
    ("L4", [("L4", 24)]), ("A10", [("A10", 24)]), ("A10G", [("A10G", 24)]), ("A40", [("A40", 48)]),
    ("B200 SXM 192GB", [("B200 SXM", 192)]), ("MI300X 192GB", [("MI300X", 192)]), ("T4", [("T4", 16)]),
    ("V100 PCIe 16GB", [("V100 PCIe", 16)]), ("V100 SXM2 32GB", [("V100 SXM2", 32)]),
    ("RTX 6000 Ada 48GB", [("RTX 6000 Ada", 48)]), ("A6000", [("RTX A6000", 48)]),
    ("H100 SXM 80GB", [("H100 SXM", 80)]), ("H100 SXM5 80GB", [("H100 SXM", 80)]), ("H100 NVL", [("H100 NVL", 94)]),
    ("GH200", [("GH200", 96)]), ("GB300 SXM 288GB", [("GB300 SXM", 288)]),
    ("Quadro RTX 6000 24GB", [("Quadro RTX 6000", 24)]), ("RTX 6000 Ada", [("RTX 6000 Ada", 48)]),
    ("RTX PRO 6000", [("RTX PRO 6000", 96)]), ("V100 16GB", [("V100", 16), ("V100 PCIe", 16)]), ("B300 SXM", [("B300 SXM", 288)]), ("RTX PRO 6000 96GB", [("RTX PRO 6000", 96)])])
def test_compare_accepts_new_models(q, want):
    assert _gpus(compare_gpu_prices(_doc(), q, 25)) == want


@pytest.mark.parametrize("q", ["Z999", "H300", "MI400X", "L4 48GB"])
def test_unknown_is_not_found(q):
    with pytest.raises(DealError) as e:
        compare_gpu_prices(_doc(), q, 10)
    assert getattr(e.value, "code", "not_found") == "not_found"
    with pytest.raises(W.WatchError):
        W.check_known_gpu(_doc(), {"gpu": q})


@pytest.mark.parametrize("q", ["L4", "A10", "MI300X", "B200", "T4", "H100 SXM 80GB"])
def test_watch_and_eligibility_accept(q):
    W.check_known_gpu(_doc(), {"gpu": q})
    c = EL.normalize(gpu=q)
    hits = {r["gpu"] for r in _doc()["rates"] if set(c["gpu"]) <= set(EL._tokens(r["gpu"]))}
    assert hits and all(family_of(h) == family_of(next(iter(hits))) for h in hits)


def test_estimate_l4_excludes_l40():
    out = estimate_job_cost(_doc(), "L4", 1, job_hours=1)
    gpus = {o["gpu"] for o in out.get("options") or out.get("results") or []}
    assert gpus == {"L4"}
    with pytest.raises(JobCostError):
        estimate_job_cost(_doc(), "Z999", 1, job_hours=1)


def test_coverage_layers_separate():
    survey = {"surveyed_at": "2026-10-30T22:11:00Z", "sources": {}, "not_surveyed": [],
              "lists": {"B300": {"RunPod": "listed"}, "B200": {"Oblivus": "listed, no sourced price"}}}
    doc = _doc()
    doc["rates"] = [r for r in doc["rates"] if r["gpu"] != "B300 SXM"]
    cov = coverage_page.build(doc, survey=survey)
    by = {m["model"]: m for m in cov["models"]}
    assert by["B300"]["status"] == "not yet tracked" and by["B300"]["vendors"] == {}
    assert by["B300"]["vendor_lists"] == {"RunPod": "listed"}
    assert "Oblivus" not in by["B200"]["vendors"] and by["B200"]["vendor_lists"]["Oblivus"] == "listed, no sourced price"
    assert by["L4"]["vendors"] and "L4" not in by["L40"]["variants"]
    assert not any("affiliate" in json.dumps(m) or "commission" in json.dumps(m) for m in cov["models"])


def test_coverage_json_built_from_feed():
    cov = json.loads((ROOT / "api" / "v1" / "coverage.json").read_text())
    feed = {(family_of(r["gpu"]) or r["gpu"], r["advertiser"]) for r in BASE["rates"]}
    cells = {(m["family"] or m["model"], v) for m in cov["models"] for v in m["vendors"]}
    assert cells == feed
    assert all(m["vendors"] == {} for m in cov["models"] if m["status"] == "not yet tracked")
