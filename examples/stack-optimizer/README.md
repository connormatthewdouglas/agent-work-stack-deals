# OpenAI Agents SDK: describe your agent, get the cheapest cited stack

Launches the Lantern Works MCP server (`uvx lantern-works-deals-mcp`, 0.3.6+) over stdio with the OpenAI Agents
SDK's `agents.mcp.MCPServerStdio`, sends a plain-text description of an agent's job to `optimize_agent_stack`, and
prints the cheapest option with a cited price for each component (GPU, scraping, proxy, search, LLM API, email, ...).
The same optimizer runs in the browser at https://thelanternworks.com/stack/.

```bash
uv venv -p 3.12 .venv && . .venv/bin/activate
uv pip install -r requirements.txt      # uv/uvx must be on PATH
python stack_optimizer_agent.py "scrapes 20k JS pages/month via 5 GB residential proxies, 3k search queries, summarizes with an LLM, budget \$300/mo"
python stack_optimizer_agent.py "..." --json    # full tool output (alternatives, assumptions, untracked providers)
python stack_optimizer_agent.py "..." --agent   # optional, needs OPENAI_API_KEY
```

- **Default path (tested, no LLM):** calls `optimize_agent_stack` directly through the MCP server. The server parses the
  description deterministically (keywords/regex, no LLM) and returns one line per component with `calc`,
  `source_url` and `checked_at`, plus the total and whether it is complete.
- **`--agent` path (untested):** an `Agent` with `mcp_servers=[server]` calls the tool itself and summarizes. It needs
  `OPENAI_API_KEY`, and the maintainers have not run it.

## Real output (lantern-works-deals-mcp 0.3.6 from PyPI, openai-agents 0.24, run 2026-10-28 3:07 PM ET)

```text
tools: compare_deals, compare_gpu_prices, get_deal, optimize_agent_stack, optimize_stack, search_deals
job: scrapes 20k JS pages/month via 5 GB residential proxies, 3k search queries, summarizes with an LLM, budget $300/mo
parsed components: scraping, proxy, llm_api, search
  scraping: ZenRows Launch, $69.0/mo [priced], 20,000 x 5 = 100,000 credits; within 250,000 included at $69/mo, checked 2026-10-27T02:54:00-04:00, https://www.zenrows.com/pricing
  proxy: 9Proxy Residential (per GB), $3.4/mo [priced], $0/mo incl. 0 + 5 x $0.68 per 1 extra, checked 2026-10-27T02:54:00-04:00, https://9proxy.com/pricing  (referral link)
  llm_api: Groq Free plan with documented model rate limits (RPM/RPD/TPM) in Groq console docs, $0.0/mo [entry_price], free tier ($0), checked None, https://console.groq.com/docs/rate-limits
  search: Exa Starter credits + pay as you go, $4/mo [priced], $0/mo incl. 2,500 + 1 x $4 per 1,000 extra, checked 2026-10-27T02:54:00-04:00, https://exa.ai/pricing  (referral link)
$69.00 (scraping) + $3.40 (proxy) + $0.00 (llm_api) + $4.00 (search) = $76.40/mo (complete)
within budget: True

job: fine-tune a 13B model for 40 GPU hours, send 5k emails, budget $150/mo
parsed components: gpu, email
  gpu: RunPod RTX A6000 (Community Cloud), $13.2/mo [priced], $0.33/hr x 40 h, checked 2026-10-28T16:43:09+00:00, https://www.runpod.io/pricing  (referral link)
  email: SendPulse Basic (free), $0.0/mo [priced], within 12,000 included at $0/mo, checked 2026-10-27T02:54:00-04:00, https://sendpulse.com/prices/smtp  (referral link)
$13.20 (gpu) + $0.00 (email) = $13.20/mo (complete)
within budget: True
```

Prices change; rerun for current data. Components with no cited price say `no sourced price tracked` and are not
estimated. `entry_price` means the cheapest cited entry plan; real usage may need a bigger plan.

With openai-agents 0.24 you may see `Failed to validate request ... server/discover` on stderr. The SDK's MCP
client sends an optional discovery probe that the server does not support; it falls back to the normal handshake.

**Referral links:** options with `affiliate: true` carry a referral `redeem_url` and a `referral_disclosure`, and the
script marks those lines `(referral link)`. The `source_url` printed is the vendor's own pricing page. Affiliate status
is not a ranking factor. Results cover tracked providers only (vendors not tracked may cost less), and prices are
monthly list prices before tax. Confirm on the vendor page before spending.
