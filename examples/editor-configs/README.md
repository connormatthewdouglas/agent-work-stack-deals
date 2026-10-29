# Editor MCP configs (Roo Code, Continue)

| File | Put it at |
|---|---|
| `roo-mcp.json` | Roo Code: MCP icon → Edit Global MCP (`mcp_settings.json`) or project `.roo/mcp.json` |
| `roo-mcp-hosted.json` | same, hosted endpoint (Roo needs `"type": "streamable-http"` for URL servers) |
| `continue-lantern-works-deals.yaml` | Continue: `.continue/mcpServers/lantern-works-deals.yaml` (tools work in Agent mode) |

Status (2026-10-29): the files parse, and the exact command/URL in them start or reach the server and list all 7 tools then available (0.3.19, before estimate_job_cost). **Not tested inside Roo Code or Continue themselves.** Reports welcome via GitHub issues.
