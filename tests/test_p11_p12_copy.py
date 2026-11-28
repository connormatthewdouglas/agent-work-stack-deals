"""P11/P12: README and /gpu/*-rental-price/ pages lead with what an agent gets in one call; tool names are real."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install_page  # noqa: E402

ONE_CALL = ("compare_gpu_prices", "find_available_gpus", "estimate_job_cost", "create_alert", "check_alerts", "get_price_changes", "get_price_trend")
HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/mcp"


def _real_tools():
    return set(install_page.TOOLS) | set(install_page.HOSTED_EXTRA)


def test_one_call_tool_names_exist_in_server_code():
    assert set(ONE_CALL) <= _real_tools()
    assert len(install_page.TOOLS) == 11 and len(_real_tools()) == 18  # README states 11 local / 18 hosted


def test_readme_leads_with_one_call_and_has_install_block():
    s = (ROOT / "README.md").read_text(encoding="utf-8")
    top = s.split("## Connect your client")[0]
    for name in ONE_CALL:
        assert f"`{name}" in top, name
    assert f"claude mcp add --transport http lantern-works-gpu-prices \"{HOSTED}?ref=readme\"" in top
    assert "uvx lantern-works-deals-mcp" in top and "No API key" in top
    assert "among tracked providers" in top and "not real-time" in top
    assert "18 in total" in s and "Tools (11 in the local package" in s
    assert "Frosty" not in s and "Connor" not in top


def test_rental_pages_have_agent_intro_and_valid_meta():
    pages = list((ROOT / "gpu").glob("*-rental-price/index.html"))
    assert pages
    for path in pages:
        t = path.read_text(encoding="utf-8")
        desc = re.search(r'name="description" content="(.*?)"', t).group(1)
        assert len(desc) <= 155 and "among tracked providers" in desc, (path, desc)
        assert "For agents, in one call:" in t, path
        for name in ("compare_gpu_prices", "find_available_gpus", "estimate_job_cost", "create_alert", "check_alerts", "get_price_changes", "get_price_trend"):
            assert f"<code>{name}</code>" in t, (path, name)
        assert 'href="https://thelanternworks.com/install/"' in t and 'href="https://thelanternworks.com/api/"' in t
        assert "Frosty" not in t and "Connor" not in t
    h100 = (ROOT / "gpu" / "h100-rental-price" / "index.html").read_text(encoding="utf-8")
    assert "Free MCP server and JSON API for agents." in h100
