import copy, json
from pathlib import Path
from core import deals as core
from core.referrals import REFERRALS, REFERRAL_LABEL

ROOT = Path(__file__).resolve().parents[1]
FEED = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())


def test_referral_only_on_runpod_and_thunder():
    for r in FEED["rates"]:
        if r["advertiser"] in ("RunPod", "Thunder Compute"):
            assert r["referral_url"] == REFERRALS[r["advertiser"]] and r["referral_label"] == REFERRAL_LABEL
        else:
            assert "referral_url" not in r and "referral_label" not in r, r["advertiser"]
    assert {"Lambda", "Hyperstack"} <= {r["advertiser"] for r in FEED["rates"]}


def test_additive_currency_fields():
    for r in FEED["rates"]:
        assert r["quote_currency"] == "USD" and "fx_date" in r and r["last_verified"] == r["verified_at"]


def _order(data, gpu):
    return [x["rate_id"] for x in core.compare_gpu_prices(data, gpu, limit=25)["results"]]


def test_referral_never_changes_order():
    for gpu in ("H100", "A100", "RTX 4090"):
        base = _order(FEED, gpu)
        stripped = copy.deepcopy(FEED)
        for r in stripped["rates"]:
            r.pop("referral_url", None); r.pop("referral_label", None)
        assert _order(stripped, gpu) == base
        everyone = copy.deepcopy(FEED)
        for r in everyone["rates"]:
            r["referral_url"] = "https://example.com/?ref=x"; r["referral_label"] = REFERRAL_LABEL
        assert _order(everyone, gpu) == base


def test_brief_output_keeps_new_fields(monkeypatch):
    from mcp_server import server
    monkeypatch.setattr(server, "gpu_loader", core.GpuPricesLoader(file=str(ROOT / "api/v1/gpu-prices.json")))
    out = server.compare_gpu_prices("H100", limit=25)
    assert out["mode"] == "brief"
    rows = out["results"]
    assert rows and all(r["quote_currency"] == "USD" and "last_verified" in r and "fx_date" in r for r in rows)
    for r in rows:
        assert ("referral_url" in r) == (r["advertiser"] in REFERRALS)
