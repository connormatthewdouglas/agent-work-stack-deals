# Examples

Copy-and-adapt examples for the Lantern Works deals feed, GPU price API and MCP server (`uvx lantern-works-deals-mcp`, tools: `search_deals`, `compare_deals`, `get_deal`, `compare_gpu_prices`, `optimize_stack`).

| Path | What it does |
|---|---|
| `cheapest-gpu/SKILL.md` | Agent skill: cheapest tracked GPU for a model and monthly hours |
| `scraping-api-selection/SKILL.md` | Agent skill: choose a scraping/crawl/SERP API for a volume and budget |
| `free-agent-infra/SKILL.md` | Agent skill: assemble a $0 starter stack from free tiers |
| `gpu-price-monitor/` | Zero-dependency script that diffs `/api/v1/gpu-prices.json` snapshots (cron/Actions) |
| `langgraph-cheapest-h100/` | LangChain/LangGraph via `langchain-mcp-adapters`: launch the MCP server with uvx and find the cheapest H100 (`compare_gpu_prices`, no LLM key needed) |

Install one skill: `npx skills add https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/cheapest-gpu` (works once merged to main). Prices exclude storage, egress and taxes; confirm on the vendor page before spending. MIT.
