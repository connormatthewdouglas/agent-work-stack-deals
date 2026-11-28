"""Outside install surfaces carry a one-line install and the copy-paste first call."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRST = 'find_available_gpus(gpu="H100")'
INSTALL = "uvx lantern-works-deals-mcp"
HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/mcp"
BLURB = "current in-stock check among tracked providers"


def _has_call(text: str) -> bool:
    return FIRST in text or FIRST.replace('"', "&quot;") in text


def test_readme_and_pypi_readme_have_install_and_first_call():
    for rel in ("README.md", "mcp_server/README.md"):
        s = (ROOT / rel).read_text(encoding="utf-8")
        assert _has_call(s), rel
        assert INSTALL in s and HOSTED in s, rel
        assert BLURB in s, rel
        assert "Frosty" not in s


def test_listing_landing_pages_have_install_and_first_call():
    for rel in ("for-agents/index.html", "install/index.html", "quickstart/index.html"):
        t = (ROOT / rel).read_text(encoding="utf-8")
        assert _has_call(t), rel
        assert INSTALL in t and HOSTED in t, rel
        assert BLURB in t, rel
        assert "Frosty" not in t and "Connor" not in t
