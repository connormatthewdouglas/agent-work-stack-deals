"""Find the cheapest H100 with the Lantern Works MCP server via langchain-mcp-adapters.

Launches `uvx lantern-works-deals-mcp` over stdio, loads its tools as LangChain
tools, and calls `compare_gpu_prices` directly (no LLM needed). Set
OPENAI_API_KEY and pass --agent to run the same tools inside a LangGraph
ReAct agent instead.
"""
import asyncio
import json
import os
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient

SERVER = {
    "lantern-works-deals": {
        "command": "uvx",
        "args": ["lantern-works-deals-mcp"],
        "transport": "stdio",
    }
}


def _text(result):
    if isinstance(result, tuple):  # (content, artifact) in some adapter versions
        result = result[0]
    if isinstance(result, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    return str(result)


async def main():
    client = MultiServerMCPClient(SERVER)
    tools = {t.name: t for t in await client.get_tools()}
    print("tools:", ", ".join(sorted(tools)))

    if "--agent" in sys.argv and os.environ.get("OPENAI_API_KEY"):
        from langgraph.prebuilt import create_react_agent

        agent = create_react_agent("openai:gpt-4o-mini", list(tools.values()))
        out = await agent.ainvoke(
            {"messages": [("user", "What is the cheapest H100 per hour right now? Use compare_gpu_prices.")]}
        )
        print(out["messages"][-1].content)
        return

    raw = _text(await tools["compare_gpu_prices"].ainvoke({"gpu": "H100"}))
    try:
        print(json.dumps(json.loads(raw), indent=2)[:3000])
    except ValueError:
        print(raw[:3000])


if __name__ == "__main__":
    asyncio.run(main())
