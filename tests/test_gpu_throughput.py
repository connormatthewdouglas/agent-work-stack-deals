"""Schema + evidence rules for data/gpu_throughput.json (T20 Phase B): published figures only, explicit gaps."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "data" / "gpu_throughput.json").read_text())
GPUS = {"H100", "A100", "L40S", "RTX 4090"}
UNITS = {"tokens/s", "samples/s", "images/s", "TFLOPS", "GB/s", "TB/s"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _num_in_quote(value, quote):
    nums = {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", quote)}
    return float(value) in nums


def test_header():
    assert DATA["schema"] == "lantern-works-gpu-throughput/1"
    assert ISO.match(DATA["generated_at"]) and DATA["figures"] and DATA["gaps"]


def test_figures_have_required_fields_and_evidence():
    ids = set()
    for f in DATA["figures"]:
        assert f["id"] not in ids
        ids.add(f["id"])
        assert f["gpu"] in GPUS and f["variant"] and f["workload"] and f["metric"]
        assert f["unit"] in UNITS
        assert isinstance(f["value"], (int, float)) and not isinstance(f["value"], bool) and f["value"] > 0
        assert f["source_url"].startswith("https://") and f["source_title"]
        assert ISO.match(f["retrieved_at"])
        assert f["publication_date"] is None or re.match(r"^\d{4}-\d{2}-\d{2}$", f["publication_date"])
        if f["publication_date"] is None:
            assert f["date_note"]
        assert f["quote"] and _num_in_quote(f["value"], f["quote"]), f["id"]  # value copied, not derived
        assert "gap" not in f or f["gap"] is False


def test_per_gpu_only_when_unambiguous():
    for f in DATA["figures"]:
        c = f["conditions"]
        assert isinstance(c["gpu_count"], int) and c["gpu_count"] >= 1 and c["per_gpu_note"]
        assert c["per_gpu"] == (c["gpu_count"] == 1), f["id"]
        if f["source_type"] == "mlperf_inference":
            assert c["scenario"] and c["precision"] and c["division"] == "closed"
            assert "mlcommons/inference_results_" in f["source_url"]


def test_gaps_are_explicit():
    for g in DATA["gaps"]:
        assert g["gap"] is True and g["gpu"] and g["workload"] and len(g["reason"]) > 20
        assert "value" not in g
