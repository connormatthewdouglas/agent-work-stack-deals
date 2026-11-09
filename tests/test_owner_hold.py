"""Owner hold: Hyperstack and Verda rows on main are not rewritten by Scout imports."""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core.owner_hold import is_held  # noqa: E402
from core import gpu_history  # noqa: E402
import import_scout_availability as avail  # noqa: E402
import import_scout_wider as wider  # noqa: E402
import refresh_gpu_prices as refresh  # noqa: E402


def test_scout_import_failure_fails_the_job_and_still_opens_the_issue():
    text = (ROOT / ".github/workflows/scout-import.yml").read_text(encoding="utf-8")
    job = text.split("jobs:", 1)[1].split("import:", 1)[1].split("steps:", 1)[0]
    assert "continue-on-error" not in job
    assert 'pipeline_issue.sh "Scout import"' in text
    assert "rebase_push_main.sh" in text
    for name in ("gpu-refresh.yml", "lium-collect.yml"):
        body = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "contents: write" in body and "rebase_push_main.sh" in body


def test_hold_names_match_verda_parenthetical():
    names = ["Hyperstack", "Verda"]
    assert is_held("Verda", names) and is_held("Verda (formerly DataCrunch)", names)
    assert is_held("Hyperstack", names)
    assert not is_held("RunPod", names) and not is_held("Verdant", names)


def test_wider_hold_keeps_verda_and_hyperstack_bytes(tmp_path, monkeypatch):
    pricing = tmp_path / "gpu_pricing"
    pricing.mkdir()
    verda = {"vendor": "Verda (formerly DataCrunch)", "deal_id": None, "source_url": "https://verda.com/pricing",
             "checked_at": "2026-11-01T00:00:00+00:00",
             "records": [{"vendor": "Verda (formerly DataCrunch)", "gpu": "H100", "tier": "On-demand", "vram_gb": 80,
                          "price_usd": 1.5, "checked_at": "2026-11-01T00:00:00+00:00"}]}
    hyper = {"vendor": "Hyperstack", "deal_id": None, "source_url": "https://www.hyperstack.cloud/gpu-pricing",
             "checked_at": "2026-11-01T00:00:00+00:00",
             "records": [{"vendor": "Hyperstack", "gpu": "A100", "tier": "On-demand", "price_usd": 1.2,
                          "checked_at": "2026-11-01T00:00:00+00:00"}]}
    runpod = {"vendor": "RunPod", "deal_id": None, "source_url": "https://www.runpod.io/pricing",
              "checked_at": "2026-11-01T00:00:00+00:00", "records": []}
    for name, doc in (("verda.json", verda), ("hyperstack.json", hyper), ("runpod.json", runpod)):
        (pricing / name).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    before_v = (pricing / "verda.json").read_bytes()
    before_h = (pricing / "hyperstack.json").read_bytes()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    feed = {"version": "3.2", "batch": "wider-gpu", "collected_at": now, "generation_id": "test-gen",
            "rows": [
                {"vendor": "Verda", "gpu_model": "H100 SXM", "vram_gb": 80, "tier": "On-demand instance (1x GPU)",
                 "price_usd_hr": 9.99, "source_url": "https://verda.com/pricing", "verified_at": now, "batch": "wider-gpu"},
                {"vendor": "Hyperstack", "gpu_model": "A100", "vram_gb": 80, "tier": "On-demand", "price_usd_hr": 8.88,
                 "source_url": "https://www.hyperstack.cloud/gpu-pricing", "verified_at": now, "batch": "wider-gpu"},
                {"vendor": "RunPod", "gpu_model": "H100 SXM", "vram_gb": 80, "tier": "On-demand (Secure Cloud)",
                 "price_usd_hr": 2.5, "price_basis": "securePrice (list price, 1 GPU)", "gpu_count": 1,
                 "source_url": "https://www.runpod.io/pricing", "verified_at": now, "batch": "wider-gpu"},
            ]}
    src = tmp_path / "wider.json"
    src.write_text(json.dumps(feed), encoding="utf-8")
    monkeypatch.setattr(wider, "PRICING", pricing)
    monkeypatch.setitem(wider.FILES, "Hyperstack", "hyperstack.json")
    monkeypatch.setattr(wider, "META", tmp_path / "wider_meta.json")
    monkeypatch.setattr(sys, "argv", ["import_scout_wider.py", str(src)])
    wider.main()
    assert (pricing / "verda.json").read_bytes() == before_v
    assert (pricing / "hyperstack.json").read_bytes() == before_h
    got = json.loads((pricing / "runpod.json").read_text(encoding="utf-8"))
    assert any(r.get("gpu") == "H100 SXM" and r.get("price_usd") == 2.5 for r in got["records"])
    assert all(r["source_url"] == "https://www.runpod.io/pricing" for r in got["records"] if r.get("batch") == "wider-gpu")


def test_availability_hold_carries_rows_unchanged(tmp_path, monkeypatch):
    old_h = {"vendor": "Hyperstack", "gpu": "A100", "vram_gb": 80, "tier": "On-demand", "in_stock": False,
             "availability_checked_at": "2026-11-06T02:51:34Z", "availability_note": "keep hyperstack"}
    old_v = {"vendor": "Verda (formerly DataCrunch)", "gpu": "H100 SXM", "vram_gb": 80, "tier": "On-demand",
             "in_stock": True, "availability_checked_at": "2026-11-06T02:51:34Z", "availability_note": "keep verda"}
    out = tmp_path / "latest.json"
    out.write_text(json.dumps({"rows": [old_h, old_v]}), encoding="utf-8")
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    feed = {"version": "3.2", "generation_id": "gen-new", "rows": [
        {"vendor": "Hyperstack", "gpu": "A100", "vram_gb": 80, "tier": "On-demand", "in_live_feed": True,
         "in_stock": True, "availability_checked_at": fresh, "availability_note": "NEW hyperstack"},
        {"vendor": "Hyperstack", "gpu": "H100", "vram_gb": 80, "tier": "On-demand", "in_live_feed": True,
         "in_stock": True, "availability_checked_at": fresh, "availability_note": "extra hyperstack"},
        {"vendor": "Verda (formerly DataCrunch)", "gpu": "H100 SXM", "vram_gb": 80, "tier": "Spot", "in_live_feed": True,
         "in_stock": False, "availability_checked_at": fresh, "availability_note": "NEW verda"},
        {"vendor": "RunPod", "gpu": "H100", "vram_gb": 80, "tier": "On-demand", "in_live_feed": True,
         "in_stock": True, "availability_checked_at": fresh, "availability_source": "https://api.runpod.io/graphql",
         "availability_note": "runpod ok"},
    ]}
    src = tmp_path / "feed.json"
    raw = json.dumps(feed).encode()
    src.write_bytes(raw)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": {"feed_enriched_v2_latest.json": hashlib.sha256(raw).hexdigest()}}), encoding="utf-8")
    monkeypatch.setattr(avail, "OUT", out)
    monkeypatch.setattr(avail, "SRC", src)
    monkeypatch.setenv("LW_SCOUT_MANIFESTS", str(manifest))
    monkeypatch.setattr(sys, "argv", ["import_scout_availability.py", str(src)])
    avail.main()
    doc = json.loads(out.read_text(encoding="utf-8"))
    held = [r for r in doc["rows"] if r["vendor"].startswith("Hyperstack") or r["vendor"].startswith("Verda")]
    assert [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in sorted(held, key=lambda r: r["vendor"])] == [
        json.dumps(old_h, ensure_ascii=False, sort_keys=True),
        json.dumps(old_v, ensure_ascii=False, sort_keys=True),
    ]
    assert all(r["availability_checked_at"] == "2026-11-06T02:51:34Z" for r in held)
    assert any(r["vendor"] == "RunPod" and r["availability_checked_at"] == fresh for r in doc["rows"])
    assert doc["owner_hold_carried"] == 2


def _priced(vendor, price="1.99"):
    """A row whose evidence quote matches PAGE, so a refresh would reprice it if the vendor were not held."""
    quote = "NVIDIA A100 SXM 40 GB 30 220 GiB 512 GiB SSD $1.99"
    checked = "2026-11-01T10:00:00+00:00"
    return {"vendor": vendor, "deal_id": None, "source_url": "https://example.test/pricing",
            "checked_at": checked,
            "extras": {k: {"status": "unknown", "text": "x", "source_url": "https://example.test/pricing"}
                       for k in ("egress", "storage", "interruption")},
            "records": [{
                "vendor": vendor, "gpu": "A100 SXM", "vram_gb": 40, "price_usd": float(price), "billing_unit": "hourly",
                "hourly_usd": float(price), "interruptible": False, "tier": "On-demand", "form_factor": "SXM",
                "quote": f"A100 ${price}/hr", "source_url": "https://example.test/pricing", "checked_at": checked,
                "evidence": {"source_url": "https://example.test/pricing", "quote": quote, "checked_at": checked},
                "verified_at": checked,
            }]}


_PARSED_PAGE = ("<html><body><table><tr><td>NVIDIA A100 SXM</td><td>40 GB</td><td>30</td>"
                "<td>220 GiB</td><td>512 GiB SSD</td><td>$1.89</td></tr></table></body></html>")


def test_refresh_does_not_touch_held_vendors_when_the_page_parses():
    now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    held = [_priced("Hyperstack"), _priced("Verda (formerly DataCrunch)")]
    before = [json.dumps(d, sort_keys=True) for d in held]
    hist_before = gpu_history.snapshot_rows(held)
    class Fetch:
        def __init__(self):
            self.calls = []
        def get(self, url):
            self.calls.append(url)
            return 200, _PARSED_PAGE
    fetch = Fetch()
    # The same page reprices a vendor that is not on the hold, so the fixture really parses.
    control = _priced("RunPod")
    report = refresh.refresh(held + [control], fetch, now)
    assert [json.dumps(d, sort_keys=True) for d in held] == before
    assert gpu_history.snapshot_rows(held) == hist_before
    assert fetch.calls == ["https://example.test/pricing"]  # only RunPod
    assert control["records"][0]["price_usd"] == 1.89
    assert control["records"][0]["checked_at"].startswith("2026-11-09")
    assert {r["result"] for r in report if r["vendor"] != "RunPod"} == {"owner hold, untouched"}


def test_owner_held_prices_do_not_rank_in_cheapest_compare_or_agent_stack():
    from core.gpu import build_rates
    from core.deals import compare_gpu_prices
    from core import agent_stack
    deals = json.loads((ROOT / "api/v1/deals.json").read_text())["deals"]
    built = build_rates(deals)
    assert not any(is_held(r["advertiser"]) for r in built["rates"])
    assert not any(is_held(v["vendor"]) for v in built["vendors"])
    owners = [h for h in built["held_stale"] if is_held(h["vendor"])]
    assert owners and {h["reason"] for h in owners} == {"owner_hold"}
    assert any(h["vendor"] == "Hyperstack" for h in owners)
    assert any(str(h["vendor"]).startswith("Verda") for h in owners)
    cheap = {"advertiser": "Hyperstack", "gpu": "H100 SXM", "vram_gb": 80, "hourly_equiv_usd": 0.01,
             "price_usd": 0.01, "unit": "hour", "tier": "On-demand", "tier_class": "on-demand",
             "interruptible": False, "billing_unit": "hourly", "source_url": "https://example.test/h",
             "verified_at": "2026-11-09T00:00:00Z", "checked_at": "2026-11-09T00:00:00Z",
             "availability": {"in_stock": None}, "gpu_count": 1, "min_gpus": 1}
    other = {**cheap, "advertiser": "RunPod", "hourly_equiv_usd": 2.5, "price_usd": 2.5,
             "source_url": "https://example.test/r"}
    out = compare_gpu_prices({"rates": [cheap, other], "feed_updated_at": "2026-11-09T00:00:00Z"}, "H100", limit=5)
    assert [r["advertiser"] for r in out["results"]] == ["RunPod"]
    assert out["held_owner"][0]["reason"] == "owner_hold" and out["held_owner"][0]["vendor"] == "Hyperstack"
    only = compare_gpu_prices({"rates": [cheap]}, "H100")
    assert only["results"] == [] and only["held_owner"][0]["reason"] == "owner_hold"
    plan = agent_stack.plan("100 GPU hours", deals, {"offers": []}, {"rates": [cheap, other]})
    gpu_line = next(line for line in plan["lines"] if line["component"] == "gpu")
    assert gpu_line["choice"]["vendor"] == "RunPod"
    assert gpu_line["held"][0]["reason"] == "owner_hold" and gpu_line["held"][0]["vendor"] == "Hyperstack"


def test_committed_feed_wall_clock_catches_stale_ranked_rows(monkeypatch):
    """Outside T41-12, and without the pinned build clock. Owner-held rows are not ranked.
    A non-held vendor-file row past its existing hold (7 days, or 48h for a batch row) is not ranked either.
    Thresholds are unchanged. T41-12's 48h bar on the published feed stays in the release gate."""
    monkeypatch.delenv("LW_AVAIL_NOW", raising=False)
    from core.gpu import build_rates, load_vendor_files
    from core.data_age import STALE_HOURS
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    assert not any(is_held(r.get("advertiser")) for r in feed["rates"])
    assert any(h.get("reason") == "owner_hold" and is_held(h.get("vendor")) for h in feed.get("held_stale") or [])
    deals = json.loads((ROOT / "api/v1/deals.json").read_text())["deals"]
    built = build_rates(deals)  # wall clock: LW_AVAIL_NOW is unset
    assert not any(is_held(r["advertiser"]) for r in built["rates"])
    assert {h["reason"] for h in built["held_stale"] if is_held(h["vendor"])} == {"owner_hold"}
    now = datetime.now(timezone.utc)
    for doc in load_vendor_files():
        if doc.get("stale") or doc.get("manual_snapshot") or is_held(doc.get("vendor")):
            continue
        for rec in doc["records"]:
            if rec.get("stale") or rec.get("no_capacity"):
                continue
            stamp = datetime.fromisoformat(str(rec.get("verified_at") or rec["checked_at"]).replace("Z", "+00:00"))
            limit = 48 if rec.get("price_check") == "batch" or rec.get("batch") else STALE_HOURS
            if (now - stamp).total_seconds() / 3600 <= limit:
                continue
            assert not any(r["advertiser"] == rec.get("vendor") and r["gpu"] == rec.get("gpu") and r.get("tier") == rec.get("tier")
                           and r.get("verified_at") == (rec.get("verified_at") or rec.get("checked_at"))
                           for r in built["rates"]), (rec.get("vendor"), rec.get("gpu"))
