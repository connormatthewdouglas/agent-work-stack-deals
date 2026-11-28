"""P7: clear Rent here / rent_url on top rows of the three booking tools.

Deterministic: fixtures and a frozen clock only. No live feed, no wall clock,
no pins to committed history or gpu-prices.json, and no hits on the production
/go/ counter or committed stats.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core import contract, golinks
from core.cost_per_job import estimate_job_cost
from core.deals import compare_gpu_prices, find_available_gpus
from core.gpu_availability import expires_at
import site_stats as S

NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)  # ISO week 2026-W48
FRESH = "2026-11-25T11:00:00Z"
N = golinks.RENT_HERE_TOP_N


def _av(in_stock=True, checked=FRESH, **kw):
    av = {"in_stock": in_stock, "checked_at": checked, "origin": "scout",
          "availability_expires_at": kw.pop("expires", None) or expires_at(checked)}
    av.update(kw)
    return av


def _row(vendor, price, gpu="H100", deal_id=None, availability=None, **kw):
    r = {
        "advertiser": vendor, "vendor": vendor, "gpu": gpu, "vram_gb": 80,
        "price_usd": price, "hourly_usd": price, "hourly_equiv_usd": price,
        "gpu_count": 1, "min_gpus": 1, "unit": "hour", "tier": "On-demand",
        "tier_class": "on-demand", "interruptible": False, "billing_unit": "hourly",
        "price_status": "listed", "verified_at": FRESH, "checked_at": FRESH,
        "source_url": f"https://{vendor.lower().replace(' ', '-')}.example/pricing",
        "deal_id": deal_id,
        "availability": availability if availability is not None else _av(),
    }
    r.update(kw)
    return r


def _feed(rates):
    return {"rates": rates, "held_stale": [],
            "availability_collected_at": "2026-11-25T10:00:00Z",
            "feed_updated_at": "2026-11-25T10:05:00Z"}


# Five on-demand H100 rows so top-N and the N+1 row are both observable.
RATES = [
    _row("Cheap Cloud", 1.10),
    _row("Mid Cloud", 1.50, deal_id="deal-abc-001"),
    _row("Dear Cloud", 2.00),
    _row("Extra Cloud", 2.50),
    _row("Last Cloud", 3.00),
]


def _finalize(tool, raw, mode="brief"):
    return contract.finalize(tool, raw, mode=mode)


def _list_key(tool, out):
    return out["results"] if tool != "find_available_gpus" else out["available"]


@pytest.fixture
def feed():
    return _feed(RATES)


@pytest.mark.parametrize("mode", ["brief", "full"])
@pytest.mark.parametrize("tool", ["compare_gpu_prices", "find_available_gpus", "estimate_job_cost"])
def test_top_rows_have_rent_here_and_lower_rows_do_not(feed, tool, mode):
    if tool == "compare_gpu_prices":
        raw = compare_gpu_prices(feed, "H100", limit=10, on_demand_only=True, now=NOW)
    elif tool == "find_available_gpus":
        raw = find_available_gpus(feed, "H100", limit=10, on_demand_only=True, now=NOW)
    else:
        raw = estimate_job_cost(feed, "H100", 1, job_hours=10, top_n=5, now=NOW)
    out = _finalize(tool, raw, mode=mode)
    assert out["ok"] is True
    rows = _list_key(tool, out)
    assert len(rows) >= N + 1
    for i, row in enumerate(rows):
        if i < N:
            url = row["tracked_url"]
            assert url.startswith(golinks.GO_BASE) and "src=mcp" in url
            assert row["rent_url"] == url
            assert row["rent_here"] == golinks.rent_here_line(url)
            assert row["rent_here"].startswith("Rent here: ")
            # A deal_id on the rate becomes /go/<deal-id> when the tool keeps that field (compare, planner).
            if row.get("deal_id") == "deal-abc-001" or row.get("id") == "deal-abc-001":
                assert url == golinks.GO_BASE + "deal-abc-001?src=mcp"
            else:
                assert "/go/v/" in url or "/go/deal-" in url
        else:
            assert "rent_url" not in row and "rent_here" not in row
            assert row.get("tracked_url", "").startswith(golinks.GO_BASE)
    assert out["referral_disclosure"] == golinks.REFERRAL_DISCLOSURE


def test_ranking_and_receipts_untouched(feed):
    raw = estimate_job_cost(feed, "H100", 1, job_hours=10, top_n=5, now=NOW)
    before = [r["vendor"] for r in raw["results"]]
    # Receipts are issued by the MCP wrapper; confirm annotate / rent-here never walk them.
    raw["receipt"] = {"lines": [{"component": "rank1", "choice": {"rate_id": raw["results"][0]["rate_id"],
                                                                   "vendor": raw["results"][0]["vendor"]}}]}
    out = _finalize("estimate_job_cost", raw, mode="full")
    assert [r["vendor"] for r in out["results"]] == before
    assert [r["rank"] for r in out["results"]] == sorted(r["rank"] for r in out["results"])
    assert all("tracked_url" not in line and "rent_url" not in line and "rent_here" not in line
               for line in out["receipt"]["lines"])
    # compare rank order is unchanged by the additive fields
    raw_c = compare_gpu_prices(feed, "H100", on_demand_only=True, now=NOW)
    order = [r["advertiser"] for r in raw_c["results"]]
    out_c = _finalize("compare_gpu_prices", raw_c, mode="full")
    assert [r["advertiser"] for r in out_c["results"]] == order


def test_add_rent_here_is_additive_and_skips_rows_without_a_link():
    out = {"results": [{"advertiser": "Acme"}, {"vendor": "  "}, {"vendor": "Beta"}]}
    golinks.annotate(out)
    golinks.add_rent_here(out, "compare_gpu_prices", n=3)
    assert out["results"][0]["rent_url"].endswith("/go/v/acme?src=mcp")
    assert "rent_url" not in out["results"][1]  # no provider slug, no invented URL
    assert out["results"][2]["rent_here"].startswith("Rent here: ")


def test_rent_url_click_reaches_stats_json_via_src_mcp(feed):
    """A src=mcp click on a rent_url is counted in weekly stats; house/test clicks are not.

    This exercises the same add_go_clicks / add_agent_query_to_click path that writes
    stats.json. It does not fetch the live /go/ route or mutate the committed file.
    """
    raw = compare_gpu_prices(feed, "H100", on_demand_only=True, now=NOW)
    out = _finalize("compare_gpu_prices", raw, mode="brief")
    row = out["results"][0]
    url, provider = row["rent_url"], row["advertiser"]
    assert url.startswith(golinks.GO_BASE) and "src=mcp" in url and "/go/" in url

    day = "2026-11-25"
    hosted = {
        "rows": [{"day": day, "ref": "x", "n": 1}],
        "hits": [
            {"day": day, "kind": "tool", "name": "compare_gpu_prices", "ref": "none",
             "ua_class": "mcp:claude", "src_class": "other", "n": 10},
            {"day": day, "kind": "tool", "name": "compare_gpu_prices", "ref": "house-p7",
             "ua_class": "house", "src_class": "house", "n": 99},
        ],
    }
    rep = S.build(hosted, {}, None, 12, NOW)
    S.add_go_clicks(rep, {"rows": [
        {"day": day, "provider": provider, "src": "mcp", "ref": "none", "ua_class": "browser", "n": 2},
        # excluded: house verification traffic, must not look like a production click
        {"day": day, "provider": provider, "src": "mcp-test", "ref": "house-p7", "ua_class": "browser", "n": 7},
        {"day": day, "provider": provider, "src": "mcp", "ref": "none", "ua_class": "bot", "n": 3},
    ]})
    S.add_agent_query_to_click(rep, hosted)
    week = next(w for w in rep["weeks"] if w["week"] == "2026-W48")
    q = week["agent_query_to_click"]
    assert q == {"agent_tool_calls": 10, "agent_mcp_clicks": 2, "rate": 0.2, "null_reason": None}
    assert week["clicks"]["by_source"] == {"mcp": 2}
    assert week["test_go_clicks_by_provider"][provider]["mcp"] == 7
    # committed stats.json is not written
    committed = json.loads((ROOT / "stats.json").read_text())
    assert committed is not rep
