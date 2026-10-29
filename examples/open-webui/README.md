# Open WebUI

**Option A, hosted (no install).** Open WebUI 0.6.31+: Admin Settings → Integrations (External Tool Servers) → + Add Connection → Type **MCP (Streamable HTTP)**, URL:

```
https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=install
```

No auth.

**Option B, local server through mcpo** (OpenAPI bridge), then add `http://localhost:8000` as an **OpenAPI** connection:

```bash
uvx --with "mcp<2" --with "fastapi<0.120" mcpo --port 8000 -- uvx lantern-works-deals-mcp
```

The `mcp<2` / `fastapi<0.120` pins avoid import / `ssl_certfile` start-up errors seen with newer releases (2026-10-29).

Status: mcpo bridge tested 2026-10-29 (all 7 tools then available in 0.3.19 exposed as OpenAPI routes, `compare_gpu_prices` returned rates); hosted URL answers MCP `tools/list`. Adding the connection inside the Open WebUI admin UI and calling it from a chat model is **untested**.
