"""Gauge rel053 blocker: a price with no source (source_url plus a check date) is never shown anywhere.
DataImpulse (no source_url, no verified_at) stays listed label-only; this covers every place a deal price can appear."""
import glob, html, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from core.price_label import is_sourced, shown_price  # noqa: E402

MONEY = re.compile(r"[$€£₹]\s?\d|\d\s?€|¢")
DEALS = json.loads((ROOT / "deals.json").read_text())["deals"]
UNSOURCED = [d for d in DEALS if not is_sourced(d)]
DI = next(d for d in DEALS if d["id"] == "deal-dataimpulse-001")


def _pages():
    for f in glob.glob(str(ROOT / "compare/*/index.html")):
        t = Path(f).read_text()
        if 'http-equiv="refresh"' not in t:
            yield f, t


def test_helper_and_dataimpulse_is_unsourced():
    assert not is_sourced(DI) and shown_price(DI) is None
    assert not is_sourced({"price_usd": 5, "source_url": "https://x"})  # a source with no check date is not enough
    assert shown_price({"price_usd": 5, "source_url": "https://x", "verified_at": "2026-11-02"}) == 5


def test_feed_has_no_dataimpulse_price():
    for p in ("deals.json", "api/v1/deals.json"):
        d = next(x for x in json.loads((ROOT / p).read_text())["deals"] if x["id"] == DI["id"])
        assert d["price_usd"] is None and d["list_price_usd"] is None, p
        assert not MONEY.search(" ".join(str(d.get(k) or "") for k in ("unit", "pricing_note", "title"))), p


def test_stack_pricing_offers_are_all_sourced_and_dataimpulse_unpriced():
    sp = json.loads((ROOT / "api/v1/stack-pricing.json").read_text())
    assert sp["offers"]
    for o in sp["offers"]:
        assert o.get("source_url") and o.get("checked_at"), o.get("vendor")
        assert o.get("vendor") != "DataImpulse"
    assert "DataImpulse" not in json.dumps(sp["offers"])


def test_compare_tables_and_pros_cons_show_no_unsourced_price():
    names = {d["advertiser"]: d for d in UNSOURCED}
    seen_di = False
    for f, t in _pages():
        for row in re.findall(r"<tr><td><a href=\"[^\"]+\">([^<]+)</a></td>(.*?)</tr>", t, re.S):
            d = names.get(html.unescape(row[0]))
            if d and d["id"] in t:
                pass
            if html.unescape(row[0]) == "DataImpulse":
                seen_di = True
            if d:  # a cited GPU rate label (its own source_url + checked_at in data/gpu_pricing) is allowed
                cell = re.sub(r"From \$[\d.]+/GPU-hr \([^)]*\), checked \d{4}-\d\d-\d\d", "", html.unescape(re.sub("<[^>]+>", " ", row[1])))
                assert not MONEY.search(cell), (f, row[0])
        for name, body in re.findall(r"<h3><a href=\"[^\"]+\">([^<]+)</a></h3>(.*?)(?=<h3>|</section>|$)", t, re.S):
            if html.unescape(name) in names:
                assert not MONEY.search(html.unescape(re.sub("<[^>]+>", " ", body.split("<h2")[0]))), (f, name)
    assert seen_di  # still listed, label only


def test_dataimpulse_on_residential_page_is_label_only():
    t = (ROOT / "compare/cheapest-residential-proxies/index.html").read_text()
    row = re.search(r"DataImpulse</a></td>(.*?)</tr>", t, re.S).group(1)
    assert "Pricing on vendor site" in row and not MONEY.search(row)
    pc = re.search(r"DataImpulse</a></h3>(.*?)(?=<h3>)", t, re.S).group(1)
    assert "No verified public price" in pc and not MONEY.search(pc)


def test_price_blocks_have_only_sourced_rows():
    for f, t in _pages():
        m = re.search(r'id="lw-price-block">(.*?)</script>', t, re.S)
        items = json.loads(m.group(1).replace("<\\/", "</"))["items"]
        for i in items:
            assert i.get("source_url") and i.get("checked_at"), (f, i.get("vendor"))
        assert not any(i["vendor"] == "DataImpulse" for i in items), f


def test_deal_pages_show_no_unsourced_price():
    import generate_seo_pages as g
    for d in UNSOURCED:
        assert "$" not in re.sub(r"<[^>]+>", "", g.price_bits(d)) or g.deal_price_label(d) in g.price_bits(d), d["id"]
        assert "\"price\"" not in g.json_ld(d, "https://x"), d["id"]
        assert 'data-price=""' in g.filter_attrs(d), d["id"]
    page = (ROOT / "deals/dataimpulse-001/index.html").read_text()
    assert "Pricing on vendor site" in page


def test_api_v1_feed_nulls_unsourced_prices_additively():
    src = json.loads((ROOT / "deals.json").read_text())["deals"]
    v1 = {d["id"]: d for d in json.loads((ROOT / "api/v1/deals.json").read_text())["deals"]}
    fly = v1["deal-fly-trial-001"]
    assert fly["price_usd"] is None and fly["price_null_reason"] == "no cited price"
    for d in src:  # additive: nothing removed or renamed; only prices of unsourced deals change
        o = v1[d["id"]]
        assert set(d) <= set(o)
        if is_sourced(d):
            assert o == d
        else:
            assert o["price_usd"] is None and o["list_price_usd"] is None and o["price_null_reason"] == "no cited price"
            assert {k: v for k, v in o.items() if k not in ("price_usd", "list_price_usd", "price_null_reason")} == \
                   {k: v for k, v in d.items() if k not in ("price_usd", "list_price_usd")}


def test_mcp_tools_never_return_unsourced_price(monkeypatch):
    monkeypatch.setenv("LANTERN_DEALS_FILE", str(ROOT / "deals.json"))  # even from the raw source feed
    from core import deals as cd
    assert cd.cite_guard({"id": "x", "price_usd": 0})["price_null_reason"] == "no cited price"
    s = {"id": "y", "price_usd": 3, "source_url": "https://v", "verified_at": "2026-11-02"}
    assert cd.cite_guard(s) is s
    assert "price_null_reason" in cd.PUBLIC_FIELDS and "price_null_reason" in cd.SUMMARY_FIELDS


def test_deploy_serves_guarded_alias():
    w = (ROOT / ".github/workflows/validate-and-deploy.yml").read_text()
    assert "cp _site/api/v1/deals.json _site/deals.json" in w
