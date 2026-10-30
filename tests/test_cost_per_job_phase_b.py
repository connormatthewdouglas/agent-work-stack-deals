"""T20 Phase B: published-benchmark throughput fallback. Never invents, skips flagged figures, user input wins."""
import pytest

from core import throughput
from core.cost_per_job import JobCostError, estimate_job_cost
from tests.test_cost_per_job import _row

D = {"rates": [_row("V", 2.0, gpu="H100 SXM"), _row("V", 1.0, gpu="RTX 4090"), _row("V", 1.5, gpu="L40S"),
               _row("V", 2.0, gpu="H100 PCIe")]}


def test_uses_single_gpu_figure():
    out = estimate_job_cost(D, "H100 SXM", 1, work_units=9081.51 * 3600, workload="BERT-Large inference")
    assert out["throughput_basis"] == "published_benchmark"
    s = out["throughput_source"]
    assert s["derived"] is False and s["quote"] == "Samples per second: 9081.51" and s["date"] == "2024-03-27"
    assert s["url"].startswith("https://github.com/mlcommons/") and s["benchmark"] and s["caveats"]
    assert out["job_hours"] == pytest.approx(1.0) and out["citations"] == [s["url"]]


def test_multi_gpu_figure_used_only_on_its_measured_gpu_count():
    """T46: an 8-GPU result prices an 8-GPU job (measured config), never a 1-GPU job."""
    out = estimate_job_cost(D, "L40S", 8, work_units=3481.53 * 3600, workload="llama2-70b inference")
    s = out["throughput_source"]
    assert s["derived"] is False and s["reported_gpu_count"] == 8
    assert "measured on 8 GPUs" in s["caveats"][0] and not any("linear scaling" in c for c in s["caveats"])
    assert out["job_hours"] == pytest.approx(1.0)


@pytest.mark.parametrize("gpu,n,wl,measured", [("H100 SXM", 1, "llama2-70b", 8), ("H100 SXM", 4, "llama2-70b", 8),
                                               ("H100 SXM", 8, "resnet50", 1), ("L40S", 1, "resnet50", 8)])
def test_t46_configuration_mismatch_is_not_measured(gpu, n, wl, measured):
    with pytest.raises(JobCostError) as e:
        estimate_job_cost(D, gpu, n, work_units=1e6, workload=wl)
    m = e.value.message
    assert e.value.code == "not_found" and "missing: throughput" in m and "configuration mismatch" in m
    assert f"measured on {measured}x" in m and f"gpus_per_job={measured}" in m  # actionable follow-up
    assert "job_hours" in m and "throughput_units_per_gpu_hour" in m


def test_t46_user_benchmark_still_prices_any_gpu_count():
    out = estimate_job_cost(D, "H100 SXM", 1, work_units=1e6, throughput_units_per_gpu_hour=1e6, workload="llama2-70b")
    assert out["throughput_basis"] == "user_supplied" and out["job_hours"] == pytest.approx(1.0)


def test_t46_ambiguous_configurations_not_chosen(tmp_path):
    import json
    from pathlib import Path
    d = json.loads((Path(__file__).resolve().parents[1] / "data" / "gpu_throughput.json").read_text())
    f = next(x for x in d["figures"] if x["gpu"] == "H100" and x["variant"] == "SXM 80GB" and x["workload"] == "resnet50")
    g = json.loads(json.dumps(f))
    g["id"] += "-server"
    g["conditions"]["scenario"] = "Server"
    d["figures"].append(g)
    p = tmp_path / "t.json"
    p.write_text(json.dumps(d))
    fig, why = throughput.lookup("H100 SXM 80GB", "resnet50", path=p, gpus=1)
    assert fig is None and "more than one eligible figure" in why and "Offline" in why and "Server" in why


def test_skips_flagged_reference_figure_4090_sdxl():
    with pytest.raises(JobCostError) as e:
        estimate_job_cost(D, "RTX 4090", 1, work_units=100, workload="SDXL")
    assert e.value.code == "not_found" and "missing: throughput for RTX 4090" in e.value.message
    assert "reference" in e.value.message


def test_skips_sparsity_spec_and_open_division_gap():
    for gpu, wl in [("H100 SXM", "peak_spec"), ("RTX 4090", "llama2-70b")]:
        with pytest.raises(JobCostError) as e:
            estimate_job_cost(D, gpu, 1, work_units=1, workload=wl)
        assert "missing: throughput" in e.value.message


@pytest.mark.parametrize("wl", ["fine-tune Llama 2 70B LoRA", "BERT-Large training", "train resnet50"])
def test_training_never_resolves(wl):
    with pytest.raises(JobCostError) as e:
        estimate_job_cost(D, "H100 SXM", 8, work_units=1000, workload=wl)
    assert "missing: throughput for H100 SXM" in e.value.message


def test_user_override_wins():
    out = estimate_job_cost(D, "H100 SXM", 1, work_units=100, throughput_units_per_gpu_hour=50, workload="bert-large")
    assert out["throughput_basis"] == "user_supplied" and out["throughput_source"] is None
    assert out["job_hours"] == pytest.approx(2.0)
    out = estimate_job_cost(D, "H100 SXM", 1, job_hours=3, workload="bert-large")
    assert out["throughput_basis"] == "user_supplied" and out["job_hours"] == 3


def test_missing_gap_and_ambiguous_variant():
    with pytest.raises(JobCostError) as e:  # A100 sdxl: documented gap
        estimate_job_cost(D, "A100 SXM", 1, work_units=1, workload="sdxl")
    assert "missing: throughput for A100 SXM" in e.value.message
    with pytest.raises(JobCostError) as e:  # bare H100: SXM/PCIe/NVL figures differ, never pick one
        estimate_job_cost(D, "H100", 1, work_units=1, workload="bert-large")
    assert "missing: throughput for H100" in e.value.message and "ambiguous" in e.value.message


def test_figure_found_but_no_work_units():
    with pytest.raises(JobCostError) as e:
        estimate_job_cost(D, "H100 SXM", 1, workload="resnet50")
    assert "missing: work_units" in e.value.message


def test_dataset_values_copied_not_computed():
    fig, _ = throughput.lookup("A100 SXM 80GB", "resnet50")
    assert fig["throughput_source"]["reported_value"] == 42379.3
    assert fig["value_per_gpu_hour"] == pytest.approx(42379.3 * 3600)
