"""Daily GPU refresh (parse-only updates, stale holds), snapshots/history, the CI change gate, MCP history option."""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import refresh_gpu_prices as R  # noqa: E402
from core import gpu_history as H  # noqa: E402
from core.gpu import build_rates, load_vendor_files, record_problems  # noqa: E402
from core import deals as core  # noqa: E402

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
URL = "https://example.com/pricing"


def rec(price=1.99, quote="NVIDIA A100 SXM 40 GB 30 220 GiB 512 GiB SSD $1.99", tier="On-demand", **kw):
    r = {"vendor": "V", "gpu": "A100 SXM", "vram_gb": 40, "price_usd": price, "billing_unit": "hourly", "hourly_usd": price,
         "interruptible": False, "tier": tier, "form_factor": "SXM", "quote": f"A100 ${price}/hr", "source_url": URL,
         "checked_at": "2026-11-01T10:00:00+00:00",
         "evidence": {"source_url": URL, "quote": quote, "checked_at": "2026-11-01T10:00:00+00:00"}}
    r.update(kw)
    return r


def doc(*records, **kw):
    d = {"vendor": "V", "deal_id": None, "source_url": URL, "checked_at": "2026-11-01T10:00:00+00:00",
         "extras": {k: {"status": "unknown", "text": "x", "source_url": URL} for k in ("egress", "storage", "interruption")},
         "records": list(records)}
    d.update(kw)
    return d


class Fake:
    def __init__(self, body, status=200):
        self.body, self.status, self.calls = body, status, 0

    def get(self, url):
        self.calls += 1
        return self.status, self.body


PAGE = "<html><body><table><tr><td>NVIDIA A100 SXM</td><td>40 GB</td><td>30</td><td>220 GiB</td><td>512 GiB SSD</td><td>$1.89</td></tr></table></body></html>"


def test_parsed_change_updates_price_and_evidence():
    d = doc(rec())
    rows = R.refresh([d], Fake(PAGE), NOW)
    r = d["records"][0]
    assert rows[0]["result"] == "changed" and r["price_usd"] == 1.89 and r["hourly_usd"] == 1.89
    assert r["verified_at"] == r["checked_at"] == r["evidence"]["checked_at"] == "2026-11-03T12:00:00+00:00"
    assert "$1.89" in r["evidence"]["quote"] and r["quote"] == "A100 $1.89/hr"
    assert not record_problems(d)


def test_unchanged_price_still_reverifies():
    d = doc(rec())
    R.refresh([d], Fake(PAGE.replace("1.89", "1.99")), NOW)
    assert d["records"][0]["price_usd"] == 1.99 and d["records"][0]["verified_at"].startswith("2026-11-03")


def test_unreadable_keeps_old_price_and_verified_at():
    d = doc(rec())
    rows = R.refresh([d], Fake("<html>redesigned page $9.99</html>"), NOW)
    r = d["records"][0]
    assert r["price_usd"] == 1.99 and r["verified_at"] == "2026-11-01T10:00:00+00:00"
    assert r["checked_at"].startswith("2026-11-03") and rows[0]["result"].startswith("unreadable")
    assert "stale" not in r  # only 2 days old


def test_unreadable_for_more_than_stale_days_is_held_and_unranked_then_released():
    d = doc(rec())
    R.refresh([d], Fake("", status=503), NOW + timedelta(days=8))
    r = d["records"][0]
    assert r["stale"]["auto"] is True and r["price_usd"] == 1.99
    out = build_rates([], [d])
    assert out["rates"] == [] and out["held_stale"][0]["records"][0]["gpu"] == "A100 SXM"
    R.refresh([d], Fake(PAGE), NOW + timedelta(days=9))
    assert "stale" not in d["records"][0] and build_rates([], [d])["rates"][0]["price_usd"] == 1.89


def test_ambiguous_context_is_unreadable():
    d = doc(rec())
    R.refresh([d], Fake(PAGE + PAGE.replace("1.89", "1.49")), NOW)
    assert d["records"][0]["price_usd"] == 1.99


def test_large_jump_not_auto_applied():
    d = doc(rec())
    rows = R.refresh([d], Fake(PAGE.replace("1.89", "4.99")), NOW)
    assert d["records"][0]["price_usd"] == 1.99 and rows[0]["result"].startswith("NOT applied")


def test_manual_and_vendor_holds_untouched():
    held = rec(stale={"reason": "manual"})
    d = doc(held)
    R.refresh([d], Fake(PAGE), NOW)
    assert d["records"][0]["price_usd"] == 1.99 and d["records"][0]["stale"] == {"reason": "manual"}
    v = doc(rec(), stale={"reason": "vendor page outdated"})
    before = copy.deepcopy(v)
    f = Fake(PAGE)
    R.refresh([v], f, NOW)
    assert v == before and f.calls == 0


def test_aria_hidden_duplicates_and_jsonld_are_handled():
    modal = ('<p>Nvidia H200 SXM</p><span>$<span class="sr-only">0.001261</span>'
             '<span aria-hidden="true">0 . 0 0 1 2 6 1</span></span> / sec')
    t = R.page_text(modal)
    r = rec(price=0.001261, quote="Nvidia H200 SXM $0.001261 / sec", billing_unit="per-second", hourly_usd=4.5396)
    assert R.parse_listed(r, t)[0] == "0.001261"
    ld = ('<script type="application/ld+json">{"@type":"Product","description":"Community Cloud $3.59/hr, '
          'Secure Cloud $5.29/hr."}</script>')
    t = R.page_text(ld)
    sec = rec(price=5.29, tier="Secure Cloud", quote="Community Cloud $3.59/hr, Secure Cloud $5.29/hr.")
    com = rec(price=3.59, tier="Community Cloud", quote="Community Cloud $3.59/hr, Secure Cloud $5.29/hr.")
    assert R.parse_listed(sec, t)[0] == "5.29" and R.parse_listed(com, t)[0] == "3.59"


def test_marketplace_median_and_thin_market_hold():
    offers = [{"dph_total": p, "num_gpus": 1, "gpu_ram": 24 * 1024} for p in (0.4, 0.5, 0.6, 0.7, 0.8)]
    m = rec(price=0.55, gpu="RTX 4090", vram_gb=24, price_status="marketplace", lowest_offer_usd=0.4, offer_count=5,
            price_basis="median", quote="x", evidence={"source_url": URL, "quote": "median $0.55/hr", "checked_at": "2026-11-01T10:00:00+00:00"})
    d = doc(m)
    R.refresh([d], Fake(json.dumps({"offers": offers})), NOW)
    assert d["records"][0]["price_usd"] == 0.6 and d["records"][0]["offer_count"] == 5 and not record_problems(d)
    R.refresh([d], Fake(json.dumps({"offers": offers[:3]})), NOW)
    assert d["records"][0]["stale"]["auto"] and d["records"][0]["price_usd"] == 0.6
    big = [{"dph_total": p, "num_gpus": 1, "gpu_ram": 24 * 1024} for p in (0.5, 0.6, 0.65, 0.7, 0.8, 0.9)]
    R.refresh([d], Fake(json.dumps({"offers": big})), NOW)  # 5+ again: auto hold released with fresh median + evidence
    r = d["records"][0]
    assert "stale" not in r and r["offer_count"] == 6 and r["price_usd"] == 0.675 and r["lowest_offer_usd"] == 0.5
    assert "6 verified" in r["evidence"]["quote"] and r["verified_at"] == r["evidence"]["checked_at"] and not record_problems(d)


def _snap(day, price, status="ranked"):
    d = doc(rec(price=price))
    if status == "held":
        d["records"][0]["stale"] = {"reason": "x"}
    return H.snapshot_doc([d], day)


def test_history_change_points_and_recent_changes():
    h = H.build_history([_snap("2026-11-01", 1.99), _snap("2026-11-02", 1.99), _snap("2026-11-03", 1.89),
                         _snap("2026-11-04", 1.89, "held")])
    s = h["series"][0]
    assert [p["date"] for p in s["points"]] == ["2026-11-01", "2026-11-03", "2026-11-04"]
    assert h["changes"] == [{**h["changes"][0], "date": "2026-11-03", "from_hourly_usd": 1.99, "to_hourly_usd": 1.89, "change_pct": -5.0}]
    assert H.recent_changes(h, days=30) and not H.recent_changes(h, days=30, gpu="H100")
    assert "tracked providers" in h["scope"]


def test_change_gate():
    old = [doc(rec())]
    new = copy.deepcopy(old)
    new[0]["records"][0]["price_usd"] = new[0]["records"][0]["hourly_usd"] = 1.89
    assert H.change_problems(H.base_from_docs(old), new, "base")  # price changed, evidence not updated
    new[0]["records"][0]["evidence"] = {"source_url": URL, "quote": "NVIDIA A100 SXM ... $1.89", "checked_at": "2026-11-03T00:00:00+00:00"}
    assert H.change_problems(H.base_from_docs(old), new, "base") == []
    new[0]["records"][0]["evidence"]["quote"] = "no price"
    assert H.change_problems(H.base_from_docs(old), new, "base")


def test_committed_data_snapshots_and_history():
    snaps = H.load_snapshots()
    assert snaps and snaps[0]["date"] == "2026-10-27"
    for s in snaps:
        keys = [r["key"] for r in s["rows"]]
        assert len(keys) == len(set(keys))
    docs = load_vendor_files()
    assert H.change_problems(H.base_from_snapshot(snaps[-1]), docs, "latest snapshot") == []
    hist = json.loads((ROOT / "api" / "v1" / "gpu-prices" / "history.json").read_text())
    assert hist == {**H.build_history(snaps), "source": hist["source"]}


def test_mcp_compare_include_history():
    data = {"rates": build_rates([], [doc(rec())])["rates"]}
    h = H.build_history([_snap("2026-11-01", 1.99), _snap("2026-11-03", 1.89)])
    data = {"rates": build_rates([], [doc(rec(price=1.89, quote="$1.89"))])["rates"]}
    out = core.compare_gpu_prices(data, "A100", 5, history=h)
    assert out["results"][0]["price_history"] == [{"date": "2026-11-01", "hourly_usd": 1.99, "status": "ranked"},
                                                  {"date": "2026-11-03", "hourly_usd": 1.89, "status": "ranked"}]
    assert out["history"]["recent_changes"][0]["to_hourly_usd"] == 1.89
    assert "history" not in core.compare_gpu_prices(data, "A100", 5)


def test_freshness_check_warns_then_fails():
    import importlib.util
    from datetime import timedelta
    spec = importlib.util.spec_from_file_location("fresh", Path(__file__).resolve().parents[1] / "scripts" / "check_gpu_freshness.py")
    F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
    from core.gpu import load_vendor_files
    last = min(datetime.fromisoformat(r["checked_at"]) for d in load_vendor_files() if not d.get("stale") for r in d["records"])
    assert F.status(last + timedelta(hours=1))[0] == 0
    code, msgs = F.status(last + timedelta(hours=25))
    assert code == 0 and any("::warning::" in m for m in msgs)
    assert F.status(last + timedelta(hours=27))[0] == 1


def test_marketplace_filter_units_and_variants():
    """Per-GPU price = machine dph_total / num_gpus; only the record's VRAM size; no bids, no unverified offers."""
    gb = 1024
    offers = [{"dph_total": 0.5, "num_gpus": 1, "gpu_ram": 24564},
              {"dph_total": 1.2, "num_gpus": 2, "gpu_ram": 24564},          # 2-GPU machine -> 0.60 per GPU
              {"dph_total": 2.4, "num_gpus": 4, "gpu_ram": 24564},          # 4-GPU machine -> 0.60 per GPU
              {"dph_total": 0.7, "num_gpus": 1, "gpu_ram": 49140},          # 48 GB modded 4090: other VRAM, excluded
              {"dph_total": 0.1, "num_gpus": 1, "gpu_ram": 24 * gb, "is_bid": True},          # interruptible bid: excluded
              {"dph_total": 0.2, "num_gpus": 1, "gpu_ram": 24 * gb, "verification": "unverified"},  # excluded
              {"dph_total": 0.3, "num_gpus": 1, "gpu_ram": 24 * gb, "rented": True}]          # excluded
    assert R.market_stats(json.dumps({"offers": offers}), 24) == [0.5, 0.6, 0.6]
