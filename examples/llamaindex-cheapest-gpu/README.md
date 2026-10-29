# LlamaIndex: cheapest tracked GPU rate

```bash
pip install llama-index-tools-mcp "mcp<2"
python main.py H100            # hosted endpoint
LANTERN_LOCAL=1 python main.py A100   # local server via uvx
```

Lists the Lantern Works MCP tools through `McpToolSpec` and calls `compare_gpu_prices`. Prices come live from the feed; confirm on the vendor page before spending.

Status: direct tool path tested 2026-10-29 (hosted endpoint). Passing `tools` to a LlamaIndex `FunctionAgent` with an LLM is **untested**.
Data: Lantern Works, CC BY 4.0.
