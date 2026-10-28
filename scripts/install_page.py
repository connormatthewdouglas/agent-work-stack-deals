"""/install/: add the Lantern Works MCP server / skill to an agent (content from Beacon's staged draft,
reviewed: tool list, versions and the 'tested' line reflect checks actually run). Also the small
'Using an AI agent?' link snippet appended to comparison pages."""
from __future__ import annotations

import html
import json
from pathlib import Path

PATH = "install"
TESTED_ON = "2026-10-27"
TESTED_VERSION = "0.3.4"
TOOLS = ("search_deals", "compare_deals", "get_deal", "compare_gpu_prices", "optimize_stack")
CFG = {"command": "uvx", "args": ["lantern-works-deals-mcp"]}
CURSOR_LINK = "cursor://anysphere.cursor-deeplink/mcp/install?name=lantern-works-deals&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJsYW50ZXJuLXdvcmtzLWRlYWxzLW1jcCJdfQ=="
VSCODE_LINK = ("https://vscode.dev/redirect/mcp/install?name=lantern-works-deals&config="
               "%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22lantern-works-deals-mcp%22%5D%7D")


def link_snippet(base: str) -> str:
    return (f'  <p class="lw-agent-link" style="font-size:.85em;opacity:.75;margin-top:2rem">\n'
            f'    Using an AI agent? <a href="{base}/install/">Add Lantern Works to your agent</a> (free MCP server, read-only).\n'
            f'  </p>\n')


def _pre(s: str) -> str:
    return f"<pre>{html.escape(s)}</pre>"


def write(g) -> str:
    base = g.BASE
    desktop = json.dumps({"mcpServers": {"lantern-works-deals": CFG}}, indent=2)
    vscode = json.dumps({"servers": {"lantern-works-deals": {"type": "stdio", **CFG}}}, indent=2)
    tools = ", ".join(f"<code>{t}</code>" for t in TOOLS)
    body = f"""  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › <a href="{base}/for-agents/">For agents</a> › Install</nav>
  <h1>Add Lantern Works to your agent</h1>
  <p>Free, read-only, no API key. MCP server: <code>lantern-works-deals-mcp</code> (<a href="https://pypi.org/project/lantern-works-deals-mcp/">PyPI</a>, MIT; MCP Registry <code>io.github.connormatthewdouglas/lantern-works-deals</code>). Needs <a href="https://docs.astral.sh/uv/">uv</a> (or pipx). Tools: {tools}.</p>
  <p class="meta">Tested {TESTED_ON}: a clean <code>uvx lantern-works-deals-mcp</code> ({TESTED_VERSION}) initializes over stdio and all {len(TOOLS)} tools return results.</p>

  <h2>Claude Code</h2>
  {_pre("claude mcp add lantern-works-deals -- uvx lantern-works-deals-mcp")}

  <p>Or as a Claude Code plugin (skill + MCP server) from our free, self-hosted marketplace:</p>
  {_pre("/plugin marketplace add connormatthewdouglas/agent-work-stack-deals" + chr(10) + "/plugin install lantern-works-deals@lantern-works")}

  <h2>Claude Desktop</h2>
  <p>Settings → Developer → Edit Config (<code>claude_desktop_config.json</code>):</p>
  {_pre(desktop)}
  <p>Restart Claude Desktop. If <code>uvx</code> isn't on Claude's PATH, use the absolute path from <code>which uvx</code>.</p>

  <h2>Cursor</h2>
  <p><a href="{html.escape(CURSOR_LINK)}">One-click install</a>, or add the same JSON to <code>~/.cursor/mcp.json</code> / <code>.cursor/mcp.json</code>.</p>

  <h2>VS Code (Copilot agent mode)</h2>
  <p><a href="{html.escape(VSCODE_LINK)}">Install in VS Code</a>, or <code>.vscode/mcp.json</code>:</p>
  {_pre(vscode)}

  <h2>Cline</h2>
  <p>MCP Servers → Configure → <code>cline_mcp_settings.json</code> (tested {TESTED_ON}: this exact config started the server and <code>tools/list</code> returned all {len(TOOLS)} tools):</p>
  {_pre(desktop)}

  <h2>Skills-based agents (Claude Code skills, OpenClaw)</h2>
  {_pre("npx skills add connormatthewdouglas/agent-work-stack-deals")}
  <p>Installs <a href="{base}/SKILL.md">SKILL.md</a> (checked {TESTED_ON} with <code>-a claude-code</code>). For OpenClaw MCP, use the generic stdio config below.</p>

  <h2>Any MCP client (generic)</h2>
  <p>Command <code>uvx</code>, args <code>["lantern-works-deals-mcp"]</code>, transport stdio. pipx: <code>pipx run lantern-works-deals-mcp</code>. Docker: build the repo's <code>Dockerfile</code> and run <code>docker run -i --rm &lt;image&gt;</code>. Optional env: <code>LANTERN_DEALS_FILE</code>, <code>LANTERN_GPU_PRICES_FILE</code> (offline JSON).</p>
  <p>The server only fetches the two public JSON files below and sends <code>User-Agent: lantern-works-deals-mcp/&lt;version&gt;</code>, nothing that identifies you.</p>

  <h2>Framework examples</h2>
  <ul>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/langgraph-cheapest-h100">LangGraph / LangChain</a>: cheapest H100 via <code>langchain-mcp-adapters</code> (tool called directly, no LLM key needed)</li>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/crewai-cheapest-gpu">CrewAI</a>: cheapest GPU for a described job via <code>MCPServerAdapter</code> (direct tool path tested; LLM agent path untested)</li>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/openai-agents-cheapest-gpu">OpenAI Agents SDK</a>: cheapest GPU for a described job via <code>MCPServerStdio</code> (direct tool path tested; LLM agent path untested)</li>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/gpu-price-monitor">GPU price monitor</a>: zero-dependency script that alerts when a tracked rate drops by a set percent, using the <a href="https://thelanternworks.com/api/v1/gpu-prices/history.json">price history API</a></li>
  </ul>
  <p>Some tool results include referral links (<code>affiliate: true</code>, <code>redeem_url</code>). <code>source_url</code> is the vendor's own pricing page.</p>

  <h2>Privacy and telemetry</h2>
  <p>Telemetry is <strong>off by default</strong>. Setting <code>LANTERN_TELEMETRY=1</code> in the server's environment opts in to an anonymous count of tool calls, sent at most once a day. Each count is only the tool name, package version, UTC day and number of calls. No arguments, IDs or IPs are sent or stored, and telemetry never blocks a tool call. Details: <a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/PRIVACY.md">PRIVACY.md</a>.</p>
  <h2>No MCP? Use the JSON</h2>
  <ul>
    <li>Deals: <a href="{base}/api/v1/deals.json">{base}/api/v1/deals.json</a></li>
    <li>GPU prices: <a href="{base}/api/v1/gpu-prices.json">{base}/api/v1/gpu-prices.json</a></li>
  </ul>
  <p>More: <a href="{base}/for-agents/">For agents</a> (endpoints, schema, offer types).</p>
"""
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell("Install Lantern Works in your agent (MCP, Claude Code, Cursor, VS Code)",
                                "Add the free, read-only Lantern Works MCP server to Claude Code, Claude Desktop, Cursor, VS Code or any MCP client: uvx lantern-works-deals-mcp.",
                                f"{base}/{PATH}/", body), encoding="utf-8")
    return PATH
