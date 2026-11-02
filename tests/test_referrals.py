import copy, json
from pathlib import Path
from core import deals as core
from core.referrals import REFERRALS, REFERRAL_LABEL

ROOT = Path(__file__).resolve().parents[1]
FEED = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())


def test_referral_label_on_every_code_carrying_row():
    from core.referrals import has_ref_code
    for r in FEED["rates"]:
        if r["advertiser"] in REFERRALS:
            assert r["referral_url"] == REFERRALS[r["advertiser"]] and r["referral_label"] == REFERRAL_LABEL
        if r.get("affiliate") or has_ref_code(r.get("redeem_url")) or has_ref_code(r.get("referral_url")):
            assert r.get("referral_label") == REFERRAL_LABEL, (r["advertiser"], r.get("redeem_url"))
        if r["advertiser"] in ("Lambda", "Hyperstack") or r["advertiser"].startswith("Verda"):
            assert "referral_url" not in r and "referral_label" not in r, r["advertiser"]
    labelled = {r["advertiser"] for r in FEED["rates"] if r.get("referral_label")}
    assert {"Vast.ai", "Ucartz", "Clore.ai", "Novita AI", "99Stack Cloud", "RunPod", "Thunder Compute"} <= labelled


def test_codes_are_never_stripped():
    for r in FEED["rates"]:
        if r.get("referral_url") and r["advertiser"] not in REFERRALS:
            assert r["referral_url"] == r["redeem_url"]


def test_has_ref_code_detects_common_params():
    from core.referrals import has_ref_code
    for u in ("https://x.com/?ref=a", "https://x.com/?ref_id=1", "https://x.com/aff.php?aff=5", "https://x.com/a/abc", "https://x.com/?via=lw", "https://x.com/?fpr=lw"):
        assert has_ref_code(u), u
    assert not has_ref_code("https://lambda.ai/pricing")


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
        if r["advertiser"] in REFERRALS:
            assert r["referral_url"] == REFERRALS[r["advertiser"]] and r["referral_label"] == REFERRAL_LABEL
    full = server.compare_gpu_prices("H100", limit=25, mode="full")["results"]
    for r in full:
        if r.get("redeem_url") and r.get("affiliate"):
            assert r.get("referral_label") == REFERRAL_LABEL, r["advertiser"]


def test_site_tables_label_every_code_carrying_gpu_row():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    t = (root / "gpu/rtx-4090-rental-price/index.html").read_text()
    for row in re.findall(r"<tr>.*?</tr>", t, re.S):
        if "Vast.ai" in row and "Link" in row:
            assert "Referral link" in row
