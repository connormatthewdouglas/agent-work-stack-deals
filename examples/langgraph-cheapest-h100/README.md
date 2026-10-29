# LangGraph / LangChain: cheapest H100 via MCP

Launches the Lantern Works MCP server (`uvx lantern-works-deals-mcp`) over stdio with
[`langchain-mcp-adapters`](https://github.com/langchain-ai/langchain-mcp-adapters), loads all of its tools
as LangChain tools, and calls `compare_gpu_prices` with `{"gpu": "H100"}`.

**By default no LLM is used:** the script calls the tool directly through the adapter, so it runs
without any API key. With `OPENAI_API_KEY` set, `--agent` runs the same tools inside a LangGraph
ReAct agent (that path was not tested in CI or by the maintainers).

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt   # needs uv/uvx on PATH for the server
python cheapest_h100.py           # direct tool call, no LLM
python cheapest_h100.py --agent   # optional, needs OPENAI_API_KEY
```

Expected output (prices change): the tool list, then JSON whose `summary` reads like
`Cheapest among tracked providers: RunPod H100 PCIe at $1.99/hr ...`. Results cover tracked
providers only and exclude storage, egress and taxes; confirm on the vendor page.
