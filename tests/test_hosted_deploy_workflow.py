"""A3: hosted MCP deploys from CI on a release or version tag, using the Cloudflare token by name."""
from pathlib import Path

WF = (Path(__file__).resolve().parents[1] / ".github/workflows/deploy-hosted-mcp.yml").read_text(encoding="utf-8")


def test_deploys_on_release_and_tag_with_named_secrets():
    assert "release:" in WF and "published" in WF and 'tags: ["v*"]' in WF
    assert "secrets.CLOUDFLARE_API_TOKEN" in WF
    assert "secrets.CLOUDFLARE_ACCOUNT_ID" in WF
    assert "wrangler" in WF and "hosted/build.sh" in WF
    assert "Missing repository secret CLOUDFLARE_API_TOKEN" in WF
