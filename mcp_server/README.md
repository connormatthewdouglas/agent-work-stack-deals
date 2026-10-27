# Lantern Works deals — MCP server (read-only, local stdio)

mcp-name: io.github.connormatthewdouglas/lantern-works-deals

Built on the official Python MCP SDK (`mcp>=1.10,<2`, FastMCP). Tools:

| Tool | Args | Returns |
|---|---|---|
| `search_deals` | `query`, `category`, `offer_type`, `max_price`, `tags[]`, `limit` (1-25, default 10), `cursor` | `{total, count, results[], next_cursor}` (summary fields only) |
| `compare_deals` | `ids` (2-5) | `{order, deals[], note}` best value first |
| `get_deal` | `id` | the deal's public record |

Errors: `{"error": {"code": "invalid_argument|invalid_cursor|not_found|feed_unavailable|feed_invalid", "message": ...}}`.

Data: `https://thelanternworks.com/api/v1/deals.json`, cached 5 min (stale copy served if a refetch fails). Overrides: `LANTERN_DEALS_FILE` (local JSON), `LANTERN_DEALS_URL`. Only an allow-list of public fields is returned. Ranking (`core/deals.py`) uses offer type, relevance, known price and `verified_at` freshness, never affiliate status or commission.

## Install

Published on [PyPI](https://pypi.org/project/lantern-works-deals-mcp/) as `lantern-works-deals-mcp` and in the MCP Registry as `io.github.connormatthewdouglas/lantern-works-deals`. With [uv](https://docs.astral.sh/uv/):

```bash
uvx lantern-works-deals-mcp   # stdio server
```

Claude Desktop (`claude_desktop_config.json`) / Cursor (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "lantern-works-deals": {
      "command": "uvx",
      "args": ["lantern-works-deals-mcp"]
    }
  }
}
```

Without uv: `pip install lantern-works-deals-mcp`, then use `"command": "lantern-works-deals-mcp"`.

### Fallback: from git

```bash
git clone https://github.com/connormatthewdouglas/agent-work-stack-deals.git
cd agent-work-stack-deals
python3 -m venv .venv && .venv/bin/pip install -r mcp_server/requirements.txt
```

```json
{
  "mcpServers": {
    "lantern-works-deals": {
      "command": "/ABS/PATH/agent-work-stack-deals/.venv/bin/python",
      "args": ["/ABS/PATH/agent-work-stack-deals/mcp_server/server.py"]
    }
  }
}
```

## Test

```bash
.venv/bin/pip install pytest && .venv/bin/python -m pytest -q tests
.venv/bin/python mcp_server/smoke/smoke_client.py   # real stdio client session, live feed
```

## Package

`pyproject.toml` at the repo root builds `lantern-works-deals-mcp` (published 0.1.0) with a `lantern-works-deals-mcp` console command. Local build: `python3 -m build`.

## Client validation

Transcripts in `smoke/`: official Python SDK client (`transcript.txt`), MCP Inspector CLI (`inspector_cli_transcript.txt`), OpenAI Agents SDK `MCPServerStdio` (`agents_sdk_transcript.txt`).

`server.json` is published in the MCP Registry as `io.github.connormatthewdouglas/lantern-works-deals`.
