"""T42: the browser calculator bills whole instances exactly like core.gpu.estimate (and so the MCP).
Runs the real page script from tools/gpu-cost-calculator/index.html in node with a tiny DOM stub and compares
the rendered rows (cost, requested/billed GPUs) with the Python engine for 1/8/9-GPU cases."""
import html, json, pathlib, re, shutil, subprocess
import pytest
from core import gpu as G
ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "tools/gpu-cost-calculator/index.html"
NODE = shutil.which("node")
STUB = r"""
const els={}; function el(id){ if(!els[id]) els[id]={id,value:"",checked:true,href:"",textContent:"",tBodies:[{innerHTML:""}],addEventListener(){}}; return els[id]; }
globalThis.document={getElementById:el,dispatchEvent(){},addEventListener(){}};
globalThis.CustomEvent=function(){}; globalThis.location={search:process.argv[process.argv.length-1]};
"""
def render(query):
    src = PAGE.read_text()
    js = re.search(r"<script>\s*(const R=.*?)</script>", src, re.S).group(1)
    js = STUB + js + "\nconsole.log(JSON.stringify({rows:els.results.tBodies[0].innerHTML,summary:els.summary.textContent}));"
    p = subprocess.run([NODE, "-", query], input=js, capture_output=True, text=True, check=True)
    out = json.loads(p.stdout)
    rows = re.findall(r"<tr><td><strong>\$([\d,]+\.\d\d)</strong></td><td>(.*?)</td><td><a[^>]*>(.*?)</a></td><td>.*?</td><td>(.*?)</td>", out["rows"])
    return [(float(c.replace(",", "")), html.unescape(g), html.unescape(a), html.unescape(calc)) for c, g, a, calc in rows]

@pytest.mark.skipif(not NODE, reason="node not installed")
@pytest.mark.parametrize("gpus", [1, 8, 9])
def test_browser_matches_python_engine(gpus):
    rates = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())["rates"]
    py = G.estimate([r for r in rates if r["unit"] == "hour"], 10, gpus, "H100")
    want = sorted(round(r["monthly_cost_usd"], 2) for r in py)
    got = render(f"?hours=10&gpus={gpus}&gpu=H100&flat=0")
    assert sorted(c for c, *_ in got) == want
    for c, g, a, calc in got:
        m = next(r for r in py if r["advertiser"] == a and round(r["monthly_cost_usd"], 2) == c)
        assert f"× {m['billed_gpus']} GPU" in calc
        if m["billed_gpus"] > gpus:
            assert f"{gpus} requested, {m['billed_gpus']} billed" in calc

@pytest.mark.skipif(not NODE, reason="node not installed")
def test_coreweave_nine_gpus_ten_hours_is_two_instances():
    rates = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())["rates"]
    cw = [r for r in G.estimate(rates, 10, 9, "H100") if r["advertiser"] == "CoreWeave"]
    assert cw and cw[0]["billed_gpus"] == 16 and cw[0]["instances"] == 2
    assert cw[0]["monthly_cost_usd"] == round(cw[0]["price_usd"] * 10 * 16, 2)
    got = [x for x in render("?hours=10&gpus=9&gpu=H100&flat=0") if x[2] == "CoreWeave"]
    assert got[0][0] == cw[0]["monthly_cost_usd"] and "2 instances" in got[0][3]

@pytest.mark.skipif(not NODE, reason="node not installed")
def test_monthly_bundle_bills_whole_servers():
    r = {"advertiser": "X", "gpu": "H100", "vram_gb": 80, "unit": "month", "price_usd": 1000.0, "gpu_count": 8,
         "server_price_usd": 8000.0, "min_gpus": 8}
    e = G.estimate([r], 10, 9)[0]
    assert (e["billed_gpus"], e["instances"], e["monthly_cost_usd"]) == (16, 2, 16000.0)


@pytest.mark.skipif(not NODE, reason="node not installed")
@pytest.mark.parametrize("q,msg", [("?hours=-5&gpus=1&gpu=H100&flat=0", "hours must be a number > 0 and <= 20000"),
                                   ("?hours=0&gpus=1&gpu=H100&flat=0", "hours must be a number > 0 and <= 20000"),
                                   ("?hours=10&gpus=0&gpu=H100&flat=0", "gpus must be an integer >= 1"),
                                   ("?hours=10&gpus=1.5&gpu=H100&flat=0", "gpus must be an integer >= 1"),
                                   ("?hours=abc&gpus=1&gpu=H100&flat=0", "hours must be a number > 0 and <= 20000"),
                                   ("?hours=1e9&gpus=1&gpu=H100&flat=0", "hours must be a number > 0 and <= 20000"),
                                   ("?hours=20000.5&gpus=1&gpu=H100&flat=0", "hours must be a number > 0 and <= 20000")])
def test_invalid_input_rejected_like_engine(q, msg):
    """re24 (2): no $0.00 rows for hours <= 0, no silent gpus=0 -> 1."""
    src = PAGE.read_text()
    js = re.search(r"<script>\s*(const R=.*?)</script>", src, re.S).group(1)
    js = STUB + js + "\nconsole.log(JSON.stringify({rows:els.results.tBodies[0].innerHTML,summary:els.summary.textContent}));"
    out = json.loads(subprocess.run([NODE, "-", q], input=js, capture_output=True, text=True, check=True).stdout)
    assert out["summary"] == "invalid_argument: " + msg and "$" not in out["rows"]


def test_engine_gpu_hours_cap_matches_calculator():
    """Gauge re26 (B): the MCP/engine rejects the same hours the calculator rejects."""
    import sys as _s
    _s.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from core import stack
    assert stack.MAX_GPU_HOURS_MONTH == 20000 and 'max="20000"' in PAGE.read_text()
    with pytest.raises(stack.StackError, match="gpu_hours must be a number 0-20000"):
        stack.optimize({"deals": []}, {"gpu_hours": 1e9}, gpu_data={"rates": []})
