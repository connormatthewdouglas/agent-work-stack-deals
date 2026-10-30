import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cost_pages  # noqa: E402

FEED = json.loads((ROOT / "api/v1/gpu-prices.json").read_text(encoding="utf-8"))


def test_twelve_pages_in_sitemap():
    sm = (ROOT / "sitemap.xml").read_text()
    for slug in cost_pages.GPUS:
        for h in cost_pages.HOURS:
            assert (ROOT / f"cost/{slug}-{h}-hours/index.html").is_file()
            assert f"/cost/{slug}-{h}-hours/" in sm


def test_eligibility_fails_closed():
    held = {h["vendor"] for h in FEED["held_stale"]}
    for fam in cost_pages.GPUS.values():
        for (gpu, vram), rows in cost_pages.eligible(FEED, fam).items():
            for r in rows:
                assert r["tier_class"] == "on-demand" and not r["interruptible"] and (r.get("min_gpus") or 1) == 1
                assert r["advertiser"] not in held and r["billing_unit"] in ("hourly", "per-second")
                assert r["gpu"] == gpu and r["vram_gb"] == vram


def test_pages_math_and_exclusions():
    for p in (ROOT / "cost").glob("*/index.html"):
        s = p.read_text(encoding="utf-8")
        assert "TensorDock" not in s and "Clore" not in s and "Compute subtotal only" in s
        h = int(re.search(r"-(\d+)-hours", str(p)).group(1))
        for rate, sub in re.findall(r'\$/GPU-hr">\$([\d.]+)</td><td data-label="\d+ h subtotal"><strong>\$([\d,.]+)', s):
            assert abs(round(float(rate) * h, 2) - float(sub.replace(",", ""))) < 0.006


def _page(slug, h):
    return (ROOT / f"cost/{slug}-{h}-hours/index.html").read_text(encoding="utf-8")


def test_out_of_stock_ranked_last_and_excluded():
    if not _fresh():
        import pytest
        pytest.skip("Scout snapshot older than 8 h: every Scout stock claim renders unknown (covered by test_0330_*)")
    s = _page("a100", 100)
    assert "stock is not checked here" not in s
    # Scout v2.5 (01:14Z): Lambda A100 SXM/PCIe 40GB out of stock, Verda A100 SXM 40GB available -> out-of-stock items listed last
    sec = s.split("Other variants (not compared)")[1].split("</ul>")[0]
    items = sec.split("<li>")[1:]
    flags = ["out of stock when checked" in i for i in items]
    assert flags == sorted(flags) and any(flags)
    for i in items:  # every out-of-stock row shows its check time (order itself is asserted above)
        if "out of stock when checked" in i:
            assert "out of stock when checked at" in i
    h = _page("h100", 100).split("<h2>H100 SXM 80GB</h2>")[1].split("</table>")[0]
    rows = h.split("<tr>")[2:]  # stock-independent: out-of-stock rows rank after every other row
    oos = ["out of stock when checked" in r for r in rows]
    assert oos == sorted(oos)


def test_unlabelled_and_nvlink_variants_named_not_mixed():
    s = _page("a100", 100)
    # 0.3.27: unlabelled A100 80GB now has 4+ vendors (Thunder, Jarvislabs, Civo, E2E) so it is its own compared table, never mixed with SXM/PCIe
    sec = s.split("<h2>A100 80GB</h2>")[1].split("</table>")[0]
    assert "Thunder Compute" in sec and "Civo" in sec and "SXM" not in sec and "Hyperstack A100 NVLink 80GB" in s
    assert "Hyperstack H100 NVLink 80GB" in _page("h100", 100)


def test_ovh_marked_ex_tax_and_index_page_linked():
    assert "OVHcloud (US) (excl. tax/VAT)" in _page("l40s", 100)
    assert (ROOT / "cost/index.html").is_file() and "/cost/</loc>" in (ROOT / "sitemap.xml").read_text()
    assert 'href="https://thelanternworks.com/cost/"' in (ROOT / "gpu/index.html").read_text()


def test_rtx4090_has_cheapest_line_with_3_plus_vendors():
    import json
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    ok = {r["advertiser"] for r in feed["rates"] if r["gpu"] == "RTX 4090" and r["tier_class"] == "on-demand"
          and not r["interruptible"] and r["availability"].get("in_stock") is not False}
    assert len(ok) >= 3
    for h in (10, 100, 730):
        sec = _page("rtx-4090", h).split("<h2>RTX 4090 24GB</h2>")[1].split("</p>")[0]
        assert "Cheapest RTX 4090 24GB among tracked providers:" in sec and "No &#x27;cheapest" not in sec



def test_h1_scoped_cheapest_and_page_lowest():
    a = _page("a100", 100)
    assert "Cheapest among tracked providers" not in a
    assert "Cheapest A100 SXM 80GB among tracked providers: CloudRift at $105.00" in a
    assert ("Lowest on-demand A100 on this page (not marked out of stock): Jarvislabs A100 40GB (variant not stated) at "
            "$8.90 / $89.00 / $649.70") in a
    for slug in ("h100", "l40s"):
        assert "on this page (not marked out of stock)" in _page(slug, 10)
    assert "CloudRift L40S 48GB at $6.30" in _page("l40s", 10)


def test_h2_availability_wording_all_pages():
    for slug in ("h100", "a100", "l40s", "rtx-4090"):
        for h in (10, 100, 730):
            assert "Not an availability claim, except rows marked out of stock when checked." in _page(slug, h)


def test_i1_rtx4090_page_lowest_line_from_feed():
    for h in (10, 100, 730):
        s = _page("rtx-4090", h)
        assert "only 2" not in s and "No &#x27;cheapest" not in s
    assert ("Lowest on-demand RTX 4090 on this page (not marked out of stock): Nova Cloud and RunC.AI (tie) RTX 4090 24GB at "
            "$4.20 / $42.00 / $306.60 (10 / 100 / 730 h)") in _page("rtx-4090", 100)
    assert "Lowest in-stock" not in "".join(_page(g, 100) for g in ("a100", "h100", "l40s", "rtx-4090"))
    assert "static page label" in (ROOT / "gpu/rtx-4090/index.html").read_text() if (ROOT / "gpu/rtx-4090/index.html").exists() else True


def test_j_site_wording():
    for g in ("a100", "h100"):
        for h in (10, 100, 730):
            s = _page(g, h)
            assert "only in-stock vendor" not in s
    assert "Listed but not ranked: no second vendor offers this exact variant in stock (form factor and memory); variants are never mixed; rows marked out of stock come last." in _page("h100", 100) + _page("a100", 100)
    inst = (ROOT / "install/index.html").read_text()
    from core.deals import VERSION
    assert inst.count("version 0.3.23") == inst.count("history: tested on version 0.3.23") and f"current version {VERSION}" in inst
    cheap = (ROOT / "gpu/cheapest-rtx-4090-rental/index.html").read_text()
    assert "Nova Cloud and RunC.AI (tie) RTX 4090" in cheap
    exp = "Where a status is shown, it is a snapshot from the time in the row, not a guarantee."
    for p in ("gpu/price-comparison/index.html", "gpu/cheapest-rtx-4090-rental/index.html", "tools/gpu-cost-calculator/index.html"):
        t = (ROOT / p).read_text()
        assert "separate later check" not in t and "separate, later check" not in t
    assert exp in (ROOT / "gpu/price-comparison/index.html").read_text()
    assert exp in (ROOT / "lanternworks/index.html").read_text()
    import glob
    specs = [open(f).read() for f in glob.glob(str(ROOT / "gpu/*/index.html"))]
    assert any("vendor-labelled" in t and exp in t for t in specs)


def test_j3_page_ties_match_mcp_rule():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import gpu_pages as gp
    class G:
        esc = staticmethod(lambda s: s)
    base = {"gpu": "X", "tier_class": "on-demand", "hourly_equiv_usd": 0.42}
    rows = [{**base, "advertiser": "B"}, {**base, "advertiser": "A"}, {**base, "advertiser": "C", "hourly_equiv_usd": 0.5}]
    assert gp._tied_names(G, rows, rows[0]) == "A and B (tie)"
    assert gp._tied_names(G, rows[2:], rows[2]) == "C"


def test_j5_explainer_not_doubled():
    import glob
    for f in glob.glob(str(ROOT / "gpu/*/index.html")):
        assert "Where a status is shown, Where" not in open(f).read()


def test_0327_new_h100_a100_rows_live_and_sourced():
    import json
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    want = {("Jarvislabs", "H100"), ("Civo", "H100"), ("Oblivus", "H100"), ("E2E Networks", "H100"),
            ("Jarvislabs", "A100"), ("Civo", "A100"), ("Oblivus", "A100"), ("E2E Networks", "A100"), ("CloudRift", "A100")}
    got = {(r["advertiser"], r["gpu"].split()[0]) for r in feed["rates"]}
    assert want <= got
    for r in feed["rates"]:
        if r["advertiser"] in {"Jarvislabs", "Civo", "Oblivus", "E2E Networks"}:
            assert r["region"] and not r["interruptible"] and r["tier_class"] == "on-demand"
            if r["advertiser"] != "Oblivus":
                assert r["availability"]["in_stock"] is None
    ob = [r for r in feed["rates"] if r["advertiser"] == "Oblivus"]
    assert ob
    for r in ob:  # J6: quote and stock count from the same capture
        a = r["availability"]
        if a.get("availability_stale"):  # expired same-capture stock: unknown, never an old in-stock claim
            assert a["in_stock"] is None and a["checked_at"] == r["verified_at"]
            continue
        if "stock_level" not in a:  # Scout-sourced claim (v3.x), not the same-capture page count
            continue
        assert a["in_stock"] is (int(a["stock_level"]) > 0)
        assert a["same_capture_as_price"] and a["checked_at"] == r["verified_at"]
        assert f"Available Stock {a['stock_level']} " in r["evidence"]["quote"] and "(count shown on the vendor page, changes often)" in a["detail"]
    for slug in ("h100", "a100"):
        s = _page(slug, 100)
        for v in ("Jarvislabs", "Civo", "Oblivus", "E2E Networks"):
            assert v in s
    assert "Massed Compute" not in _page("h100", 100)


def test_0327_old_note_cleared_and_tie_rule_shared():
    old = "Stock changes within minutes"
    for f in ("api/v1/gpu-prices.json", "api/v1/gpu/a100.json", "api/v1/gpu/h100.json", "api/v1/gpu/rtx-4090.json",
              "tools/gpu-cost-calculator/index.html"):
        assert old not in (ROOT / f).read_text(), f
    from core import gpu_availability as ga
    assert ga.NOTE == ga.STOCK_EXPLAINER and ga.NOTE.startswith("Where a status is shown")
    import core.deals as d, scripts.gpu_pages as gp
    assert gp.tie_label is d.tie_label
    rows = [{"advertiser": "A", "gpu": "H100", "tier": "On-demand", "hourly_equiv_usd": 2.0, "availability": {}},
            {"advertiser": "B", "gpu": "H100", "tier": "On-demand", "hourly_equiv_usd": 2.0, "availability": {}}]
    assert d.tie_label(rows, rows[0]) == "A and B (tie)"


def test_j7_regions_cite_supporting_urls():
    import json
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    reg = {r["advertiser"]: r["region"] for r in feed["rates"] if r["advertiser"] in {"E2E Networks", "Civo", "Jarvislabs", "Oblivus"}}
    assert "https://www.e2enetworks.com/pricing.md" in reg["E2E Networks"] and "INR" not in reg["E2E Networks"]
    assert "https://www.civo.com/docs/overview/regions" in reg["Civo"] and "MON1" in reg["Oblivus"] and "India" in reg["Jarvislabs"]


def test_j8_cheapest_a100_summary_names_memory_sizes():
    s = (ROOT / "gpu/cheapest-a100-rental/index.html").read_text()
    # K1: the out-of-stock Verda spot row now ranks last, so the overall cheapest is the on-demand Jarvislabs 40GB row
    # Scout v2.5: the Verda spot row is back in stock, so it is the overall cheapest again; the on-demand clause carries J8
    # stock-independent: whether the J8 clause leads or follows a cheaper in-stock spot row depends on Scout's snapshot
    import re
    assert re.search(r"Jarvislabs A100 40GB \(On-demand\)(</strong>)? at \$89\.00", s)
    assert "\u2014 memory sizes differ; cheapest A100 80GB among tracked providers: CloudRift A100 SXM 80GB at $105.00" in s


def test_index_a100_is_80gb_only():
    import json
    idx = json.loads((ROOT / "api/v1/gpu-price-index.json").read_text())
    assert idx["series_vram_gb"]["A100"] == 80
    import sys; sys.path.insert(0, str(ROOT / "scripts")); import gpu_index
    assert gpu_index.series_of({"gpu": "A100", "vram_gb": 40}) is None and gpu_index.series_of({"gpu": "A100", "vram_gb": 80}) == "A100"
    assert gpu_index.series_of({"gpu": "A100", "vram_gb": None}) is None
    assert "A100 series is 80 GB only" in (ROOT / "docs/GPU-INDEX-METHODOLOGY.md").read_text()


def test_j8_80gb_clause_covers_every_variant_from_feed():
    import json, re
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    c = [r for r in feed["rates"] if r["gpu"].split()[0] == "A100" and r.get("vram_gb") == 80 and r["tier_class"] == "on-demand"
         and r["availability"].get("in_stock") is not False]
    b = min(c, key=lambda r: (r["hourly_equiv_usd"], r["advertiser"]))
    s = (ROOT / "gpu/cheapest-a100-rental/index.html").read_text()
    m = re.search(r"cheapest A100 80GB among tracked providers: (.*?) at \$([\d,]+\.\d\d)", s)
    assert m and m.group(1).startswith(b["advertiser"]) and float(m.group(2).replace(",", "")) == round(b["hourly_equiv_usd"] * 100, 2)


def _ranked_rows(slug):
    import re
    s = (ROOT / f"gpu/cheapest-{slug}-rental/index.html").read_text()
    return [re.findall(r"<tr.*?</tr>", t.split("</tbody>")[0], re.S) for t in s.split("<tbody>")[1:]]  # one list per table


def test_k1_cheapest_pages_rank_out_of_stock_last():
    import glob
    for p in glob.glob(str(ROOT / "gpu/cheapest-*-rental/index.html")):
        slug = p.split("cheapest-")[1].split("-rental")[0]
        for table in _ranked_rows(slug):
            seen = False
            for r in table:
                o = "out of stock when checked" in r
                assert not (seen and not o), (slug, r[:200])
                seen |= o


def test_k2_cost_a100_any_variant_80gb_line_from_feed():
    import json
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    c = [r for r in feed["rates"] if r["gpu"].split()[0] == "A100" and r.get("vram_gb") == 80 and r["tier_class"] == "on-demand"
         and not r["interruptible"] and r["availability"].get("in_stock") is not False]
    b = min(c, key=lambda r: (r["hourly_equiv_usd"], r["advertiser"]))
    want = (f"Cheapest A100 80GB (any variant) among tracked providers: {b['advertiser']} {b['gpu']} 80GB at "
            + " / ".join(f"${b['hourly_equiv_usd'] * h:,.2f}" for h in (10, 100, 730)))
    assert want == "Cheapest A100 80GB (any variant) among tracked providers: CloudRift A100 SXM 80GB at $10.50 / $105.00 / $766.50"
    for h in (10, 100, 730):
        assert want in _page("a100", h)


def test_scout_v25_lambda_clore_render():
    import json
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    if not _fresh():  # stale snapshot: Lambda/Clore claims are unknown, the Lambda auth label stays
        lam = [r["availability"] for r in feed["rates"] if r["advertiser"] == "Lambda" and r["availability"].get("origin") == "scout"]
        assert lam and all(a["in_stock"] is None and a.get("availability_stale") for a in lam if a.get("checked_at"))
        for slug in ("a100", "h100", "rtx-4090", "l40s"):
            assert "Clore.ai" not in "".join(_page(slug, h) for h in (10, 100, 730))
        return
    lam = [r for r in feed["rates"] if r["advertiser"] == "Lambda" and r["availability"].get("in_stock") is not None]
    assert lam and all(r["availability"]["source_label"] == "authenticated vendor API (not publicly reproducible)" for r in lam)
    cl = [r for r in feed["rates"] if r["advertiser"] == "Clore.ai" and r["availability"].get("in_stock") is not None]
    assert cl and all("offer_count" not in r["availability"] and r["availability"]["unrented_servers"] > 0 for r in cl)
    s = (ROOT / "gpu/cheapest-rtx-4090-rental/index.html").read_text()
    assert "unrented servers (one server may hold several GPUs)" in s
    for slug in ("a100", "h100", "rtx-4090", "l40s"):
        assert "Clore.ai" not in "".join(_page(slug, h) for h in (10, 100, 730))
    av = json.loads((ROOT / "data/gpu_availability/latest.json").read_text())
    assert av["imported_rows"] == len(av["rows"]) >= 25
    for r in feed["rates"]:  # every row Scout checked shows its checked_at, unknown included
        a = r["availability"]
        if a.get("source") and "runpod" in a["source"] and a["in_stock"] is None:
            assert a["status"] == "unknown" and a["checked_at"]


def test_k2_mcp_a100_summary_names_cheapest_80gb():
    import json, sys
    sys.path.insert(0, str(ROOT))
    from core import deals as D
    data = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    out = D.compare_gpu_prices(data, "A100", on_demand_only=True)
    assert "Memory sizes differ (cheapest 80GB: CloudRift A100 SXM 80GB at $1.05/hr, On-demand)" in out["summary"]


def _fresh():
    import json
    from datetime import datetime, timezone
    from core.gpu_availability import AVAIL_MAX_AGE_H, age_hours
    c = json.loads((ROOT / "data/gpu_availability/latest.json").read_text())["collected_at"]
    h = age_hours(c)
    return h is not None and h <= AVAIL_MAX_AGE_H


def test_0330_other_variants_intro_and_in_stock_time():
    s = _page("a100", 100)
    sec = s.split("Other variants (not compared)")[1].split("</ul>")[0]
    assert "Listed but not ranked: no second vendor offers this exact variant in stock (form factor and memory); variants are never mixed; rows marked out of stock come last." in sec
    if _fresh() and "(available when checked" in sec:  # pages built from a fresh snapshot: in-stock rows show their check time like out-of-stock rows
        assert "(available when checked at 20" in sec and "; valid until " in sec and "after that treat as unknown)" in sec and "data-av-expires=" in sec
    assert ("<!-- av-stale -->" in s) == ("data-av-checked" in s)  # expiry script wherever a dated claim is shown


def test_0330_stale_guard_unit():
    from datetime import datetime, timedelta, timezone
    from core.gpu_availability import stale_guard
    t = datetime(2026, 10, 30, 1, 14, 24, tzinfo=timezone.utc)
    a = {"status": "available when checked", "in_stock": True, "checked_at": "2026-10-30T01:14:24Z", "origin": "scout",
         "source_label": "authenticated vendor API (not publicly reproducible)"}
    assert stale_guard(a, t + timedelta(hours=7.9)) is a
    s = stale_guard(a, t + timedelta(hours=9))
    assert s["in_stock"] is None and s["availability_stale"] is True
    assert s["status"] == "unknown (stale availability, last checked 2026-10-29 21:14 ET)"
    rec = {"status": "out of stock when checked", "in_stock": False, "checked_at": "2026-10-01T00:00:00Z", "origin": "record"}
    assert stale_guard(rec, t)["in_stock"] is None  # record-level (J6 same-capture) stock expires the same way
    assert stale_guard({"in_stock": False, "checked_at": "2026-10-01T00:00:00Z"}, t)["in_stock"] is False  # no origin: untouched


def test_0330_mcp_stale_rows_unknown_not_ranked_last():
    import json
    from datetime import datetime, timedelta, timezone
    from core import deals as D
    data = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
    # clock-independent: anchor on the newest stock check in the built feed, not a fixed snapshot time or wall clock
    from core.gpu_availability import _parse
    checks = [_parse(r["availability"]["checked_at"]) for r in data["rates"]
              if isinstance(r.get("availability"), dict) and r["availability"].get("origin") == "scout" and r["availability"].get("checked_at")]
    assert checks
    t = max(checks)
    fresh = D.compare_gpu_prices(data, "A100", limit=25, now=t + timedelta(minutes=1))
    stale = D.compare_gpu_prices(data, "A100", limit=25, now=t + timedelta(hours=9))
    scout = [r for r in stale["results"] if (r.get("availability") or {}).get("origin") == "scout"]
    assert scout and all(r["in_stock"] is None for r in scout)
    assert all(r["availability"].get("availability_stale") for r in scout if r["availability"].get("checked_at"))
    assert "stale availability" not in fresh["summary"]
    assert "available when checked" not in stale["summary"] and "out of stock when checked" not in stale["summary"]
    # stale rows are not ranked out-of-stock-last: pure price order among non-reserved rows
    p = [r["hourly_usd"] for r in stale["results"] if r["tier_class"] != "reserved"]
    assert p == sorted(p)
    if fresh["results"][0]["in_stock"] is True:
        c = fresh["results"][0]["availability"]["checked_at"].replace("T", " ")[:16]
        assert f"available when checked {c}Z" in fresh["summary"]


def test_0330_import_refuses_old_snapshot(tmp_path):
    import json, subprocess, sys
    src = json.loads((ROOT / "data/gpu_availability/latest.json").read_text())
    rows = [dict(r, availability_checked_at="2020-01-01T00:00:00Z", in_live_feed=True) for r in src["rows"]]
    f = tmp_path / "old.json"
    f.write_text(json.dumps({"version": "2.5", "rows": rows}))
    before = (ROOT / "data/gpu_availability/latest.json").read_bytes()
    p = subprocess.run([sys.executable, str(ROOT / "scripts/import_scout_availability.py"), str(f)], capture_output=True, text=True)
    assert p.returncode != 0 and "refusing to import" in (p.stderr + p.stdout)
    assert (ROOT / "data/gpu_availability/latest.json").read_bytes() == before


def test_re17_expires_at_on_every_stock_claim():
    import json
    from datetime import timedelta
    from core.gpu_availability import AVAIL_MAX_AGE_H, _parse
    feeds = [json.loads((ROOT / "api/v1/gpu-prices.json").read_text())["rates"]]
    feeds += [json.loads(p.read_text()).get("rows") or [] for p in (ROOT / "api/v1/gpu").glob("*.json") if p.name != "index.json"]
    n = 0
    for rows in feeds:
        for r in rows:
            a = r.get("availability") if isinstance(r.get("availability"), dict) else {}
            if a.get("in_stock") is None:
                assert "availability_expires_at" not in a or a.get("availability_stale") is None
                continue
            n += 1
            assert _parse(a["availability_expires_at"]) == _parse(a["checked_at"]) + timedelta(hours=AVAIL_MAX_AGE_H)
    assert n or not _fresh()
    fa = (ROOT / "for-agents/index.html").read_text()
    assert "availability_expires_at" in fa and "after that treat as unknown" in fa
    assert "availability_expires_at" in (ROOT / "llms.txt").read_text()
