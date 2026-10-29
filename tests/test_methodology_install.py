"""Methodology page + framework install snippets (offline checks; live runs are recorded on /install/)."""
import html, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/mcp"


def _pres(page):
    s = (ROOT / page / "index.html").read_text(encoding="utf-8")
    return s, [html.unescape(p) for p in re.findall(r'<div class="codebox"><pre>(.*?)</pre>', s, re.S)]


def test_framework_snippets_use_real_package_and_endpoint():
    s, pres = _pres("install")
    for anchor in ("llamaindex", "openwebui", "roo-code", "continue"):
        assert f'id="{anchor}"' in s and f'href="#{anchor}"' in s
    llama = next(p for p in pres if "llama_index.tools.mcp" in p)
    compile(llama, "llama", "exec")
    assert HOSTED in llama
    roo = next(json.loads(p) for p in pres if '"streamable-http"' in p)
    assert roo["mcpServers"]["lantern-works-deals"]["url"].startswith(HOSTED)
    cont = next(p for p in pres if "schema: v1" in p)
    assert "command: uvx" in cont and "- lantern-works-deals-mcp" in cont and "version:" in cont
    assert any(p.startswith("uvx mcpo") and p.endswith("uvx lantern-works-deals-mcp") for p in pres)


def test_methodology_page_reads_code_constants():
    src = (ROOT / "core" / "gpu.py").read_text(encoding="utf-8")
    stale = re.search(r"^STALE_DAYS\s*=\s*(\d+)", src, re.M).group(1)
    market = re.search(r"^MIN_MARKET_OFFERS\s*=\s*(\d+)", src, re.M).group(1)
    s = (ROOT / "methodology" / "index.html").read_text(encoding="utf-8")
    assert f"{stale} days" in s and f"fewer than {market} available offers" in s
    assert "MIT License" in s and "CC BY 4.0" in s and "Lantern Works" in s and "10:23 UTC" in s
    assert "Frosty" not in s
    assert "/methodology/" in (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    assert 'href="/methodology/"' in s or "/methodology/\"" in s


def test_free_credits_page_cited_and_clean():
    s = (ROOT / "gpu" / "free-credits" / "index.html").read_text(encoding="utf-8")
    import sys as _s
    _s.path.insert(0, str(ROOT / "scripts"))
    import free_credits_page as F
    for name, url, *_ in F.PROGRAMS:
        assert url.startswith("https://") and url in s, name
    assert s.count(f"checked {F.CHECKED}") >= len(F.PROGRAMS)
    assert "Frosty" not in s and "commission" not in s.lower() and "sponsored" not in s
    assert "/gpu/free-credits/" in (ROOT / "sitemap.xml").read_text(encoding="utf-8")
