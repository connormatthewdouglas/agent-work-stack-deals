from urllib.parse import urlparse, parse_qs

from core.report_issue import report_issue_url, FORM_IDS


def test_report_issue_url_public_fields_only():
    r = {"advertiser": "RunPod", "gpu": "H100 SXM", "vram_gb": 80, "tier": "Secure Cloud", "hourly_usd": 2.69,
         "deal_id": "runpod-gpu", "source_url": "https://www.runpod.io/pricing", "query": "secret workload"}
    u = urlparse(report_issue_url(r))
    q = parse_qs(u.query)
    assert u.scheme == "https" and u.netloc == "github.com"
    assert q["template"] == ["wrong-price.yml"] and q["deal_id"] == ["runpod-gpu"]
    assert set(q) <= set(FORM_IDS) | {"template", "title"}
    assert "secret" not in report_issue_url(r)


def test_compare_results_carry_report_issue_url():
    import json
    from pathlib import Path
    from core.deals import compare_gpu_prices
    data = json.loads((Path(__file__).resolve().parents[1] / "api/v1/gpu-prices.json").read_text())
    out = compare_gpu_prices(data, "H100")
    assert all("template=wrong-price.yml" in x["report_issue_url"] for x in out["results"])
