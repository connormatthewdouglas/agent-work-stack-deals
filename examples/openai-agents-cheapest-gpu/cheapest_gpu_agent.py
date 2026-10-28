"""Cheapest GPU for a described job, using the OpenAI Agents SDK with the Lantern Works MCP server.

Launches `uvx lantern-works-deals-mcp` over stdio with agents.mcp.MCPServerStdio.
Default (no LLM key): maps the job to a GPU with a simple VRAM rule and calls
compare_gpu_prices directly through the MCP server. With OPENAI_API_KEY set and
--agent, an Agent picks the GPU and calls the tools itself (untested by maintainers).

Usage: python cheapest_gpu_agent.py "fine-tune a 13B model with LoRA" [--agent]
"""
import asyncio
import json
import os
import sys

from agents.mcp import MCPServerStdio


def pick_gpu(job: str) -> str:
    """Very rough VRAM heuristic for the no-LLM path."""
    j = job.lower()
    if any(k in j for k in ("70b", "65b", "pretrain", "full fine-tune")):
        return "H100"
    if any(k in j for k in ("13b", "30b", "34b", "fine-tune", "finetune", "lora")):
        return "A100"
    return "RTX 4090"


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    job = args[0] if args else "serve a 7B chat model for a small team"
    async with MCPServerStdio(
        name="lantern-works-deals",
        params={"command": "uvx", "args": ["lantern-works-deals-mcp"]},
        client_session_timeout_seconds=60,
    ) as server:
        tools = await server.list_tools()
        print("tools:", ", ".join(sorted(t.name for t in tools)))

        if "--agent" in sys.argv and os.environ.get("OPENAI_API_KEY"):
            from agents import Agent, Runner

            agent = Agent(
                name="GPU cost analyst",
                instructions="Choose a GPU model with enough VRAM for the job, call compare_gpu_prices, and report "
                "the cheapest option with provider, $/hr and source_url. Say which links are referral links.",
                mcp_servers=[server],
            )
            result = await Runner.run(agent, f"Job: {job}")
            print(result.final_output)
            return

        gpu = pick_gpu(job)
        res = await server.call_tool("compare_gpu_prices", {"gpu": gpu, "limit": 3})
        data = json.loads(res.content[0].text)
        print(f"job: {job}\ngpu: {gpu}\n{data['summary']}")
        for r in data["results"]:
            ref = "  (referral link)" if r.get("affiliate") else ""
            print(f"  #{r['rank']} {r['advertiser']} {r['gpu']} {r.get('tier')}: ${r['hourly_usd']}/hr, "
                  f"checked {r.get('checked_at')}, {r['source_url']}{ref}")


if __name__ == "__main__":
    asyncio.run(main())
