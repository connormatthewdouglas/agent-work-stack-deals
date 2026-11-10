"""T120 PR B: billed-count math, unknown billing terms, reservation break-even, MCP snippet."""
import html, json, pathlib, re, shutil, subprocess

import pytest

from core import gpu as G

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "tools/gpu-cost-calculator/index.html"
NODE = shutil.which("node")
STUB = r"""
const els={}; function el(id){ if(!els[id]) els[id]={id,value:"",checked:true,href:"",hidden:false,textContent:"",innerHTML:"",tBodies:[{innerHTML:""}],addEventListener(){}}; return els[id]; }
globalThis.document={getElementById:el,dispatchEvent(){},addEventListener(){}};
globalThis.CustomEvent=function(){}; globalThis.location={search:process.argv[process.argv.length-1]};
"""


def render(query="?"):
    src = PAGE.read_text(encoding="utf-8")
    js = re.search(r"<script>\s*(const R=.*?)</script>", src, re.S).group(1)
    js = STUB + js + """
console.log(JSON.stringify({rows:els.results.tBodies[0].innerHTML,summary:els.summary.textContent,quote:(els.quote&&els.quote.innerHTML)||"",href:els.permalink.href}));"""
    p = subprocess.run([NODE, "-", query], input=js, capture_output=True, text=True, check=True)
    out = json.loads(p.stdout)
    out["quote"] = html.unescape(out.get("quote") or "")
    return out


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_billed_count_and_subtotal_on_billed():
    """9x H100 for 10 hours: CoreWeave bills two 8-GPU instances (16 GPUs). The quote names the
    cheapest headline-eligible row; the table still shows CoreWeave billed math. A fixture where
    the named row has a multi-GPU minimum is asserted on the quote box itself."""
    rates = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())["rates"]
    cw = [r for r in G.estimate(rates, 10, 9, "H100") if r["advertiser"] == "CoreWeave"]
    assert cw and cw[0]["billed_gpus"] == 16 and cw[0]["instances"] == 2
    subtotal = round(cw[0]["price_usd"] * 10 * 16, 2)
    assert cw[0]["monthly_cost_usd"] == subtotal
    out = render("?hours=10&gpus=9&gpu=H100&flat=0")
    assert "CoreWeave" in out["rows"] and "2 instances" in out["rows"]
    assert "9 requested, 16 billed" in out["rows"]

    # Named-quote path: a single 8-GPU on-demand row so the headline pick must bill 16 for 9 requested.
    src = PAGE.read_text(encoding="utf-8")
    js = re.search(r"<script>\s*(const R=.*?)</script>", src, re.S).group(1)
    i = js.index("const R=")
    _obj, end = json.JSONDecoder().raw_decode(js, i + len("const R="))
    # Keep V and the rest of the script; replace only the rates array.
    fresh = "2026-11-10T12:00:00+00:00"
    row = {
        "advertiser": "CoreWeave", "gpu": "H100 SXM", "vram_gb": 80, "unit": "hour",
        "price_usd": 6.155, "hourly_equiv_usd": 6.155, "gpu_count": 8, "min_gpus": 8,
        "tier": "On-demand, 8-GPU instance", "tier_class": "on-demand", "billing": "per hour while running",
        "billing_unit": "hourly", "price_status": "listed", "verified_at": fresh, "checked_at": fresh,
        "source_url": "https://coreweave.example/pricing", "redeem_url": "https://coreweave.example/pricing",
        "deal_id": "coreweave", "basis": "listed", "affiliate": False, "interruptible": False,
    }
    js = "const R=" + json.dumps([row]) + js[end:]
    stub = STUB + js + "\nconsole.log(JSON.stringify({quote:els.quote.innerHTML,summary:els.summary.textContent}));"
    got = json.loads(subprocess.run([NODE, "-", "?hours=10&gpus=9&gpu=H100+SXM&flat=0"],
                                    input=stub, capture_output=True, text=True, check=True).stdout)
    got["quote"] = html.unescape(got.get("quote") or "")
    assert "Requested 9 GPUs; billed 16 GPUs" in got["quote"]
    assert "$984.80 is for the 16 billed GPUs" in got["quote"]
    assert "Compute subtotal: $984.80 for 10 hours × 16 billed GPUs" in got["quote"]
    assert "minimum rental is 8 GPUs sold as whole 8-GPU servers (2 instances)" in got["quote"]
    assert "CoreWeave" in got["summary"]


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_unknown_billing_increment_and_sourced_increment():
    out = render("?hours=100&gpus=1&gpu=H100+PCIe&flat=0")
    quote = out["quote"]
    assert "Normalized hourly price:" in quote
    # RunPod (and several others) have no billing_granularity in the feed.
    # The named 1x H100 PCIe on-demand row is Hyperstack, which does publish per-minute increment.
    assert "Hyperstack" in quote and "billing increment: per-minute" in quote
    # A vendor with no sourced increment must say unknown, never a guessed increment.
    src = PAGE.read_text(encoding="utf-8")
    js = re.search(r"<script>\s*(const R=.*?)</script>", src, re.S).group(1)
    i = js.index("const R=")
    _obj, end = json.JSONDecoder().raw_decode(js, i + len("const R="))
    rest = js[end:]
    # Force V so this advertiser has a null increment.
    rest = re.sub(r", V=\{.*?\}, C=", ", V={\"RunPod\":{\"billing_granularity\":null}}, C=", rest, count=1, flags=re.S)
    fresh = "2026-11-10T12:00:00+00:00"
    row = {
        "advertiser": "RunPod", "gpu": "H100 PCIe", "vram_gb": 80, "unit": "hour",
        "price_usd": 2.89, "hourly_equiv_usd": 2.89, "gpu_count": 1, "min_gpus": 1,
        "tier": "On-demand (Secure Cloud)", "tier_class": "on-demand", "billing": "per hour while running",
        "billing_unit": "hourly", "price_status": "listed", "verified_at": fresh, "checked_at": fresh,
        "source_url": "https://runpod.example/pricing", "redeem_url": "https://runpod.example/pricing",
        "deal_id": "runpod", "basis": "listed", "affiliate": False, "interruptible": False,
    }
    js = "const R=" + json.dumps([row]) + rest
    got = json.loads(subprocess.run(
        [NODE, "-", "?hours=100&gpus=1&gpu=H100+PCIe&flat=0"],
        input=STUB + js + "\nconsole.log(JSON.stringify({quote:els.quote.innerHTML}));",
        capture_output=True, text=True, check=True,
    ).stdout)
    got["quote"] = html.unescape(got.get("quote") or "")
    assert "billing increment: unknown" in got["quote"]
    assert "Not included: storage, egress, idle time beyond the hours entered, and taxes." in got["quote"]
    assert "vendor price source" in got["quote"]
    assert "free credit" not in got["quote"].lower()  # no invented credits
    assert "compare_gpu_prices(" in got["quote"]
    assert '"on_demand_only": true' in got["quote"]
    assert '"gpu": "H100 PCIe"' in got["quote"]
    assert '"gpus": 1' in got["quote"]


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_reservation_break_even_hours_per_day_and_weekday():
    """Hyperstack H100 SXM has both reserved and on-demand rows. Break-even uses 730 h/month and 21.7 weekdays."""
    out = render("?hours=100&gpus=1&gpu=H100+SXM&flat=0")
    q = out["quote"]
    assert "Reservation break-even for Hyperstack H100 SXM" in q
    # 2.72 * 730 / (3.2 * 730) = 85%; 20.4 h/day; 28.6 h/weekday
    assert "20.4 hours/day" in q
    assert "28.6 hours/weekday" in q
    assert "21.7 weekdays/month" in q
    assert "weekday-only use does not break even" in q
    assert "hours_per_month" in q
    assert "compare_gpu_prices(" in q
    assert '"gpu": "H100 SXM"' in q
