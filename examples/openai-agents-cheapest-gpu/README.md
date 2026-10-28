# OpenAI Agents SDK: cheapest GPU for a described job

Launches the Lantern Works MCP server (`uvx lantern-works-deals-mcp`) over stdio with the OpenAI Agents SDK's
`agents.mcp.MCPServerStdio`, then finds the cheapest tracked GPU rental for a job you describe.

```bash
uv venv -p 3.12 .venv && . .venv/bin/activate
uv pip install -r requirements.txt      # uv/uvx must be on PATH
python cheapest_gpu_agent.py "fine-tune a 13B model with LoRA"
python cheapest_gpu_agent.py "pretrain a 70B model" --agent   # optional, needs OPENAI_API_KEY
```

- **Default path (tested, no LLM):** a simple keyword rule maps the job to a GPU (H100, A100 or RTX 4090). The script
  then calls `compare_gpu_prices` directly through the MCP server and prints the top 3 results.
- **`--agent` path (untested):** an `Agent` with `mcp_servers=[server]` picks the GPU and calls the tools itself. It
  needs `OPENAI_API_KEY`, and the maintainers have not run it.

With openai-agents 0.24 you may see `Failed to validate request ... server/discover` on stderr. The SDK's MCP
client sends an optional discovery probe that the server does not support. The client then falls back to the normal
handshake, and the tools work.

**Referral links:** results with `affiliate: true` have a referral `redeem_url`, and the script marks those lines
`(referral link)`. The `source_url` it prints is the vendor's own pricing page. Results cover tracked providers only,
`checked_at` is when the price was last checked (UTC), and prices exclude storage, egress and taxes.
Confirm on the vendor page before spending.
