"""T118/T115 regressions: brief compare_gpu_prices keeps the on-demand fallback note, the interruptible flag and the
applied constraints; stdio serverInfo carries build like hosted; T112/T113 feed fields pass through."""
import asyncio
import re

from core import contract
from core import deals as core

FULL = {
    "gpu": "MI355X", "summary": "s", "count": 1, "total": 1, "on_demand_only": True,
    "on_demand_fallback": "No on-demand rate is tracked for this model, so these results include spot/community/marketplace rates.",
    "constraints": {"applied": {"gpu": ["mi355x"], "tiers": ["interruptible", "on-demand"]}, "eligible_rate_ids": ["r_x"], "contract": "c"},
    "results": [{"rank": 1, "rate_id": "r_x", "advertiser": "DigitalOcean GPU Droplets", "gpu": "MI355X", "hourly_usd": 4.5,
                 "source_url": "https://example.invalid/", "tier": "Spot (interruptible)", "tier_class": "interruptible",
                 "interruptible": True}],
}


def test_brief_keeps_fallback_interruptible_and_constraints():
    b = contract.finalize("compare_gpu_prices", FULL, "brief")
    assert b["mode"] == "brief"
    assert b["on_demand_fallback"] == FULL["on_demand_fallback"]
    assert b["on_demand_only"] is True
    assert b["constraints"] == {"applied": FULL["constraints"]["applied"]}
    assert b["results"][0]["interruptible"] is True


def test_live_mi355x_on_demand_only_brief_never_hides_spot():
    from mcp_server import server
    r = server.compare_gpu_prices(gpu="MI355X", on_demand_only=True)
    assert r["ok"] and r["mode"] == "brief"
    for row in r["results"]:
        if row.get("tier_class") != "on-demand":
            assert "interruptible" in row
            assert r.get("on_demand_fallback"), "non-on-demand row shown under on_demand_only without the fallback note"
    if r["results"]:
        assert "constraints" in r and "applied" in r["constraints"]


def test_rate_fields_pass_t112_t113_through():
    for k in ("availability_rate_7d", "expected_cost_usd", "availability_status", "availability_reason"):
        assert k in core.RATE_FIELDS


def test_stdio_server_info_has_build():
    from mcp_server import server
    from mcp.shared.memory import create_connected_server_and_client_session

    async def go():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as c:
            return await c.initialize()
    info = asyncio.run(go()).serverInfo
    assert info.name == "lantern-works-deals" and info.version == server.__version__
    build = info.model_dump().get("build")
    assert build == server.BUILD_SHA and (build == "unknown" or re.fullmatch(r"[0-9a-f]{40}", build))
