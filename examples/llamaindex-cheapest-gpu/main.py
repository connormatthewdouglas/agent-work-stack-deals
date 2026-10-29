"""Cheapest tracked GPU rate via LlamaIndex's MCP client (direct tool path; no LLM key needed).
pip install llama-index-tools-mcp "mcp<2"   then:  python main.py H100
Set LANTERN_LOCAL=1 to run the local server (uvx lantern-works-deals-mcp) instead of the hosted endpoint."""
import asyncio, os, sys
from llama_index.tools.mcp import BasicMCPClient, McpToolSpec

HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=install"


async def main(gpu: str) -> None:
    client = BasicMCPClient("uvx", args=["lantern-works-deals-mcp"]) if os.getenv("LANTERN_LOCAL") else BasicMCPClient(HOSTED)
    tools = await McpToolSpec(client=client).to_tool_list_async()
    print("tools:", ", ".join(t.metadata.name for t in tools))
    res = await client.call_tool("compare_gpu_prices", {"gpu": gpu})
    for c in res.content:
        print(getattr(c, "text", c)[:2000])
    # To hand the tools to an agent: FunctionAgent(tools=tools, llm=...) (agent path not tested here).


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "H100"))
