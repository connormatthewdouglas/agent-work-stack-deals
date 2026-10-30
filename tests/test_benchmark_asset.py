"""T43: the benchmark asset ships inside the package; a broken asset is internal_error, not 'unsupported workload'."""
from pathlib import Path

import pytest

from core import cost_per_job, throughput

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_asset_is_byte_copy_of_data():
    assert (ROOT / "core/assets/gpu_throughput.json").read_bytes() == (ROOT / "data/gpu_throughput.json").read_bytes()
    assert throughput.asset_info()["figures"] >= 71


def test_package_data_declared():
    assert '"lantern_works_deals_mcp.core" = ["assets/*.json"]' in (ROOT / "pyproject.toml").read_text()


@pytest.mark.parametrize("content", ["", "{not json", '{"schema": "other", "figures": [1]}', '{"schema": "lantern-works-gpu-throughput/1", "figures": []}'])
def test_corrupt_asset_is_asset_error(tmp_path, content):
    p = tmp_path / "t.json"; p.write_text(content)
    with pytest.raises(throughput.AssetError):
        throughput.lookup("H100 SXM 80GB", "resnet50", path=p)
    with pytest.raises(throughput.AssetError):
        throughput.lookup("H100 SXM 80GB", "resnet50", path=tmp_path / "missing.json")


def test_estimate_internal_error_on_broken_asset(monkeypatch):
    def boom(*a, **k):
        raise throughput.AssetError(throughput.ASSET_ERROR + ": test")
    monkeypatch.setattr(throughput, "lookup", boom)
    with pytest.raises(cost_per_job.JobCostError) as e:
        cost_per_job.estimate_job_cost({"records": []}, "H100 SXM 80GB", 1, work_units=1e6, workload="resnet50")
    assert e.value.code == "internal_error" and "packaging fault" in e.value.message


def test_training_still_abstains():
    fig, why = throughput.lookup("H100 SXM 80GB", "llama 3 70b fine-tuning")
    assert fig is None and "training" in why
