"""Single-GPU headlines go through core price rank and skip min_gpus above 1.

core.deals.gpu_rate_rank_key is price-only. It does not read min_gpus, so
compare_gpu_prices still ranks a cheaper N-GPU row first. The site skips those
rows when it names a single-GPU price. Affiliate status is not a rank input.
Reserved rates are never the headline.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from core.deals import compare_gpu_prices, gpu_rate_rank_key  # noqa: E402
import gpu_pages  # noqa: E402
import spec_pages  # noqa: E402
from gpu_model_json import build  # noqa: E402

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


def _row(vendor, price, *, min_gpus=1, tier="On-demand", tier_class="on-demand", affiliate=False,
         in_stock=None, gpu="H100 SXM", billing_unit="hourly"):
    r = {
        "advertiser": vendor, "gpu": gpu, "vram_gb": 80, "hourly_equiv_usd": price, "price_usd": price,
        "unit": "hour", "tier": tier, "tier_class": tier_class, "billing_unit": billing_unit,
        "interruptible": tier_class == "interruptible", "min_gpus": min_gpus, "gpu_count": min_gpus,
        "affiliate": affiliate, "verified_at": (NOW - timedelta(hours=2)).isoformat(),
        "source_url": f"https://example.com/{vendor}",
    }
    if in_stock is not None:
        r["availability"] = {"in_stock": in_stock}
    return r


MULTI = _row("Vast", 0.40, min_gpus=8, tier="On-demand (8x GPU)")
SINGLE = _row("RunPod", 1.99, affiliate=True)
DEARER = _row("Lambda", 3.50, affiliate=False)
OOS = _row("CheapOOS", 0.15, in_stock=False)
RESERVED = _row("CommitCo", 0.05, tier="Reserved 1-year", tier_class="reserved")
SPOT_MULTI = _row("Lium", 0.20, min_gpus=2, tier="Spot", tier_class="interruptible")
SPOT_SINGLE = _row("Hyperstack", 0.90, tier="Spot", tier_class="interruptible")


def test_engine_rank_does_not_skip_min_gpus():
    """The engine was not changed to exclude multi-GPU rows. A cheaper 8-GPU row still ranks first."""
    data = {"rates": [SINGLE, MULTI, RESERVED], "feed_updated_at": NOW.isoformat()}
    out = compare_gpu_prices(data, "H100", now=NOW, on_demand_only=False, include_reserved=True)
    assert out["results"][0]["advertiser"] == "Vast"
    assert out["results"][0]["min_gpus"] == 8
    assert gpu_rate_rank_key(MULTI) < gpu_rate_rank_key(SINGLE)


def test_rank_key_ignores_affiliate_and_min_gpus_value():
    a = _row("A", 1.0, affiliate=False)
    b = _row("A", 1.0, affiliate=True)
    assert gpu_rate_rank_key(a) == gpu_rate_rank_key(b)
    hi = _row("A", 1.0, min_gpus=8)
    assert gpu_rate_rank_key(a) == gpu_rate_rank_key(hi)


def test_gpu_pages_headline_skips_cheaper_multi_reserved_and_oos():
    rows = [MULTI, OOS, RESERVED, DEARER, SINGLE]
    picked = gpu_pages._pick_cheapest(rows)
    assert picked["advertiser"] == "RunPod"
    assert gpu_pages.min_gpus_count(picked) == 1
    assert picked["tier_class"] != "reserved"
    hourly = gpu_pages.hourly_single(rows)
    assert hourly[0]["advertiser"] == "RunPod"
    assert all(gpu_pages.min_gpus_count(r) <= 1 and r["tier_class"] != "reserved" for r in hourly)
    flipped = [dict(r, affiliate=not r["affiliate"]) for r in rows]
    assert [r["advertiser"] for r in gpu_pages.rank_rates(rows)] == [r["advertiser"] for r in gpu_pages.rank_rates(flipped)]
    assert gpu_pages.min_gpus_phrase(MULTI) == "8x GPU minimum"
    assert gpu_pages.min_gpus_phrase(SINGLE) == ""
    assert "8x GPU minimum" in gpu_pages._rate_str(MULTI)


def test_spec_heads_skip_multi_gpu_minimums():
    rows = [MULTI, SINGLE, SPOT_MULTI, SPOT_SINGLE, RESERVED]
    od = spec_pages.on_demand_head(rows)
    sp = spec_pages.spot_head(rows)
    assert od["advertiser"] == "RunPod" and spec_pages.gp.min_gpus_count(od) == 1
    assert sp["advertiser"] == "Hyperstack" and sp["hourly_equiv_usd"] == 0.90
    assert "2x GPU minimum" in spec_pages.price_cell(type("G", (), {})(), SPOT_MULTI)


def test_model_json_cheapest_skips_multi_gpu_rows():
    fam = {"name": "H100", "rates": [MULTI, SINGLE, RESERVED, SPOT_MULTI, SPOT_SINGLE]}
    doc = build("h100", fam, "https://example.com")
    named = [r["provider"] for rows in doc["cheapest"].values() for r in rows]
    assert "Vast" not in named and "CommitCo" not in named and "Lium" not in named
    assert "RunPod" in named and "Hyperstack" in named
    assert any(r.get("min_gpus") == 8 for r in doc["rows"])
    assert "commission" not in json.dumps(doc).lower()


def _h100(vendor, price, form, **kw):
    r = _row(vendor, price, gpu=f"H100 {form}" if form != "not stated" else "H100", **kw)
    r["form_factor"] = form
    return r


def test_form_factor_headline_skips_cheaper_eight_gpu_row():
    """An 8-GPU row can be the engine's cheapest SXM and still must not be the page line."""
    rows = [
        _h100("Vast", 0.40, "SXM", min_gpus=8),
        _h100("RunPod", 1.99, "SXM"),
        _h100("Lambda", 3.50, "PCIe"),
    ]
    heads = dict(gpu_pages.form_factor_heads(rows))
    assert heads["SXM"]["advertiser"] == "RunPod" and heads["SXM"]["min_gpus"] == 1
    assert heads["PCIe"]["advertiser"] == "Lambda"
    html = gpu_pages._form_split(type("G", (), {"esc": staticmethod(lambda s: s)})(), rows)
    assert "Vast" not in html and "0.40" not in html and "0.4" not in html
    assert "RunPod" in html and "1.99" in html


def test_form_factor_only_multi_gpu_says_no_single_gpu_rate():
    rows = [
        _h100("Vast", 0.40, "SXM", min_gpus=8),
        _h100("RunPod", 2.10, "PCIe"),
    ]
    heads = dict(gpu_pages.form_factor_heads(rows))
    assert heads["SXM"] is None
    assert heads["PCIe"]["advertiser"] == "RunPod"
    html = gpu_pages._form_split(type("G", (), {"esc": staticmethod(lambda s: s)})(), rows)
    assert "H100 SXM" in html and "no single-GPU rate" in html
    assert "Vast" not in html and "0.40" not in html


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_embed_rank_matches_core_and_skips_multi_gpu():
    node = r"""
const r = require(process.argv[1]);
const rows = JSON.parse(process.argv[2]);
const head = r.singleGpuHeadline(rows);
const order = r.rankGpuRates(rows).map(x => x.advertiser);
process.stdout.write(JSON.stringify({head: head && head.advertiser, order, label: r.minGpusLabel(rows[0])}));
"""
    rows = [MULTI, SINGLE, OOS, RESERVED, DEARER]
    proc = subprocess.run(
        ["node", "-e", node, str(ROOT / "embed" / "rank.js"), json.dumps(rows)],
        capture_output=True, text=True, check=True,
    )
    got = json.loads(proc.stdout)
    assert got["head"] == "RunPod"
    assert got["order"] == [r["advertiser"] for r in gpu_pages.rank_rates(rows)]
    assert got["label"] == "8x GPU minimum"
    js = (ROOT / "embed" / "badge.js").read_text(encoding="utf-8")
    rank = (ROOT / "embed" / "rank.js").read_text(encoding="utf-8").split("if (typeof module", 1)[0].strip()
    assert rank in js
    assert "cheapest" not in js.lower()
    assert "isSingleGpuRate" in js
    assert "headlineEligible" in js


def _gen():
    return type("G", (), {"BASE": "https://example.com", "esc": staticmethod(lambda s: str(s)),
                          "slug_for": staticmethod(lambda deal_id: "x")})()


def _table(rows):
    for r in rows:
        r.setdefault("monthly_cost_usd", round((r.get("price_usd") or 0) * 100, 2))
        r.setdefault("billing", r.get("tier") or "")
    full = {gpu_pages._key(r): r["monthly_cost_usd"] for r in rows}
    return gpu_pages._table_one(_gen(), rows, full)


def test_l40s_koyeb_stays_in_table_labeled_serverless_and_is_not_cheapest():
    """Koyeb is hourly and on-demand, so only the serverless tier keeps it out of the headline."""
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text(encoding="utf-8"))
    l40s = [r for r in feed["rates"] if "L40S" in (r.get("gpu") or "")]
    koyeb = next(r for r in l40s if r["advertiser"] == "Koyeb")
    assert gpu_pages.is_serverless(koyeb)
    assert koyeb.get("billing_unit") == "hourly"
    assert (koyeb.get("tier_class") or "on-demand") == "on-demand"
    pick = gpu_pages._pick_cheapest(l40s)
    assert pick is not None and pick["advertiser"] != "Koyeb"
    cheap = dict(koyeb)
    cheap["hourly_equiv_usd"] = 0.01
    cheap["price_usd"] = 0.01
    again = gpu_pages._pick_cheapest([cheap, _row("CloudRift", 0.69, gpu="L40S")])
    assert again["advertiser"] == "CloudRift"
    html = _table([koyeb, _row("CloudRift", 0.69, gpu="L40S")])
    row = next(line for line in html.split("<tr") if "Koyeb" in line)
    assert "serverless" in row.lower()
    bare = _row("Func", 0.02, tier="Per-call GPU", billing_unit="per-second")
    bare["billing"] = "function, per second"
    marked = _table([bare])
    assert "[serverless]" in marked
    assert gpu_pages._pick_cheapest([bare, SINGLE])["advertiser"] == "RunPod"
    page = (ROOT / "gpu" / "l40s-rental-price" / "index.html").read_text(encoding="utf-8")
    assert "Koyeb" in page and "serverless" in page.lower()


def test_home_spread_skips_cheaper_serverless_and_multi_gpu():
    import home_page
    rates = [
        _row("Koyeb", 0.05, gpu="H100 SXM", tier="Serverless GPU instance (per-second billing)"),
        _row("Vast", 0.01, gpu="H100 SXM", min_gpus=8),
        _row("RunPod", 1.99, gpu="H100 SXM"),
        _row("Lambda", 4.00, gpu="H100 PCIe"),
    ]
    got = {s["slug"]: s for s in home_page.spread(rates)}
    assert got["h100"]["cheapest_vendor"] == "RunPod"
    assert got["h100"]["min"] == 1.99
    assert got["h100"]["cheapest_price"] == 1.99
    assert "Koyeb" not in got["h100"]["cheapest_vendor"]


def test_form_factor_headline_skips_cheaper_serverless():
    rows = [
        _h100("Koyeb", 0.10, "SXM", tier="Serverless GPU instance (per-second billing)"),
        _h100("RunPod", 1.99, "SXM"),
        _h100("Lambda", 3.50, "PCIe"),
    ]
    heads = dict(gpu_pages.form_factor_heads(rows))
    assert heads["SXM"]["advertiser"] == "RunPod"
    assert heads["PCIe"]["advertiser"] == "Lambda"
    html = gpu_pages._form_split(type("G", (), {"esc": staticmethod(lambda s: s)})(), rows)
    assert "Koyeb" not in html and "0.10" not in html
    assert "RunPod" in html


def test_model_json_cheapest_skips_serverless():
    modal = _row("Modal", 0.02, tier="Serverless, preemptible (per second)", tier_class="interruptible",
                 billing_unit="per-second")
    fam = {"name": "H100", "rates": [modal, MULTI, SINGLE, RESERVED]}
    doc = build("h100", fam, "https://example.com")
    named = [r["provider"] for rows in doc["cheapest"].values() for r in rows]
    assert "Modal" not in named and "serverless" not in doc["cheapest"]
    assert "RunPod" in named
    assert any(r["provider"] == "Modal" for r in doc["rows"])


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_calculator_and_home_js_share_rank_eligibility():
    """The calculator and homepage inline isServerlessRate and headlineEligible from embed/rank.js."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from embed_page import eligibility_js
    slice_js = eligibility_js().strip()
    pages = [
        ROOT / "index.html",
        ROOT / "tools" / "gpu-cost-calculator" / "index.html",
        ROOT / "embed" / "badge.js",
    ]
    for page in pages:
        assert slice_js in page.read_text(encoding="utf-8"), page
    calc = (ROOT / "tools" / "gpu-cost-calculator" / "index.html").read_text(encoding="utf-8")
    assert "cur.filter(headlineEligible)" in calc
    home = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "headlineEligible(r)" in home
    feed = json.loads((ROOT / "api/v1/gpu-prices.json").read_text(encoding="utf-8"))["rates"]
    cases = [
        _row("Koyeb", 0.01, tier="Serverless GPU instance (per-second billing)", billing_unit="hourly"),
        _row("Modal", 0.02, tier="Serverless, preemptible (per second)", tier_class="interruptible",
             billing_unit="per-second"),
        _row("Func", 0.03, tier="Per-call GPU", billing_unit="per-second"),
        MULTI, RESERVED, SINGLE,
    ]
    cases[2]["billing"] = "function, per second"
    slim_feed = [{k: r.get(k) for k in ("advertiser", "gpu", "tier", "tier_class", "billing", "billing_unit", "min_gpus")}
                 for r in feed]
    assert [gpu_pages.headline_eligible(r) for r in slim_feed] == [gpu_pages.headline_eligible(r) for r in feed]
    node = r"""
const rank = require(process.argv[1]);
const cases = JSON.parse(process.argv[3]);
const feed = JSON.parse(process.argv[4]);
eval(process.argv[2]);
const picks = cases.filter(headlineEligible).map(r => r.advertiser);
const agree = function(rows){
  return rows.every(function(r){
    return headlineEligible(r) === rank.headlineEligible(r) && isServerlessRate(r) === rank.isServerlessRate(r);
  });
};
process.stdout.write(JSON.stringify({
  picks: picks,
  caseFlags: cases.map(headlineEligible),
  feedFlags: feed.map(headlineEligible),
  agree: agree(cases) && agree(feed),
  head: rank.singleGpuHeadline(cases) && rank.singleGpuHeadline(cases).advertiser
}));
"""
    proc = subprocess.run(
        ["node", "-e", node, str(ROOT / "embed" / "rank.js"), slice_js, json.dumps(cases), json.dumps(slim_feed)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    assert got["picks"] == ["RunPod"]
    assert got["head"] == "RunPod"
    assert got["agree"]
    assert got["caseFlags"] == [gpu_pages.headline_eligible(r) for r in cases]
    assert got["feedFlags"] == [gpu_pages.headline_eligible(r) for r in slim_feed]


def test_gpu_pages_table_keeps_multi_gpu_labeled_and_pick_skips_it():
    """A cheaper 8-GPU row stays in the table, labeled, and is not _pick_cheapest."""
    rows = [MULTI, SINGLE]
    assert gpu_pages._pick_cheapest(rows)["advertiser"] == "RunPod"
    html = _table(rows)
    vast = next(line for line in html.split("<tr") if "Vast" in line)
    assert "8x GPU minimum" in vast
    assert "8-GPU" in vast
    runpod = next(line for line in html.split("<tr") if "RunPod" in line)
    assert "8x GPU minimum" not in runpod


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_calculator_default_pick_skips_multi_gpu_and_serverless():
    """The generator and the published page name a single-GPU instance, not a cheaper serverless or min_gpus row."""
    py = (ROOT / "scripts" / "gpu_calculator.py").read_text(encoding="utf-8")
    page = (ROOT / "tools" / "gpu-cost-calculator" / "index.html").read_text(encoding="utf-8")
    assert "cur.filter(headlineEligible)" in py
    assert "cur.filter(headlineEligible)" in page
    src = re_search_script(page)
    i = src.index("const R=")
    _obj, end = json.JSONDecoder().raw_decode(src, i + len("const R="))
    fresh = datetime.now(timezone.utc).isoformat()
    multi = _row("Vast", 0.02, min_gpus=8, gpu="H100 SXM")
    multi["gpu_count"] = 1
    multi["billing"] = "hourly"
    koyeb = _row("Koyeb", 0.01, gpu="H100 SXM", tier="Serverless GPU instance (per-second billing)")
    koyeb["billing"] = "serverless, per-second billing"
    single = _row("RunPod", 1.99, gpu="H100 SXM")
    single["billing"] = "hourly"
    for r in (multi, koyeb, single):
        r["verified_at"] = fresh
        r["redeem_url"] = r["source_url"]
        r["deal_id"] = r["advertiser"]
        r["basis"] = "listed"
        r["affiliate"] = False
    src = "const R=" + json.dumps([multi, koyeb, single]) + src[end:]
    stub = r"""
const els={}; function el(id){ if(!els[id]) els[id]={id,value:"",checked:true,href:"",textContent:"",tBodies:[{innerHTML:""}],addEventListener(){}}; return els[id]; }
globalThis.document={getElementById:el,dispatchEvent(){},addEventListener(){}};
globalThis.CustomEvent=function(){}; globalThis.location={search:process.argv[process.argv.length-1]};
"""
    proc = subprocess.run(
        ["node", "-", "?hours=100&gpus=1"],
        input=stub + src + "\nconsole.log(JSON.stringify({summary:els.summary.textContent,rows:els.results.tBodies[0].innerHTML}));",
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert "RunPod" in out["summary"] and "$199.00" in out["summary"]
    assert "Koyeb" not in out["summary"] and "Vast" not in out["summary"]
    assert "Koyeb" in out["rows"] and "serverless" in out["rows"].lower()
    assert "Vast" in out["rows"] and "minimum 8 GPUs" in out["rows"]


def _embed_template_js() -> str:
    from embed_page import BADGE_JS, _RANK_JS
    return (BADGE_JS.replace("__BASE__", "https://thelanternworks.com")
            .replace("__FAM__", json.dumps({"H100": "h100"}))
            .replace("__RANK__\n", _RANK_JS))


def _lowest_tracked(js: str, rows: list[dict]) -> dict:
    node = r"""
let src = process.argv[1];
const open = src.indexOf("(function(){");
if (open >= 0) src = src.slice(open + "(function(){".length);
const cut = src.indexOf("var els=");
if (cut >= 0) src = src.slice(0, cut);
eval(src);
const d = {schema:"lantern-works-gpu-prices/1", rates: JSON.parse(process.argv[2]), feed_updated_at:"2026-11-06"};
const el = {attrs:{}, innerHTML:"", getAttribute(k){return this.attrs[k] || null}, setAttribute(k,v){this.attrs[k]=v}};
el.setAttribute("data-gpu", "H100");
render(el, d);
const p = pickRow(d, "H100", "family", "on-demand");
process.stdout.write(JSON.stringify({
  advertiser: p.row ? p.row.advertiser : null,
  price: p.row ? p.row.hourly_equiv_usd : null,
  html: el.innerHTML
}));
"""
    proc = subprocess.run(
        ["node", "-e", node, js, json.dumps(rows)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _assert_lowest_tracked_skips_both(js: str):
    multi = _row("Vast", 0.40, min_gpus=8, gpu="H100 SXM", tier="On-demand (8x GPU)")
    koyeb = _row("Koyeb", 0.05, gpu="H100 SXM", tier="Serverless GPU instance (per-second billing)")
    single = _row("RunPod", 1.99, gpu="H100 SXM")
    got = _lowest_tracked(js, [multi, koyeb, single])
    assert got["advertiser"] == "RunPod" and got["price"] == 1.99
    assert "lowest tracked" in got["html"] and "RunPod" in got["html"] and "$1.99" in got["html"]
    assert "Vast" not in got["html"] and "Koyeb" not in got["html"]
    assert "8x GPU minimum" not in got["html"]
    empty = _lowest_tracked(js, [multi, koyeb])
    assert empty["advertiser"] is None
    assert "lowest tracked" not in empty["html"]
    assert "0.40" not in empty["html"] and "0.05" not in empty["html"]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_badge_js_lowest_tracked_skips_multi_gpu_and_serverless():
    """Published embed/badge.js: the lowest-tracked line must not name a cheaper multi-GPU or serverless row."""
    _assert_lowest_tracked_skips_both((ROOT / "embed" / "badge.js").read_text(encoding="utf-8"))


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_embed_page_lowest_tracked_skips_multi_gpu_and_serverless():
    """scripts/embed_page.py template, separate from the published badge.js file."""
    _assert_lowest_tracked_skips_both(_embed_template_js())


def re_search_script(page: str) -> str:
    import re
    return re.search(r"<script>\s*(const R=.*?)</script>", page, re.S).group(1)
