"""Logo/favicon assets exist with the right sizes and every public page links them (+ og/twitter image, JSON-LD logo)."""
import json, re, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "node_modules", ".github", "mcp_server", "tests", "examples", "plugins", "skills"}


def test_assets():
    def png(name):
        b = (ROOT / name).read_bytes()
        assert b[:8] == b"\x89PNG\r\n\x1a\n"
        return struct.unpack(">II", b[16:24])
    assert png("logo.png") == (400, 400)
    assert png("favicon-32.png") == (32, 32)
    assert png("apple-touch-icon.png") == (180, 180)
    assert (ROOT / "favicon.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_every_page_has_brand_head():
    pages = [p for p in ROOT.rglob("*.html") if not SKIP & set(p.relative_to(ROOT).parts)]
    missing = []
    for p in pages:
        t = p.read_text(encoding="utf-8")
        if "</head>" not in t:
            continue
        head = t.split("</head>")[0]
        for need in ('rel="icon" href="https://thelanternworks.com/favicon.ico"',
                     'property="og:image" content="https://thelanternworks.com/logo.png"',
                     'name="twitter:image" content="https://thelanternworks.com/logo.png"'):
            if need not in head:
                missing.append((str(p.relative_to(ROOT)), need))
        assert head.count("<!-- brand -->") == 1, p
    assert not missing, missing[:5]
    assert len(pages) > 100


def test_jsonld_logo():
    t = (ROOT / "index.html").read_text(encoding="utf-8")
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
    orgs = [n for b in blocks for n in json.loads(b).get("@graph", []) if n.get("@type") == "Organization"]
    assert orgs and orgs[0]["logo"]["url"] == "https://thelanternworks.com/logo.png"
