"""/stack/ page: generated, in nav + sitemap, and its in-browser parse matches core/agent_stack.parse."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import agent_stack as a

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "stack" / "index.html").read_text()
MAIN = PAGE.split("<footer")[0]  # the site-wide footer carries the standard affiliate disclosure
STATIC = MAIN.split("<script>")[0]
SAMPLES = [
    "Scrapes 20k JS-rendered pages a month through 5 GB of residential proxies, runs 3,000 search queries, summarizes with an LLM and sends 2,000 report emails.",
    "Serves a 13B model on an RTX 4090 for 200 GPU hours a month",
    "Finds leads with 5,000 search queries, scrapes 10k pages and sends 10,000 emails a month.",
    "crawl 1.5m urls with headless chrome via proxies, 40 GB",
]


def test_page_in_sitemap_and_nav():
    assert "https://thelanternworks.com/stack/</loc>" in (ROOT / "sitemap.xml").read_text()
    assert 'href="https://thelanternworks.com/stack/"' in (ROOT / "index.html").read_text()
    assert a.NO_DATA in MAIN and "commission" not in MAIN.lower() and "payout" not in MAIN.lower()


def test_presets_cited():
    for m in re.finditer(r'<a href="([^"]+)" rel="noopener">source</a>', STATIC):
        assert m.group(1).startswith("https://")


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_parse_matches_python():
    script = re.search(r"<script>\s*(const S=.*?)\$\(\"go\"\)", PAGE, re.S).group(1)
    js = script + "\nconst out=" + json.dumps(SAMPLES) + ".map(t=>{const r=parse(t);return [r.comps.slice().sort(),r.q,r.gm]});console.log(JSON.stringify(out));"
    js = "const document={getElementById:()=>({})};\n" + js
    res = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    for t, (comps, q, gm) in zip(SAMPLES, res):
        p = a.parse(t)
        pq = dict(p["quantities"])
        if pq.get("scrape_pages") and p["js_rendering"]:
            pq["scrape_pages_js"] = pq.pop("scrape_pages")
        assert comps == sorted(p["components"]), t
        assert {k: float(v) for k, v in q.items()} == {k: float(v) for k, v in pq.items()}, t
        assert gm == p["gpu_model"], t
