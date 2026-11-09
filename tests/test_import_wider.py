"""T63: the wider importer preserves the full economic offer, separates verbatim and normalized evidence, holds rows
with missing allocation/evidence, and re-imports idempotently without touching curated rows."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from core import gpu as g  # noqa: E402
from import_scout_wider import apply, normalize, normalize_ex  # noqa: E402

BASE = {"tier": "On-demand", "source_url": "https://example.test/pricing", "source_detail": "https://example.test/api",
        "verified_at": "2026-10-31T13:08:29+00:00", "batch": "wider-gpu", "price_basis": "api.price_per_hour (list price, 1 GPU)"}


def row(**k):
    return {**BASE, **k}


def _doc(vendor, records):
    return {"vendor": vendor, "deal_id": None, "source_url": "https://example.test/pricing",
            "checked_at": "2026-10-31T13:08:29+00:00", "records": records}


FILES = {"RunPod": "runpod.json", "Lambda": "lambda.json", "Vast.ai": "vast.json", "Verda": "verda.json"}


def _valid(vendor, rec):
    doc = json.loads((ROOT / "data/gpu_pricing" / FILES[vendor]).read_text())
    doc["records"] = [{**rec, "vendor": doc["vendor"]}]
    probs = g.record_problems(doc)
    assert not probs, probs


def test_b300_keeps_vendor_memory():
    r = normalize(row(vendor="Verda", gpu_model="B300 SXM 268GB", vram_gb=268, price_usd_hr=11.35))
    assert r["gpu"] == "B300 SXM" and r["vram_gb"] == 268 and "vram_note" not in r
    _valid("Verda", r)


def test_eight_gpu_only_offer_bills_sixteen_for_nine():
    r = normalize(row(vendor="Lambda", gpu_model="H100 SXM 80GB", vram_gb=80, price_usd_hr=2.99, gpu_count=8,
                      min_gpus=8, server_price_usd_hr=23.92, price_basis="instance price_cents_per_hour (8x H100 server)"))
    assert r["gpu_count"] == 8 and r["min_gpus"] == 8 and r["price_usd"] == 23.92
    assert r["hourly_usd"] == 2.99 and r["server_hourly_usd"] == 23.92
    _valid("Lambda", r)
    est = g.estimate([{**r, "advertiser": "Lambda", "unit": "hour", "price_usd": r["hourly_usd"]}], 10, gpus=9)[0]
    assert est["billed_gpus"] == 16 and est["instances"] == 2


def test_serverless_per_second_is_held():
    for r in (row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=None, price_usd_sec=0.000119,
                  billing_unit="per-second", price_basis="serverless flex price per second (1 GPU)"),
              row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.43, price_basis="serverless active worker price (1 GPU)"),
              row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.43, tier="Serverless flex")):
        rec, why = normalize_ex(r)
        assert rec is None and "serverless" in why, r


def _curated(name):
    return json.loads((ROOT / "data/gpu_pricing" / f"{name}.json").read_text())


def test_actual_curated_serverless_rows_are_held_whatever_the_field():
    # T63 (Bjorn 1108): the feed's real serverless rows, Koyeb L40S ("Serverless GPU instance (per-second billing)",
    # billing_unit hourly, $1.20) and Modal (billing_unit per-second), are exactly what must never enter as a dedicated
    # hourly rate. Their own fields and text are used verbatim; no values are invented.
    koyeb, modal = _curated("koyeb"), _curated("modal")
    leaks = [{**x, "billing_granularity": d.get("billing_granularity")} for d in (koyeb, modal) for x in d["records"]]
    assert len(leaks) == 5
    for x in leaks:
        r = row(vendor=x["vendor"], gpu_model=x["gpu"], vram_gb=x["vram_gb"], price_usd_hr=x["hourly_usd"], gpu_count=1,
                **{k: v for k, v in x.items() if k not in ("vendor", "gpu", "vram_gb", "price_usd", "hourly_usd")})
        rec, why = normalize_ex(r)
        assert rec is None and why.startswith("serverless/per-second"), (x["vendor"], x["gpu"], why)
    # each serverless signal alone, under whatever field name carries it, holds an otherwise importable RunPod row
    k = koyeb["records"][0]
    ok = row(vendor="RunPod", gpu_model="L40S 48GB", vram_gb=48, price_usd_hr=k["hourly_usd"], gpu_count=1)
    assert normalize_ex(ok)[0] is not None  # control: imports without the signal
    # (follow-up, Gauge 1108 #102 a) billing_granularity and a quote's "/sec" are not hold signals on their own:
    # dedicated pods are billed per second too. Those cases are in test_per_second_text_alone_does_not_hold_dedicated_rows.
    signals = {"platform_fee_note": k["platform_fee_note"], "observation": k["tier"], "billing": "per-second",
               "billing_unit": "per_second", "price_usd_sec": 0.000333, "price_per_second": 0.000333,
               "usd_per_sec": 0.000333, "source_url": "https://www.runpod.io/serverless-gpu",
               "gpu_model": "L40S 48GB (Serverless)", "tier": modal["records"][0]["tier"]}
    for f, v in signals.items():
        rec, why = normalize_ex({**ok, f: v})
        assert rec is None and why.startswith("serverless/per-second"), (f, v, why)


def test_serverless_rows_land_in_unresolved_not_records():
    k = _curated("koyeb")["records"][0]
    rows = [row(vendor="RunPod", gpu_model="L40S 48GB", vram_gb=48, price_usd_hr=k["hourly_usd"], gpu_count=1,
                platform_fee_note=k["platform_fee_note"])]
    out, unresolved, total = apply({"RunPod": _doc("RunPod", [])}, rows)
    assert total == 0 and out["RunPod"]["records"] == []
    assert unresolved and unresolved[0]["reason"].startswith("serverless/per-second")


def test_no_false_serverless_hold_on_dedicated_rows():
    for t in ("On-demand (Secure Cloud)", "On-demand (Community Cloud)", "Spot instance (1x GPU)", "Marketplace on-demand (verified)"):
        assert normalize_ex(row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.39, tier=t, gpu_count=1))[0], t


def test_community_and_marketplace_are_not_interruptible():
    # Gauge 1104 correction: only spot/preemptible tiers are interruptible; labels are not rewritten
    for tier in ("Community Cloud", "Marketplace on-demand"):
        r = normalize(row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.39, tier=tier))
        assert r["interruptible"] is False and r["tier"] == tier, tier
        _valid("RunPod", r)
    r = normalize(row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.39, tier="Spot"))
    assert r["interruptible"] is True and r["tier"] == "Spot"
    _valid("RunPod", r)
    assert normalize(row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.39))["interruptible"] is False


def test_marketplace_median_keeps_sample_and_method():
    r = normalize(row(vendor="Vast.ai", gpu_model="A40", vram_gb=48, price_usd_hr=0.5344, offer_count=7, distinct_machines=6,
                      lowest_offer_usd=0.41, gpu_count=1, price_basis="median per-GPU dph_total", tier="Marketplace on-demand"))
    assert r["interruptible"] is False
    assert r["price_status"] == "marketplace" and r["offer_count"] == 7 and r["lowest_offer_usd"] == 0.41
    assert r["market_sample"]["distinct_machines"] == 6 and r["evidence_kind"] == "api_field"
    assert "7 offers" in r["evidence"]["quote"] and "0.5344" in r["evidence"]["quote"]
    _valid("Vast.ai", r)
    # without a lowest offer it stays a plain listed median (offer_count never at top level)
    r2 = normalize(row(vendor="Vast.ai", gpu_model="A40", vram_gb=48, price_usd_hr=0.5344, offer_count=7, gpu_count=1))
    assert r2["price_status"] == "listed" and "offer_count" not in r2 and r2["market_sample"]["offer_count"] == 7


def test_reserved_rate_is_classed_reserved():
    r = normalize(row(vendor="Lambda", gpu_model="B200 SXM 180GB", vram_gb=180, price_usd_hr=3.79, tier="Reserved 1-year",
                      term="1 year"))
    assert r["tier_class"] == "reserved" and r["term"] == "1 year"
    _valid("Lambda", r)


def test_thin_market_held():
    rec, why = normalize_ex(row(vendor="Vast.ai", gpu_model="A40", vram_gb=48, price_usd_hr=0.5, offer_count=4, gpu_count=1))
    assert rec is None and "thin market" in why
    rec, why = normalize_ex(row(vendor="Vast.ai", gpu_model="L4", vram_gb=22, price_usd_hr=0.6, feed_status="held_below_min_offers"))
    assert rec is None and "thin market" in why


def test_unsupported_input():
    for r in (row(vendor="Nowhere", gpu_model="H100", price_usd_hr=1.0),
              row(vendor="RunPod", gpu_model="H100", price_usd_hr="cheap"),
              row(vendor="RunPod", gpu_model="H100", price_usd_hr=1.0, billing_unit="per-day"),
              row(vendor="RunPod", gpu_model="H100", price_usd_hr=1.0, gpu_count=0),
              row(vendor="RunPod", gpu_model="Quantum Widget", price_usd_hr=1.0)):
        rec, why = normalize_ex(r)
        assert rec is None and why, r


def test_missing_allocation_or_evidence_held():
    rec, why = normalize_ex(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.0, price_basis="list"))
    assert rec is None and "allocation missing" in why
    rec, why = normalize_ex(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.0, gpu_count=1, price_basis=None))
    assert rec is None and "evidence missing" in why
    rec, why = normalize_ex(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.0, gpu_count=1, source_url="http://x"))
    assert rec is None and "evidence missing" in why


def test_verbatim_and_summary_separate():
    v = normalize(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.39, quote_verbatim="H100 SXM $2.39/hr"))
    assert v["evidence_kind"] == "verbatim" and v["evidence"]["quote"] == "H100 SXM $2.39/hr"
    assert "importer summary" in v["normalized_summary"] and v["normalized_summary"] != v["evidence"]["quote"]
    a = normalize(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2.39))
    assert a["evidence_kind"] == "api_field" and a["evidence"]["quote"].startswith("api.price_per_hour (list price, 1 GPU): 2.39")
    assert "importer summary" not in a["evidence"]["quote"] and a["evidence_method"]


def test_skips():
    assert normalize(row(vendor="RunPod", gpu_model="T4 16GB", vram_gb=16, price_usd_hr=0.2)) is None
    assert normalize_ex(row(vendor="Clore.ai", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.3)) == (None, None)
    assert normalize_ex(row(vendor="TensorDock", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.3)) == (None, None)
    assert normalize_ex(row(vendor="Oblivus", gpu_model="B200 SXM 192GB", vram_gb=192, price_usd_hr=None)) == (None, None)


def test_idempotent_and_removes_stale_rows_only():
    curated = {"vendor": "RunPod", "gpu": "H100", "tier": "On-demand", "vram_gb": 80, "quote": "curated"}
    stale = {"vendor": "Verda", "gpu": "V100", "tier": "x", "vram_gb": 16, "batch": "wider-gpu"}
    docs = {"RunPod": _doc("RunPod", [curated]), "Verda": _doc("Verda", [stale, {"gpu": "A100", "quote": "curated"}])}
    rows = [row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=1.0),  # collides with curated: curated wins
            row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.59),
            row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.59)]  # duplicate in batch
    out1, unres, n1 = apply(docs, rows)
    assert n1 == 1 and out1["RunPod"]["records"][0] == curated
    assert [x["gpu"] for x in out1["Verda"]["records"]] == ["A100"]  # stale batch row removed, vendor absent from batch
    out2, _, n2 = apply(out1, rows)
    assert out2 == out1 and n2 == n1
    assert docs["Verda"]["records"][0] is stale  # inputs not mutated


def test_source_detail_is_evidence_only_and_interruptible_follows_tier():
    ob = normalize(row(vendor="Oblivus", gpu_model="RTX 4090", vram_gb=24, price_usd_hr=0.64, gpu_count=1,
                       source_url="https://oblivus.com/pricing/",
                       source_detail='https://oblivus.com/pricing/ ("RTX 4090" card)'))
    assert ob["source_url"] == "https://oblivus.com/pricing/"
    assert ob["evidence"]["source_url"] == "https://oblivus.com/pricing/"
    assert "RTX 4090" in ob["source_detail"] and "(" not in ob["source_url"] and ob["interruptible"] is False
    assert normalize(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2, gpu_count=1, tier="Spot"))["interruptible"] is True
    assert normalize(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2, gpu_count=1, tier="Preemptible"))["interruptible"] is True
    assert normalize(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2, gpu_count=1, tier="Interruptible"))["interruptible"] is True
    assert normalize(row(vendor="RunPod", gpu_model="H100", vram_gb=80, price_usd_hr=2, gpu_count=1, tier="bid"))["interruptible"] is True
    assert normalize(row(vendor="Oblivus", gpu_model="H100", vram_gb=80, price_usd_hr=2, gpu_count=1,
                         source_url='https://oblivus.com/pricing/ ("H100" card)')) is None


def test_refuses_wrong_schema(tmp_path):
    f = tmp_path / "w.json"
    f.write_text(json.dumps({"version": "3.1", "batch": "wider-gpu", "collected_at": datetime.now(timezone.utc).isoformat(), "rows": []}))
    p = subprocess.run([sys.executable, str(ROOT / "scripts/import_scout_wider.py"), str(f), "--dry-run"], capture_output=True, text=True)
    assert p.returncode != 0 and "refusing" in (p.stdout + p.stderr)


def test_modal_h100_per_second_never_ranked_in_any_pricing_mode():
    # Gauge 1108: Modal's serverless per-second H100 row (tier "Serverless, preemptible (per second)", billing_unit
    # per-second, $0.001097/s) showed up in the non-on-demand compare results as an hourly rate. It is held in every mode.
    from core import deals as core
    from core.gpu import build_rates
    feed = json.loads((ROOT / "deals.json").read_text())["deals"]
    data = build_rates(feed)
    modal = [r for r in data["rates"] if r["advertiser"] == "Modal" and r["gpu"] == "H100 SXM"]
    assert modal and modal[0]["billing_unit"] == "per-second" and modal[0]["price_per_second_usd"] == 0.001097
    now = datetime.fromisoformat(modal[0]["verified_at"])  # judge the tree as of the row's own check time (no staleness)
    for kw in ({"on_demand_only": False}, {"on_demand_only": False, "include_reserved": True}, {"on_demand_only": True},
               {"on_demand_only": False, "max_data_age_hours": 720}):
        out = core.compare_gpu_prices(data, "H100", limit=25, now=now, **kw)
        assert not [x for x in out["results"] if x["advertiser"] == "Modal" or x.get("billing_unit") == "per-second"], kw
        held = [h for h in out["held_serverless"] if h["vendor"] == "Modal" and h["gpu"] == "H100 SXM"]
        assert held and held[0]["reason"].startswith("serverless/per-second") and held[0]["price_per_second_usd"] == 0.001097, kw
        assert out["excluded_serverless"] >= 1
    # Koyeb's L40S "Serverless GPU instance (per-second billing)" is billed hourly in the feed but is serverless too
    out = core.compare_gpu_prices(data, "L40S", limit=25, on_demand_only=False, now=now)
    assert not [x for x in out["results"] if x["advertiser"] in ("Koyeb", "Modal")]
    assert {h["vendor"] for h in out["held_serverless"]} >= {"Koyeb", "Modal"}
    # only-serverless model: a clear not_found, never a serverless 'cheapest'
    only = {"rates": [r for r in data["rates"] if r["advertiser"] == "Modal"]}
    try:
        core.compare_gpu_prices(only, "H100", on_demand_only=False, now=now)
        raise AssertionError("serverless-only model must not rank")
    except core.DealError as e:
        assert "serverless" in str(e)


def test_per_second_text_alone_does_not_hold_dedicated_rows():
    # Gauge 1108 #102 (a): only per-second PRICE keys (or a per-second billing unit) hold a row; "per second" billing
    # text and non-price *_seconds keys on a dedicated on-demand row do not.
    koyeb = _curated("koyeb")
    ok = row(vendor="RunPod", gpu_model="H100 SXM 80GB", vram_gb=80, price_usd_hr=2.69, gpu_count=1, tier="On-demand (Secure Cloud)")
    for f, v in {"billing_granularity": koyeb["billing_granularity"], "quote_verbatim": "H100 SXM $2.69/hr, billed per second",
                 "availability_note": "$2.69 /hr $0.000747 /sec", "two_read_gap_seconds": 60, "stock_read_gap_sec": 30,
                 "min_billing_seconds": 60}.items():
        rec, why = normalize_ex({**ok, f: v})
        assert rec is not None and why is None, (f, v, why)
    for f, v in {"price_usd_sec": 0.000747, "price_per_second": 0.000747, "usd_per_sec": 0.000747, "cost_per_second": 0.000747,
                 "billing_unit": "per-second"}.items():
        rec, why = normalize_ex({**ok, f: v})
        assert rec is None and why.startswith("serverless/per-second"), (f, v, why)


def test_bid_tier_is_interruptible_whole_word_like_core():
    # Gauge 1108 #102 (d): the importer uses #108's core.gpu.INTERRUPTIBLE_TIER_RE (whole-word bid, not/non- excluded)
    for tier, want in (("Bid", True), ("Min bid", True), ("Spot", True), ("Forbidden zone", False),
                       ("Bidirectional NVLink", False), ("Non-interruptible", False), ("Not interruptible", False),
                       ("On-demand (Community Cloud)", False), ("Marketplace on-demand (verified)", False)):
        r = normalize(row(vendor="RunPod", gpu_model="L4 24GB", vram_gb=24, price_usd_hr=0.39, tier=tier, gpu_count=1))
        assert r["interruptible"] is want and r["tier"] == tier, tier
        _valid("RunPod", r)  # record_problems agrees with the importer's flag


def test_scout_price_quote_is_kept_as_verbatim_evidence():
    # Gauge 1108 #102 (c): Scout's real Oblivus row carries the vendor text in price_quote; it is kept verbatim,
    # separate from the importer summary, instead of being replaced by an api_field summary.
    r = normalize(row(vendor="Oblivus", gpu_model="RTX 4090", vram_gb=24, price_usd_hr=0.64, gpu_count=1, tier="On-demand",
                      price_quote="RTX 4090 ... On-Demand: $0.64/hr", source_url="https://oblivus.com/pricing/",
                      source_detail='https://oblivus.com/pricing/ ("RTX 4090" card)', price_basis="per GPU-hour (listed on-demand)"))
    assert r["evidence_kind"] == "verbatim" and r["quote"] == "RTX 4090 ... On-Demand: $0.64/hr"
    assert r["evidence"]["quote"] == r["quote"] and "importer summary" in r["normalized_summary"]
    assert r["source_url"] == "https://oblivus.com/pricing/"


def test_importer_comment_no_longer_says_community_is_interruptible():
    src = (ROOT / "scripts" / "import_scout_wider.py").read_text()
    assert "community and marketplace tiers." not in src and "stay non-interruptible" in src  # main (#116) already fixed the wording
