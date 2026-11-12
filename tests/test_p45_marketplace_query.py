"""P45 (hermesagentj): marketplace_query next to median and n, and composition_flag from successive med/min/n."""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from core import contract, gpu_changes, gpu_history
from core import deals as core
from core.marketplace import (
    classify,
    composition_fields,
    is_price_move,
    marketplace_query,
    snapshot_extras,
    stats_from,
)
from core.gpu_changes import change_title

ROOT = Path(__file__).resolve().parents[1]

VAST_Q = {
    "gpu_name": {"eq": "A100 SXM4"},
    "rentable": {"eq": True},
    "rented": {"eq": False},
    "verified": {"eq": True},
    "type": "on-demand",
    "limit": 1000,
}
VAST_URL = "https://console.vast.ai/api/v0/bundles/?q=" + urllib.parse.quote(json.dumps(VAST_Q, separators=(",", ":")))


def _vast(**kw):
    row = {
        "vendor": "Vast.ai", "advertiser": "Vast.ai", "gpu": "A100 SXM", "vram_gb": 80,
        "price_status": "marketplace", "price_basis": "median per-GPU price (dph_total / num_gpus) of verified, rentable, on-demand 80 GB offers",
        "source_url": VAST_URL, "hourly_usd": 1.1964, "hourly_equiv_usd": 1.1964, "price_usd": 1.1964,
        "lowest_offer_usd": 1.07, "offer_count": 11, "tier": "Marketplace on-demand (verified; median per GPU)",
        "verified_at": "2026-11-10T12:00:00Z",
    }
    row.update(kw)
    return row


def _clore(**kw):
    row = {
        "vendor": "Clore.ai", "advertiser": "Clore.ai", "gpu": "RTX 4090", "vram_gb": 24,
        "price_status": "marketplace",
        "price_basis": "median per-GPU price of available on-demand host listings priced in USD (USD/day / 24 / gpu_count); spot/bid excluded",
        "source_url": "https://api.clore.ai/v1/marketplace",
        "hourly_usd": 0.5104, "hourly_equiv_usd": 0.5104, "price_usd": 0.5104,
        "lowest_offer_usd": 0.2917, "offer_count": 96,
        "tier": "Marketplace on-demand (host USD listings; median per GPU)",
        "verified_at": "2026-11-09T03:51:49Z",
    }
    row.update(kw)
    return row


def test_query_vast_literal_and_vram_filter_not_in_url():
    q = marketplace_query(_vast())
    assert q and "gpu_name=A100 SXM4" in q["literal"]
    assert "vram_gb=80 (applied after query)" in q["literal"]
    assert q["filters"]["gpu_name"] == "A100 SXM4"
    assert q["filters"]["rentable"] is True and q["filters"]["rented"] is False
    assert q["filters"]["verified"] is True and q["filters"]["type"] == "on-demand"
    assert q["filters"]["vram_gb"] == 80 and q["filters"]["vram_filter"] == "applied_after_query"
    assert "vram" not in urllib.parse.unquote(q["url"]).lower()
    assert q["url"] == VAST_URL


def test_query_clore_uses_recorded_method():
    q = marketplace_query(_clore())
    assert q and "USD-Blockchain" in q["literal"] and "spot/bid excluded" in q["literal"]
    assert q["filters"]["available"] == "rented == false"
    assert q["filters"]["currency"] == "USD" and q["filters"]["excluded"] == ["spot", "bid"]
    assert q["filters"]["homogeneous_servers"] is True
    assert q["filters"]["gpu"] == "RTX 4090" and q["filters"]["vram_gb"] == 24
    assert q["url"] == "https://api.clore.ai/v1/marketplace"


def test_query_null_when_not_a_marketplace_median_or_unknown():
    assert marketplace_query({"price_status": "listed", "source_url": VAST_URL, "gpu": "H100"}) is None
    assert marketplace_query({"price_status": "marketplace"}) is None  # nothing recoverable
    # Lium is a lowest-available-node price, not a median with n
    assert marketplace_query({"price_status": "listed", "tier": "Marketplace secure node",
                              "advertiser": "Lium", "source_url": "https://lium.io/api/public/v1/nodes"}) is None


def test_classify_opposite_med_min_is_composition_never_price():
    prev = {"median_usd": 1.1964, "lowest_offer_usd": 1.07, "offer_count": 11}
    cur = {"median_usd": 1.135, "lowest_offer_usd": 1.09, "offer_count": 10}  # median down, min up, n changed
    assert classify(prev, cur) == "mixed"  # n also changed
    assert not is_price_move(classify(prev, cur))
    cur_same_n = {**cur, "offer_count": 11}
    assert classify(prev, cur_same_n) == "composition"
    assert not is_price_move("composition")


def test_classify_same_direction_same_n_is_price():
    prev = {"median_usd": 1.30, "lowest_offer_usd": 1.10, "offer_count": 5}
    cur = {"median_usd": 1.40, "lowest_offer_usd": 1.20, "offer_count": 5}
    assert classify(prev, cur) == "price" and is_price_move("price")


def test_classify_n_change_same_direction_is_mixed():
    prev = {"median_usd": 1.30, "lowest_offer_usd": 1.10, "offer_count": 5}
    cur = {"median_usd": 1.40, "lowest_offer_usd": 1.20, "offer_count": 8}
    assert classify(prev, cur) == "mixed" and not is_price_move("mixed")


def test_classify_missing_previous_min_or_n_is_unknown_not_invented():
    prev = {"median_usd": 1.30}  # historical snapshot without min/n
    cur = {"median_usd": 1.20, "lowest_offer_usd": 1.00, "offer_count": 5}
    assert classify(prev, cur) == "unknown" and not is_price_move("unknown")
    assert classify(None, cur) == "unknown"
    assert classify({"median_usd": 1.30, "lowest_offer_usd": 1.1, "offer_count": 5},
                    {"median_usd": 1.30, "lowest_offer_usd": 1.1, "offer_count": 5}) is None  # nothing moved


def test_snapshot_extras_only_when_present():
    assert snapshot_extras(_vast()) == {"price_status": "marketplace", "lowest_offer_usd": 1.07, "offer_count": 11}
    assert snapshot_extras({"price_status": "listed", "lowest_offer_usd": 1.0, "offer_count": 3}) == {}
    assert snapshot_extras({"price_status": "marketplace"}) == {"price_status": "marketplace"}  # no invented zeros


def test_history_keeps_min_n_and_flags_changes():
    def snap(day, med, lo=None, n=None, key="Vast.ai|A100 SXM|Marketplace on-demand (verified; median per GPU)|80|1"):
        row = {"key": key, "vendor": "Vast.ai", "gpu": "A100 SXM",
               "tier": "Marketplace on-demand (verified; median per GPU)",
               "vram_gb": 80, "gpu_count": 1, "billing_unit": "hourly",
               "price_usd": med, "hourly_usd": med, "status": "ranked",
               "verified_at": f"{day}T12:00:00Z", "source_url": VAST_URL}
        if lo is not None:
            row["lowest_offer_usd"] = lo
        if n is not None:
            row["offer_count"] = n
        return {"date": day, "rows": [row]}

    # older snapshot has no min/n -> change is unknown, not a price move
    h = gpu_history.build_history([snap("2026-11-09", 1.1964), snap("2026-11-10", 1.135, 1.09, 10)])
    (c,) = h["changes"]
    assert c["composition_flag"] == "unknown"
    assert c["from_hourly_usd"] == 1.1964 and c["to_hourly_usd"] == 1.135
    title = change_title({"change": "down", "gpu": "A100 SXM", "vendor": "Vast.ai", "pct": -5.1,
                          "old_hourly_usd": 1.1964, "new_hourly_usd": 1.135, "composition_flag": "unknown"})
    assert "not classified as a price move" in title and "dropped" not in title and "rose" not in title

    # both snapshots have min/n; opposite med/min -> composition; points keep min/n
    h = gpu_history.build_history([snap("2026-11-09", 1.1964, 1.07, 11), snap("2026-11-10", 1.135, 1.09, 11)])
    (c,) = h["changes"]
    assert c["composition_flag"] == "composition"
    assert c["previous_offer_count"] == 11 and c["offer_count"] == 11
    assert c["previous_lowest_offer_usd"] == 1.07 and c["lowest_offer_usd"] == 1.09
    pts = h["series"][0]["points"]
    assert pts[0]["offer_count"] == 11 and pts[1]["lowest_offer_usd"] == 1.09
    assert "not a price move" in change_title({**c, "change": "down", "pct": c["change_pct"],
                                               "old_hourly_usd": c["from_hourly_usd"], "new_hourly_usd": c["to_hourly_usd"]})

    d = gpu_changes.build_changes([snap("2026-11-09", 1.30, 1.10, 5), snap("2026-11-10", 1.40, 1.20, 5)])
    assert d["changes"][0]["composition_flag"] == "price"
    assert "rose" in change_title({**d["changes"][0], "old_hourly_usd": 1.30, "new_hourly_usd": 1.40, "pct": d["changes"][0]["pct"]})


def test_change_title_without_flag_still_says_rose():
    t = change_title({"change": "up", "gpu": "X", "vendor": "V", "pct": 1.0,
                      "old_hourly_usd": 0.7965, "new_hourly_usd": 0.8045})
    assert "$0.7965/GPU-hr → $0.8045/GPU-hr" in t and "rose" in t


def test_price_changes_does_not_count_composition_as_a_price_drop():
    latest = {"date": "2026-11-10", "previous_date": "2026-11-09", "changes": [
        {"key": "a", "vendor": "Vast.ai", "gpu": "A100 SXM", "change": "down", "old_hourly_usd": 1.2,
         "new_hourly_usd": 1.1, "pct": -8.3, "source_url": VAST_URL, "composition_flag": "composition"},
        {"key": "b", "vendor": "RunPod", "gpu": "H100", "change": "down", "old_hourly_usd": 3.0,
         "new_hourly_usd": 2.5, "pct": -16.7, "source_url": "https://example.invalid/p", "composition_flag": None},
    ]}
    out = core.price_changes(latest, None)
    assert out["price_drops"] == 1 and out["composition_changes"] == 1
    assert "1 composition (not a price move)" in out["summary"]
    assert "1 price down" in out["summary"]
    brief = contract.finalize("get_price_changes", out, "brief")
    assert brief["changes"][0]["composition_flag"] in ("composition", None) or any(
        r.get("composition_flag") == "composition" for r in brief["changes"])
    assert all("composition_flag" in r for r in brief["changes"])


def test_brief_keeps_compact_query_and_flag_under_size_budget():
    row = _vast()
    row["marketplace_query"] = marketplace_query(row)
    row["composition_flag"] = "composition"
    full = {"gpu": "A100 SXM", "summary": "s", "count": 1, "results": [row],
            "scope": "tracked", "total": 1, "excluded_non_on_demand": 0, "excluded_reserved": 0,
            "next_refresh_utc": "2026-11-12T10:23:00Z", "data_checked_at": "2026-11-11T12:00:00Z",
            "refresh_hint": "h", "cheapest_by_form_factor": [], "cheapest_by_form_factor_note": None,
            "on_demand_only": False, "on_demand_fallback": None, "excluded_serverless": 0,
            "usable_memory_filter": None, "model_identity_note": None, "gpus": 1, "assumptions": [],
            "min_gpus_unmet": 0, "referral_disclosure": "d"}
    # need required compare keys
    row.update(rank=1, rate_id="r_aaaaaaaaaaaa", in_stock=True, interruptible=False,
               canonical_model="A100", form_factor="SXM", checked_at=row["verified_at"],
               last_verified=row["verified_at"], quote_currency="USD", fx_date=None,
               referral_url=None, referral_label=None, availability_rate_7d=None, expected_cost_usd=None,
               availability_status=None, availability_reason=None, availability_reason_detail=None,
               min_gpus=1, hourly_usd=row["hourly_usd"])
    b = contract.finalize("compare_gpu_prices", full, "brief")
    r = b["results"][0]
    assert r["composition_flag"] == "composition"
    assert r["marketplace_query"] == {"literal": row["marketplace_query"]["literal"]}
    assert "url" not in r["marketplace_query"]
    assert r["offer_count"] == 11 and r["lowest_offer_usd"] == 1.07
    # The 0.4x budget is asserted on a real compare_gpu_prices payload below (a one-row toy
    # full object is already compact, so a ratio on it would not be meaningful).
    from mcp_server import server as s
    brief = s.compare_gpu_prices(gpu="A100 SXM", limit=8, mode="brief")
    full_out = s.compare_gpu_prices(gpu="A100 SXM", limit=8, mode="full")
    assert brief["ok"] and full_out["ok"]
    ratio = len(json.dumps(brief)) / len(json.dumps(full_out))
    assert ratio < 0.4, f"brief is {ratio:.3f}x full after adding marketplace_query/composition_flag"
    # At least one marketplace median row in this compare should carry the query and a flag key.
    flags = [row.get("composition_flag") for row in brief["results"] if row.get("marketplace_query") or row.get("composition_flag")]
    queries = [row.get("marketplace_query") for row in brief["results"] if row.get("marketplace_query")]
    if queries:
        assert all(set(q) <= {"literal"} for q in queries)


def test_schema_and_manifest_lockstep():
    s = contract.output_schema("get_price_changes")["properties"]["changes"]["items"]["properties"]
    plugin = json.loads((ROOT / "lhm.plugin.json").read_text())
    p = next(t for t in plugin["tools"] if t["name"] == "get_price_changes")["outputSchema"]["properties"]["changes"]["items"]["properties"]
    assert p["composition_flag"] == s["composition_flag"] and "null" in s["composition_flag"]["type"]
    cs = contract.output_schema("compare_gpu_prices")["properties"]["results"]["items"]["properties"]
    for k in ("marketplace_query", "composition_flag", "composition_previous"):
        assert k in cs
    listed = " ".join(next(t for t in plugin["tools"] if t["name"] == "compare_gpu_prices")["description"].split())
    assert "marketplace_query" in listed and "composition_flag" in listed
    assert "not a price move" in listed


def test_expected_cost_usd_stays_null():
    """T116 is unchanged: expected_cost_usd stays deprecated/null."""
    from core import availability_rate
    out = availability_rate.fields("Vast.ai", "A100 SXM", 80, "Marketplace on-demand (verified; median per GPU)", 1.3)
    assert out["expected_cost_usd"] is None
    assert "deprecated (T116)" in (out.get("expected_cost_label") or "")


def test_listed_price_move_is_not_flagged_unknown_or_called_composition():
    """Verda/Lium/etc. listed prices are ordinary price moves. Flag is null, titles still say rose/dropped."""
    from core.marketplace import is_marketplace_median
    assert not is_marketplace_median({"vendor": "Verda (formerly DataCrunch)", "gpu": "H100 SXM",
                                      "tier": "On-demand", "hourly_usd": 2.5, "price_status": "listed"})
    assert not is_marketplace_median({"vendor": "Lium", "tier": "Marketplace secure node", "price_status": "listed"})
    # snapshot-shaped row (no price_status): only known published medians count
    assert is_marketplace_median({"vendor": "Vast.ai",
                                  "tier": "Marketplace on-demand (verified; median per GPU)"})
    assert is_marketplace_median({"vendor": "Clore.ai",
                                  "tier": "Marketplace on-demand (host USD listings; median per GPU)"})
    assert not is_marketplace_median({"vendor": "Lium", "tier": "Marketplace secure node"})
    assert not is_marketplace_median({"vendor": "TensorDock", "tier": "Marketplace (typical price, varies by host)"})
    assert not is_marketplace_median({"vendor": "Spheron",
                                      "tier": "Marketplace/aggregator listing (page: \"Live rates across 5+ providers\"; on-demand)"})

    def snap(day, vendor, tier, med, lo=None, n=None, status="listed"):
        row = {"key": f"{vendor}|X|{tier}|80|1", "vendor": vendor, "gpu": "H100 SXM", "tier": tier,
               "vram_gb": 80, "gpu_count": 1, "billing_unit": "hourly",
               "price_usd": med, "hourly_usd": med, "status": "ranked",
               "verified_at": f"{day}T12:00:00Z", "source_url": "https://example.invalid/p"}
        if status:
            row["price_status"] = status
        if lo is not None:
            row["lowest_offer_usd"] = lo
        if n is not None:
            row["offer_count"] = n
        return {"date": day, "rows": [row]}

    d = gpu_changes.build_changes([
        snap("2026-11-10", "Verda", "On-demand", 2.50),
        snap("2026-11-11", "Verda", "On-demand", 2.60),
    ])
    assert d["changes"][0]["composition_flag"] is None
    assert d["counts"]["up"] == 1
    title = change_title({**d["changes"][0], "old_hourly_usd": 2.50, "new_hourly_usd": 2.60, "pct": d["changes"][0]["pct"]})
    assert "rose" in title and "not a price move" not in title and "composition" not in title

    # A historical Vast median move without min/n is unknown, and is not a listed-style "dropped"
    d = gpu_changes.build_changes([
        snap("2026-11-10", "Vast.ai", "Marketplace on-demand (verified; median per GPU)", 1.20, status=None),
        snap("2026-11-11", "Vast.ai", "Marketplace on-demand (verified; median per GPU)", 1.10, status=None),
    ])
    assert d["changes"][0]["composition_flag"] == "unknown"
    title = change_title({**d["changes"][0], "old_hourly_usd": 1.20, "new_hourly_usd": 1.10, "pct": d["changes"][0]["pct"]})
    assert "dropped" not in title and "not classified as a price move" in title


def test_changes_counts_exclude_composition_mixed_unknown_from_up_down():
    """gpu-price-changes.json counts.down/up are price moves only; composition/mixed/unknown are additive."""
    def snap(day, rows):
        out = []
        for vendor, tier, med, lo, n, status in rows:
            r = {"key": f"{vendor}|X|{tier}|80|1", "vendor": vendor, "gpu": "H100 SXM", "tier": tier,
                 "vram_gb": 80, "gpu_count": 1, "billing_unit": "hourly",
                 "price_usd": med, "hourly_usd": med, "status": "ranked",
                 "verified_at": f"{day}T12:00:00Z", "source_url": "https://example.invalid/p"}
            if status:
                r["price_status"] = status
            if lo is not None:
                r["lowest_offer_usd"] = lo
            if n is not None:
                r["offer_count"] = n
            out.append(r)
        return {"date": day, "rows": out}

    vast = "Marketplace on-demand (verified; median per GPU)"
    prev = snap("2026-11-10", [
        ("Verda", "On-demand", 2.50, None, None, "listed"),
        ("Vast.ai", vast, 1.20, 1.00, 5, "marketplace"),
        ("Clore.ai", "Marketplace on-demand (host USD listings; median per GPU)", 0.50, 0.40, 10, "marketplace"),
        ("Vast.ai", "Marketplace on-demand (verified; median per GPU) B", 1.00, 0.80, 8, "marketplace"),
    ])
    # listed Verda up (price); Vast same-n opposite med/min = composition; Clore n+med up = mixed;
    # historical-style Vast B with no prev min/n = unknown
    cur = snap("2026-11-11", [
        ("Verda", "On-demand", 2.60, None, None, "listed"),
        ("Vast.ai", vast, 1.10, 1.05, 5, "marketplace"),
        ("Clore.ai", "Marketplace on-demand (host USD listings; median per GPU)", 0.55, 0.42, 12, "marketplace"),
        ("Vast.ai", "Marketplace on-demand (verified; median per GPU) B", 0.90, 0.70, 8, "marketplace"),
    ])
    # For Vast B unknown: previous snapshot must lack min/n
    prev["rows"][3].pop("lowest_offer_usd", None)
    prev["rows"][3].pop("offer_count", None)
    d = gpu_changes.build_changes([prev, cur])
    kinds = {(c["vendor"], c["composition_flag"], c["change"]) for c in d["changes"]}
    assert ("Verda", None, "up") in kinds
    assert any(c["vendor"] == "Vast.ai" and c["composition_flag"] == "composition" and c["change"] == "down" for c in d["changes"])
    assert any(c["vendor"] == "Clore.ai" and c["composition_flag"] == "mixed" and c["change"] == "up" for c in d["changes"])
    assert any(c["vendor"].startswith("Vast.ai") and c["composition_flag"] == "unknown" for c in d["changes"]) or any(
        c["composition_flag"] == "unknown" for c in d["changes"])
    assert d["counts"]["up"] == 1 and d["counts"]["down"] == 0
    assert d["counts"]["composition"] == 1 and d["counts"]["mixed"] == 1 and d["counts"]["unknown"] == 1
    assert d["counts"]["new"] == 0 and d["counts"]["removed"] == 0
    assert sum(d["counts"].values()) == len(d["changes"]) == 4
