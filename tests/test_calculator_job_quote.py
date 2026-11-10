"""T120 PR A: the GPU cost calculator shows no recommendation until GPU + hours +
count are set, defaults the price tier to on-demand (MCP compare_gpu_prices default),
and round-trips those filters through the share URL."""
import json, pathlib, re, shutil, subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "tools/gpu-cost-calculator/index.html"
FIXTURE = ROOT / "tests/fixtures/gpu-prices-min-gpus-2026-11-10.json"
NODE = shutil.which("node")
PROMPT = "Choose a GPU model and enter workload hours and GPU count to see a comparable quote."
STUB = r"""
const els={}; function el(id){ if(!els[id]) els[id]={id,value:"",checked:true,href:"",textContent:"",tBodies:[{innerHTML:""}],addEventListener(){}}; return els[id]; }
globalThis.document={getElementById:el,dispatchEvent(){},addEventListener(){}};
globalThis.CustomEvent=function(){}; globalThis.location={search:process.argv[process.argv.length-1]};
"""


def render(query="?"):
    src = PAGE.read_text(encoding="utf-8")
    js = re.search(r"<script>\s*(const R=.*?)</script>", src, re.S).group(1)
    # Frozen rate fixture (main 1b47ecc7) with the clock pinned 12 h after its feed_updated_at: the named quotes are real
    # Hyperstack/RunPod/Lium rows, and the live collectors rewrite them. Assertions unchanged.
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    start = js.index("const R=") + len("const R=")
    _, end = json.JSONDecoder().raw_decode(js, start)
    js = js[:start] + json.dumps(fixture["rates"], ensure_ascii=False) + js[end:]
    # 12 h after the feed build: 1 h availability claims have expired (stock unknown), prices are well inside 48 h.
    pin = "Date.now=()=>Date.parse(%s)+12*3600e3;\n" % json.dumps(fixture["feed_updated_at"])
    js = pin + STUB + js + "\nconsole.log(JSON.stringify({rows:els.results.tBodies[0].innerHTML,summary:els.summary.textContent,href:els.permalink.href,hours:els.hours.value,gpus:els.gpus.value,gpu:els.gpu.value,tier:els.tier.value}));"
    p = subprocess.run([NODE, "-", query], input=js, capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


@pytest.mark.skipif(not NODE, reason="node not installed")
@pytest.mark.parametrize("query", ["?", "?hours=100", "?gpus=1", "?gpu=H100",
                                   "?hours=100&gpus=1", "?hours=100&gpu=H100", "?gpus=1&gpu=H100"])
def test_no_recommendation_without_gpu_and_hours_and_count(query):
    out = render(query)
    assert out["summary"] == PROMPT
    assert PROMPT in out["rows"]
    assert "Cheapest among tracked providers" not in out["summary"]
    assert "$" not in out["rows"]


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_default_tier_is_on_demand():
    src = PAGE.read_text(encoding="utf-8")
    assert 'value="on-demand" selected' in src
    assert "Spot / interruptible (the vendor may preempt the job)" in src
    assert "Marketplace (variable host prices)" in src
    out = render("?hours=100&gpus=1&gpu=H100&flat=0")
    assert out["tier"] == "on-demand"
    assert "Cheapest among tracked providers" in out["summary"]
    # The named 1x H100 100h row is on-demand, not the cheaper community or spot rates.
    assert "Hyperstack" in out["summary"] and "250.00" in out["summary"]
    assert "199.00" not in out["summary"]  # RunPod community
    assert "200.00" not in out["summary"]  # Hyperstack spot
    # Interruptible/community rows stay out of the table until opted in.
    assert "Spot VM" not in out["rows"]
    assert "Community Cloud" not in out["rows"]
    assert "Marketplace" not in out["rows"]


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_url_round_trip_of_filters():
    q = "?hours=100&gpus=8&gpu=H100+SXM&tier=interruptible&flat=0"
    out = render(q)
    assert out["hours"] == "100" and out["gpus"] == "8"
    assert out["gpu"] == "H100 SXM" and out["tier"] == "interruptible"
    # URLSearchParams serializes space as +.
    href = out["href"]
    got = {k: v for k, v in (part.split("=", 1) for part in href.lstrip("?").split("&") if part)}
    assert got["hours"] == "100" and got["gpus"] == "8"
    assert got["gpu"].replace("+", " ") == "H100 SXM"
    assert got["tier"] == "interruptible"
    assert got.get("flat") == "0"
    assert "Lium" in out["summary"] and "1,240.00" in out["summary"]
    # A second load of the generated share link restores the same filters and quote.
    again = render(href)
    assert again["hours"] == "100" and again["gpus"] == "8"
    assert again["gpu"] == "H100 SXM" and again["tier"] == "interruptible"
    assert again["summary"] == out["summary"]
    assert again["href"] == href
