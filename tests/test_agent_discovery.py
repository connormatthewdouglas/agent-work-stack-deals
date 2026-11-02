import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent_manifest
import integration_snippet
import install_page


def test_generated_manifest_preserves_legacy_links_and_exposes_current_tools():
    doc = json.loads((ROOT / "agent.json").read_text())
    assert doc == agent_manifest.build()
    assert doc["name"] == "agent-work-stack-deals"
    feeds = {f["rel"]: f["url"] for f in doc["feeds"]}
    assert feeds["deals"] == "https://thelanternworks.com/deals.json"
    assert feeds["mirror"] == agent_manifest.LEGACY_MIRROR
    assert "query_deals" in {t["name"] for t in doc["tools"]}
    assert doc["mcp"]["read_only_tools"] == list(install_page.TOOLS)
    assert set(doc["mcp"]["opt_in_watch_tools"]).isdisjoint(doc["mcp"]["read_only_tools"])
    assert doc["mcp"]["read_only_queries_require_api_key"] is False
    assert doc["first_call"]["params"]["arguments"]["gpu"] == "H100 SXM"
    assert "gpu-model-index" in feeds
    for url in feeds.values():
        if url.startswith(agent_manifest.BASE):
            assert (ROOT / url.removeprefix(agent_manifest.BASE + "/")).exists()


def test_placement_snippet_tags_real_conversion_paths_and_keeps_limits():
    short = integration_snippet.render("hf")
    assert "/gpu/price-comparison/?ref=hf" in short and short.count("\n") == 1
    assert "```" not in short
    text = integration_snippet.render("hf", format="quickstart")
    assert "/mcp?ref=hf" in text and "/quickstart/?ref=hf" in text
    assert "--ref hf" in text and "estimate_job_cost" in text
    assert "source_url" in text and "checked_at" in text
    assert "not the entire market" in text and "compute" in text
    assert "client-specific setup" in text


@pytest.mark.parametrize("ref", ["", "x" * 33, "HF", "x&ref=qa", "x\n```", "$(id)"])
def test_snippet_rejects_invalid_channel_tags(ref):
    with pytest.raises(ValueError):
        integration_snippet.render(ref)
