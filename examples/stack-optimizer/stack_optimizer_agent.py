"""Describe your agent's job, get the cheapest cited stack back (OpenAI Agents SDK + Lantern Works MCP server).

Launches `uvx lantern-works-deals-mcp` over stdio with agents.mcp.MCPServerStdio.
Default (no LLM key): calls optimize_agent_stack directly with your description and prints each component's
cheapest option with its cited price and source. With OPENAI_API_KEY set and --agent, an Agent calls the tool
itself and summarizes (untested by maintainers).

Usage: python stack_optimizer_agent.py "scrapes 20k JS pages/month via 5 GB residential proxies, ..." [--agent] [--json]
"""
import asyncio
import json
import os
import sys

from agents.mcp import MCPServerStdio

DEFAULT_JOB = ("scrapes 20k JS pages/month via 5 GB residential proxies, 3k search queries, "
               "summarizes with an LLM, budget $300/mo")


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    job = args[0] if args else DEFAULT_JOB
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
                name="Stack cost analyst",
                instructions="Call optimize_agent_stack with the user's job description. Report each component's "
                "cheapest option with monthly cost, calc and source_url, the total and whether it is complete. "
                "Say which links are referral links and which components have no sourced price.",
                mcp_servers=[server],
            )
            result = await Runner.run(agent, f"My agent: {job}")
            print(result.final_output)
            return

        res = await server.call_tool("optimize_agent_stack", {"description": job})
        data = json.loads(res.content[0].text)
        if "--json" in sys.argv:
            print(json.dumps(data, indent=2))
            return
        print(f"job: {job}")
        print("parsed components:", ", ".join(data["parsed"]["components"]))
        for line in data["lines"]:
            c = line.get("choice")
            if not c:
                print(f"  {line['component']}: {line.get('status')} ({line.get('note') or 'no sourced price tracked'})")
                continue
            ref = "  (referral link)" if c.get("affiliate") else ""
            print(f"  {line['component']}: {c['vendor']} {c.get('plan')}, ${line['monthly_cost_usd']}/mo"
                  f" [{line['status']}], {c.get('calc')}, checked {c.get('checked_at')}, {c['source_url']}{ref}")
        print(data["estimate_math"], "(complete)" if data["estimate_is_complete"] else "(incomplete)")
        if data.get("budget"):
            print("within budget:", data["budget"]["within_budget"])


if __name__ == "__main__":
    asyncio.run(main())
