"""T117: canonical citations retain exact API request evidence, prices and quotes."""
import copy
import json
import subprocess
from pathlib import Path

import pytest
from core.source_urls import citation_problems, normalize_doc, split_source, valid_source_url
from core.gpu import build_rates, form_factor_of, _vendor_gpu_id

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("url,method,op,ident,endpoint", [
    ("https://api.runpod.io/graphql gpuTypes.securePrice id=NVIDIA B300 SXM6 AC",
     "POST", "gpuTypes.securePrice", "NVIDIA B300 SXM6 AC", "https://api.runpod.io/graphql"),
    ("https://api.datacrunch.io/v1/instance-types (1B300.30V)",
     "GET", "instance-types", "1B300.30V", "https://api.datacrunch.io/v1/instance-types")])
def test_lossless_known_citation_formats(url, method, op, ident, endpoint):
    u, ev = split_source(url)
    assert u == endpoint and valid_source_url(u)
    assert ev == {"request_method": method, "operation": op, "record_id": ident}


@pytest.mark.parametrize("url", ["https://api.example.com op id=x", "https://", "http://example.com/",
    "https://example.com/ bad", "https://example.com/%ZZ", "https://example.com/\n", None,
    "https://user:secret@example.com/", "https://example.com:wrong/", "https://example.com:0/"])
def test_unknown_or_malformed_citations_are_rejected_not_guessed(url):
    assert not valid_source_url(url)
    with pytest.raises(ValueError):
        split_source(url)


def test_valid_query_url_is_not_changed():
    u = "https://prices.azure.com/api/retail/prices?$filter=armSkuName%20eq%20%27x%27"
    assert split_source(u) == (u, {})


# Exact (gpu, tier, record_id) sets for priced wider-gpu API citations. This is an identity
# check, not a floor: losing or adding a row must fail until the change is evidenced.
# RunPod was 23 until scout-data gen 20261121T184959Z-26cfadd5 (61f100461, 18:49:59Z /
# 1:49 PM ET Nov 21): RunPod's public gpuTypes list stopped returning Tesla V100-PCIE-16GB
# (Community Cloud $0.19). V100 SXM2 Community remains. The SKU was still absent in
# 20261122T005017Z-fb7d37c5 and in a 2026-11-22T01:31:39Z gpuTypes reread (46 types).
# Collector runpod() only emits a row when the id is present with a truthy cloud flag and
# price; the 18:49Z and 00:50Z wider batches completed with errors={} / rc=0.
RUNPOD_API_CITATIONS = {
    ("A40", "On-demand (Secure Cloud)", "NVIDIA A40"),
    ("B200", "On-demand (Community Cloud)", "NVIDIA B200"),
    ("B200", "On-demand (Secure Cloud)", "NVIDIA B200"),
    ("B300", "On-demand (Community Cloud)", "NVIDIA B300 SXM6 AC"),
    ("B300", "On-demand (Secure Cloud)", "NVIDIA B300 SXM6 AC"),
    ("L4", "On-demand (Secure Cloud)", "NVIDIA L4"),
    ("MI300X", "On-demand (Secure Cloud)", "AMD Instinct MI300X OAM"),
    ("RTX 6000 Ada", "On-demand (Community Cloud)", "NVIDIA RTX 6000 Ada Generation"),
    ("RTX 6000 Ada", "On-demand (Secure Cloud)", "NVIDIA RTX 6000 Ada Generation"),
    ("RTX A4000", "On-demand (Community Cloud)", "NVIDIA RTX A4000"),
    ("RTX A4000", "On-demand (Secure Cloud)", "NVIDIA RTX A4000"),
    ("RTX PRO 4000", "On-demand (Secure Cloud)", "NVIDIA RTX PRO 4000 Blackwell"),
    ("RTX PRO 4500", "On-demand (Secure Cloud)", "NVIDIA RTX PRO 4500 Blackwell"),
    ("RTX PRO 4500 Server", "On-demand (Secure Cloud)", "NVIDIA RTX PRO 4500 Blackwell Server Edition"),
    ("RTX PRO 5000", "On-demand (Community Cloud)", "NVIDIA RTX PRO 5000 Blackwell"),
    ("RTX PRO 5000", "On-demand (Secure Cloud)", "NVIDIA RTX PRO 5000 Blackwell"),
    ("RTX PRO 6000 Max-Q", "On-demand (Community Cloud)", "NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition"),
    ("RTX PRO 6000 Server", "On-demand (Community Cloud)", "NVIDIA RTX PRO 6000 Blackwell Server Edition"),
    ("RTX PRO 6000 Server", "On-demand (Secure Cloud)", "NVIDIA RTX PRO 6000 Blackwell Server Edition"),
    ("RTX PRO 6000 Workstation", "On-demand (Community Cloud)", "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"),
    ("RTX PRO 6000 Workstation", "On-demand (Secure Cloud)", "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"),
    ("V100 SXM2", "On-demand (Community Cloud)", "Tesla V100-SXM2-16GB"),
}
VERDA_API_CITATIONS = {
    ("B200", "On-demand instance (1x GPU)", "1B200.30V"),
    ("B200", "Spot instance (1x GPU)", "1B200.30V"),
    ("B300", "On-demand instance (1x GPU)", "1B300.30V"),
    ("B300", "Spot instance (1x GPU)", "1B300.30V"),
    ("GB300", "On-demand instance (1x GPU)", "1GB300.32V"),
    ("GB300", "Spot instance (1x GPU)", "1GB300.32V"),
    ("RTX 6000 Ada", "On-demand instance (1x GPU)", "1RTX6000ADA.10V"),
    ("RTX 6000 Ada", "Spot instance (1x GPU)", "1RTX6000ADA.10V"),
    ("RTX PRO 6000", "On-demand instance (1x GPU)", "1RTXPRO6000.30V"),
    ("RTX PRO 6000", "Spot instance (1x GPU)", "1RTXPRO6000.30V"),
    ("V100", "On-demand instance (1x GPU)", "1V100.4V"),
    ("V100", "Spot instance (1x GPU)", "1V100.4V"),
}


def test_api_citation_rows_have_request_metadata_and_unchanged_prices_quotes():
    expected = {"runpod": RUNPOD_API_CITATIONS, "verda": VERDA_API_CITATIONS}
    counts = {}
    for name in ("runpod", "verda"):
        d = json.loads((ROOT / f"data/gpu_pricing/{name}.json").read_text())
        assert not citation_problems(d)
        records = [r for r in d["records"] if "record_id" in r["evidence"]]
        counts[name] = len(records)
        got = {(r["gpu"], r["tier"], r["evidence"]["record_id"]) for r in records}
        assert got == expected[name]
        for r in records:
            assert valid_source_url(r["source_url"]) and r["source_url"] == r["evidence"]["source_url"]
            assert r["evidence"]["request_method"] == ("POST" if name == "runpod" else "GET")
        # An id that used to hide in the URL still determines the hardware form, not a guess from the model.
        if name == "runpod":
            r = next(r for r in records if "B300 SXM6" in r["evidence"]["record_id"])
            assert form_factor_of(r["gpu"], vendor_id=_vendor_gpu_id(r)) == "SXM6"
    assert counts == {"runpod": 22, "verda": 12}


def test_normalization_changes_only_citation_fields():
    d = json.loads((ROOT / "data/gpu_pricing/runpod.json").read_text())
    r = next(r for r in d["records"] if "record_id" in r["evidence"])
    legacy = copy.deepcopy(r)
    ev = legacy["evidence"]
    raw = f"{legacy['source_url']} {ev.pop('operation')} id={ev.pop('record_id')}"
    ev.pop("request_method")
    legacy["source_url"] = ev["source_url"] = raw
    original = copy.deepcopy(legacy)
    fixed, n = normalize_doc({**d, "records": [legacy]})
    assert n == 1 and legacy == original  # pure import normalization, no partial write
    for k in ("price_usd", "hourly_usd", "quote", "checked_at", "verified_at", "gpu", "tier"):
        assert fixed["records"][0][k] == original[k]
    assert fixed["records"][0]["evidence"]["quote"] == original["evidence"]["quote"]
    assert normalize_doc(fixed)[1] == 0


def test_export_refuses_malformed_or_incomplete_request_evidence():
    d = json.loads((ROOT / "data/gpu_pricing/runpod.json").read_text())
    r = next(r for r in d["records"] if "record_id" in r["evidence"])
    bad = copy.deepcopy(r); bad["source_url"] += " unrecognized operation"
    out = build_rates([], [{**d, "records": [bad]}])
    assert not out["rates"] and any("invalid canonical" in p for p in out["problems"])
    bad = copy.deepcopy(r); del bad["evidence"]["record_id"]
    assert any("invalid API request" in p for p in citation_problems({**d, "records": [bad]}))


def test_import_workflow_normalizes_after_wider_import_before_export():
    s = (ROOT / ".github/workflows/scout-import.yml").read_text()
    assert s.index("python3 scripts/import_scout_wider.py") < s.index("python3 scripts/normalize_gpu_sources.py") < s.index("python3 scripts/generate_seo_pages.py")
