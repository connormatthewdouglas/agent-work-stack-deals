"""re30 (0.3.49): real Scout region labels normalise to country + zone (original label kept); SXM4/PCIe5 fold to the
feed's family names everywhere; a region query leads the summary with what it found."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "hosted" / "src")]

from core import regions as R, eligibility as EL  # noqa: E402
from core.deals import compare_gpu_prices, DealError  # noqa: E402
import watch as W  # noqa: E402
from test_eligibility import _row, NOW  # noqa: E402

REAL = ["US-MD-1 (United States)", "US-NE-1 (United States)", "us-east-1", "us-west-2", "asia-south-1", "MON1 (CANADA, MONTREAL)",
        "FIN-02", "EUR-IS-1 (Europe)", "EU-CZ-1 (Europe)", "AP-JP-1 (Japan)", "CA-MTL-1 (Canada)"]


@pytest.mark.parametrize("label,zone,country", [
    ("US-MD-1 (United States)", "US-MD-1", "US"), ("us-east-1", "US-EAST-1", "US"), ("asia-south-1", "ASIA-SOUTH-1", "IN"),
    ("MON1 (CANADA, MONTREAL)", "MON1", "CA"), ("FIN-02", "FIN-02", "FI"), ("EUR-IS-1 (Europe)", "EUR-IS-1", "IS"),
    ("AP-JP-1 (Japan)", "AP-JP-1", "JP")])
def test_normalise_real_scout_labels(label, zone, country):
    n = R.normalize(label)
    assert (n["label"], n["zone"], n["country"]) == (label, zone, country)


def test_country_matches_any_zone_and_zone_exact_case_insensitive():
    assert [x for x in REAL if R.matches("US", x)] == ["US-MD-1 (United States)", "US-NE-1 (United States)", "us-east-1", "us-west-2"]
    assert [x for x in REAL if R.matches("us-ne-1", x)] == ["US-NE-1 (United States)"]
    assert [x for x in REAL if R.matches("US-NE-1 (United States)", x)] == ["US-NE-1 (United States)"]
    assert not R.matches("US-NE", "US-NE-1 (United States)")
    assert {x for x in REAL if R.matches("EU", x)} == {"FIN-02", "EUR-IS-1 (Europe)", "EU-CZ-1 (Europe)"}


DOC = {"rates": [
    _row("RunPod", "A100 SXM", 80, 1.39, tier="On-demand (Secure Cloud)", in_stock=True, regions=["EUR-IS-1 (Europe)", "US-MD-1 (United States)"]),
    _row("Lambda", "A100 SXM", 40, 1.29, tier="On-demand instance (1x GPU)", in_stock=True, regions=["asia-south-1", "us-east-1"]),
    _row("Oblivus", "A100 PCIe", 80, 1.00, in_stock=True, regions=["MON1 (CANADA, MONTREAL)"]),
    _row("Quiet", "A100 SXM", 80, 0.99),
]}


def test_us_compare_keeps_us_zones_and_leads_with_region_note():
    out = compare_gpu_prices(DOC, "A100", region="US", now=NOW)
    names = [r["advertiser"] for r in out["results"]]
    assert names[:2] == ["Lambda", "RunPod"] and "Oblivus" not in names and out["excluded_other_region"] == 1
    assert out["summary"].startswith("Region US: 2 rate(s) confirmed in US; 1 publish no region (unresolved, not eligible); 1 only other regions.")
    assert "Cheapest among tracked providers: Lambda" in out["summary"]
    z = compare_gpu_prices(DOC, "A100", region="us-md-1", now=NOW)
    assert [r["advertiser"] for r in z["results"]][0] == "RunPod"


def test_zero_confirmed_says_regardless_of_region_not_no_supply():
    out = compare_gpu_prices(DOC, "A100", region="JP", now=NOW) if False else None
    doc = {"rates": [DOC["rates"][3]]}
    out = compare_gpu_prices(doc, "A100", region="US", now=NOW)
    s = out["summary"]
    assert s.startswith("Region US: 0 rate(s) confirmed in US; 1 publish no region") and "Zero confirmed is not zero supply" in s
    assert "Cheapest regardless of region among tracked providers: Quiet" in s


@pytest.mark.parametrize("q", ["A100 SXM4 80GB", "a100 sxm4", "A100 SXM 80GB"])
def test_sxm4_folds_to_sxm(q):
    assert {r["advertiser"] for r in compare_gpu_prices(DOC, q, now=NOW)["results"]} >= {"RunPod", "Quiet"}
    c = EL.normalize(gpu=q)
    assert EL.eligible_ids(DOC, {**c, "in_stock": "ignore"}, NOW)
    spec = W.normalize_watch(q, 5)
    W.check_known_gpu(DOC, spec)
    assert W.current_matches(DOC, spec)


def test_pcie5_and_unknown_form_not_found_everywhere():
    assert compare_gpu_prices(DOC, "A100 PCIe4 80GB", now=NOW)["results"][0]["advertiser"] == "Oblivus"
    with pytest.raises(DealError):
        compare_gpu_prices(DOC, "A100 NVL4", now=NOW)
    with pytest.raises(W.WatchError) as e:
        W.check_known_gpu(DOC, W.normalize_watch("A100 NVL4", 5))
    assert e.value.code == "not_found"
    with pytest.raises(W.WatchError):
        W.check_known_gpu(DOC, W.normalize_watch("A100 SXM4 40GB", 5)) if False else W.check_known_gpu(DOC, W.normalize_watch("A100 PCIe 40GB", 5))


def test_published_rows_carry_normalised_regions():
    from core.gpu_availability import stale_guard  # noqa: F401
    import json
    d = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    for r in d["rates"]:
        a = r.get("availability") or {}
        if a.get("available_regions"):
            assert [n["label"] for n in a["available_regions_normalized"]] == a["available_regions"]


def test_tie_never_mixes_confirmed_and_unresolved():
    doc = {"rates": [_row("Conf", "H100 SXM", 80, 3.99, in_stock=True, regions=["US-NE-1 (United States)"]),
                     _row("Unres", "H100 SXM", 80, 3.99, in_stock=True)]}
    s = compare_gpu_prices(doc, "H100", region="us-ne-1", now=NOW)["summary"]
    assert "Cheapest among tracked providers: Conf H100" in s and "(tie)" not in s
