"""Gauge rel053/re1: MCP get_deal / search_deals / compare_deals never return an uncited price (Fly.io trial $0),
in brief and full mode; source_url and price_null_reason are present (additive)."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def _server(monkeypatch, feed):
    monkeypatch.setenv("LANTERN_DEALS_FILE", str(ROOT / feed))
    sys.path.insert(0, str(ROOT))
    import importlib
    from mcp_server import server
    server = importlib.reload(server)
    return server


def _check(row):
    assert row["price_usd"] is None and row["price_null_reason"] == "no cited price"
    assert row["source_url"] == "https://fly.io/docs/about/pricing/"


def test_fly_unsourced_price_null_in_every_mode(monkeypatch):
    for feed in ("deals.json", "api/v1/deals.json"):  # raw source feed and the served feed
        s = _server(monkeypatch, feed)
        for mode in ("brief", "full"):
            g = s.get_deal(id="deal-fly-trial-001", mode=mode)
            assert g["ok"], g
            _check(g)
            r = s.search_deals(query="fly", mode=mode)
            fly = [x for x in r["results"] if x["id"] == "deal-fly-trial-001"]
            assert fly, r
            _check(fly[0])
            c = s.compare_deals(ids=["deal-fly-trial-001", "deal-9proxy-001"], mode=mode)
            _check([x for x in c["deals"] if x["id"] == "deal-fly-trial-001"][0])


def test_sourced_deal_unchanged_and_has_source_url(monkeypatch):
    s = _server(monkeypatch, "api/v1/deals.json")
    import json
    src = next(d for d in json.loads((ROOT / "deals.json").read_text())["deals"]
               if d.get("price_usd") is not None and d.get("source_url") and d.get("verified_at"))
    g = s.get_deal(id=src["id"], mode="brief")
    assert g["price_usd"] == src["price_usd"] and g["source_url"] == src["source_url"] and "price_null_reason" not in g
