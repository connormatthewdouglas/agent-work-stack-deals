"""Second client: OpenAI Agents SDK MCP adapter (MCPServerStdio) over stdio. No LLM/API key used."""
import asyncio, json, sys
from pathlib import Path
from agents.mcp import MCPServerStdio

SERVER = Path(__file__).resolve().parents[1] / "server.py"


async def main():
    async with MCPServerStdio(name="lantern-works-deals",
                              params={"command": sys.executable, "args": [str(SERVER)]},
                              cache_tools_list=True) as srv:
        tools = await srv.list_tools()
        print("tools:", [(t.name, t.annotations.readOnlyHint if t.annotations else None) for t in tools])
        for name, args in [("search_deals", {"query": "email", "category": "email", "limit": 3}),
                           ("search_deals", {"tags": ["proxy"], "max_price": 50, "limit": 2}),
                           ("get_deal", {"id": "deal-firecrawl-free-001"}),
                           ("compare_deals", {"ids": ["deal-9proxy-001", "deal-brightdata-resi-001", "deal-proxydocker-001"]}),
                           ("compare_deals", {"ids": ["deal-9proxy-001"]}),
                           ("search_deals", {"limit": 99})]:
            res = await srv.call_tool(name, args)
            data = json.loads(res.content[0].text)
            print(f"\n== {name} {json.dumps(args)}\n{json.dumps(data, indent=1, ensure_ascii=False)[:900]}")

asyncio.run(main())
