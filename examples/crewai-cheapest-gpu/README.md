# CrewAI: cheapest GPU for a described job

Starts the Lantern Works MCP server (`uvx lantern-works-deals-mcp`) over stdio with CrewAI's `MCPServerAdapter`
(`crewai-tools[mcp]`) and finds the cheapest tracked GPU rental for a job you describe.

```bash
uv venv -p 3.12 .venv && . .venv/bin/activate
uv pip install -r requirements.txt      # uv/uvx must be on PATH
python cheapest_gpu_crew.py "fine-tune a 13B model with LoRA"
python cheapest_gpu_crew.py "pretrain a 70B model" --agent   # optional, needs OPENAI_API_KEY
```

- **Default path (tested, no LLM):** a simple keyword rule maps the job to a GPU (H100, A100 or RTX 4090), then the
  script calls `compare_gpu_prices` directly through the adapter and prints the top 3 results.
- **`--agent` path (untested):** a one-agent CrewAI crew picks the GPU and calls the tools itself. It needs
  `OPENAI_API_KEY`, and the maintainers have not run it.

**Referral links:** results with `affiliate: true` have a referral `redeem_url`, and the script marks those lines
`(referral link)`. The `source_url` it prints is the vendor's own pricing page. Results cover tracked providers only,
`checked_at` is when the price was last checked (UTC), and prices exclude storage, egress and taxes.
Confirm on the vendor page before spending.
