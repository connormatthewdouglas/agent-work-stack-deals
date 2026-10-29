"""/install/: add the Lantern Works MCP server / skill to an agent (content from Beacon's staged draft,
reviewed: tool list, versions and the 'tested' line reflect checks actually run). Also the small
'Using an AI agent?' link snippet appended to comparison pages."""
from __future__ import annotations

import html
import json
from pathlib import Path

PATH = "install"
TESTED_ON = "2026-10-29"
TESTED_VERSION = "0.3.19"
def _server_tools() -> tuple[str, ...]:
    """Tool names straight from mcp_server/server.py (every @mcp.tool function), so the page can't drift (audit T2/M1)."""
    import re
    src = (Path(__file__).resolve().parents[1] / "mcp_server" / "server.py").read_text(encoding="utf-8")
    names = re.findall(r"@mcp\.tool\([^)]*\)\n(?:@\w+\n)*def (\w+)\(", src)
    order = ["compare_gpu_prices", "get_price_changes", "optimize_stack", "optimize_agent_stack", "search_deals", "compare_deals", "get_deal"]
    return tuple(sorted(names, key=lambda n: (order.index(n) if n in order else len(order), n)))


TOOLS = _server_tools()
CFG = {"command": "uvx", "args": ["lantern-works-deals-mcp"]}
HOSTED = "https://lantern-works-mcp.lantern-works.workers.dev/mcp"
LLAMA = """import asyncio
from llama_index.tools.mcp import BasicMCPClient, McpToolSpec

async def main():
    client = BasicMCPClient("https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=install")
    tools = await McpToolSpec(client=client).to_tool_list_async()
    print([t.metadata.name for t in tools])
    print(await client.call_tool("compare_gpu_prices", {"gpu": "H100"}))

asyncio.run(main())"""
ROO_HTTP = json.dumps({"mcpServers": {"lantern-works-deals": {"type": "streamable-http", "url": HOSTED + "?ref=install"}}}, indent=2)
CONTINUE = """name: Lantern Works deals
version: 0.0.1
schema: v1
mcpServers:
  - name: lantern-works-deals
    command: uvx
    args:
      - lantern-works-deals-mcp"""
CURSOR_LINK = "cursor://anysphere.cursor-deeplink/mcp/install?name=lantern-works-deals&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJsYW50ZXJuLXdvcmtzLWRlYWxzLW1jcCJdfQ=="
VSCODE_LINK = ("https://vscode.dev/redirect/mcp/install?name=lantern-works-deals&config="
               "%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22lantern-works-deals-mcp%22%5D%7D")


def link_snippet(base: str) -> str:
    return (f'  <p class="lw-agent-link" style="font-size:.85em;opacity:.75;margin-top:2rem">\n'
            f'    Using an AI agent? <a href="{base}/install/">Add Lantern Works to your agent</a> (free MCP server, read-only).\n'
            f'  </p>\n')


def _pre(s: str) -> str:
    # H8: styled box with a copy button (button is added by COPY_JS; plain <pre> still works without JS).
    return f'<div class="codebox"><pre>{html.escape(s)}</pre></div>'


COPY_JS = """<script>
document.querySelectorAll(".codebox").forEach(b=>{const btn=document.createElement("button");btn.type="button";btn.className="copy";btn.textContent="Copy";
btn.addEventListener("click",()=>{navigator.clipboard.writeText(b.querySelector("pre").innerText).then(()=>{btn.textContent="Copied";setTimeout(()=>btn.textContent="Copy",1500)},()=>{btn.textContent="Select and copy"})});b.appendChild(btn)});
</script>
"""


def write(g) -> str:
    base = g.BASE
    desktop = json.dumps({"mcpServers": {"lantern-works-deals": CFG}}, indent=2)
    vscode = json.dumps({"servers": {"lantern-works-deals": {"type": "stdio", **CFG}}}, indent=2)
    tools = ", ".join(f"<code>{t}</code>" for t in TOOLS)
    body = f"""  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › <a href="{base}/for-agents/">For agents</a> › Install</nav>
  <h1>GPU price monitor for your agent</h1>
  <p><strong>GPU price comparison for agents, checked daily.</strong> Free, read-only MCP server (<code>uvx lantern-works-deals-mcp</code>, version {TESTED_VERSION}); <code>compare_gpu_prices</code> is the main tool. Rate and provider counts change daily: see the live <a href="{base}/api/v1/gpu-prices.json">feed</a>. Some result links are referral links.</p>
  <p><strong>Know when GPU prices move.</strong> Lantern Works re-reads every tracked GPU rental rate daily from the vendor's own pricing page. Your agent can check what moved since yesterday and act on it, every day, with no API key:</p>
  <ul>
    <li><a href="{base}/api/v1/gpu-price-changes.json">/api/v1/gpu-price-changes.json</a>: rates that went down, up, newly tracked or dropped out between the last two daily snapshots, each with the vendor's source page (<a href="{base}/api/v1/gpu-price-changes.xml">RSS</a>).</li>
    <li><code>compare_gpu_prices(gpu="H100", include_history=true)</code>: today's cheapest rates among tracked providers plus each rate's price history and recent changes.</li>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/gpu-price-monitor">GPU price monitor example</a>: a zero-dependency script that alerts when a tracked rate drops by a set percent. Run it on a daily cron.</li>
  </ul>
  {_pre("uvx lantern-works-deals-mcp")}
  <p class="meta">Jump to: <a href="#hosted">Hosted endpoint</a> · <a href="#claude-code">Claude Code</a> · <a href="#claude-desktop">Claude Desktop</a> · <a href="#cursor">Cursor</a> · <a href="#vscode">VS Code</a> · <a href="#cline">Cline</a> · <a href="#llamaindex">LlamaIndex</a> · <a href="#openwebui">Open WebUI</a> · <a href="#roo-code">Roo Code</a> · <a href="#continue">Continue</a> · <a href="#generic">Any MCP client</a> · <a href="#examples">Framework examples</a> · <a href="{base}/methodology/">How prices are checked</a></p>
  <h2 id="add">Add Lantern Works to your agent</h2>
  <p>Free, read-only, no API key. MCP server: <code>lantern-works-deals-mcp</code> (<a href="https://pypi.org/project/lantern-works-deals-mcp/">PyPI</a>, MIT; MCP Registry <code>io.github.connormatthewdouglas/lantern-works-deals</code>). Needs <a href="https://docs.astral.sh/uv/">uv</a> (or pipx). Tools: {tools}.</p>
  <p class="meta">Tested {TESTED_ON}: a clean <code>uvx lantern-works-deals-mcp</code> ({TESTED_VERSION}) initializes over stdio and all {len(TOOLS)} tools return results.</p>


  <h2 id="hosted">Hosted endpoint (no install)</h2>
  <p>The same {len(TOOLS)} read-only tools (plus the opt-in <a href="#price-watch">price-watch</a> tools below) over streamable HTTP, served from a free Cloudflare Worker: <code>https://lantern-works-mcp.lantern-works.workers.dev/mcp</code>. It counts calls only as anonymous totals per tool per day (no IPs, user agents or arguments), published at <a href="https://lantern-works-mcp.lantern-works.workers.dev/stats">/stats</a>. The <code>?ref=</code> tag below just records that the link came from this page (counts at <a href="https://lantern-works-mcp.lantern-works.workers.dev/stats.json">/stats.json</a>).</p>
  {_pre("claude mcp add --transport http lantern-works-deals https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=install")}
  <p>Claude Desktop / Cursor / VS Code (<code>"type": "http"</code> or <code>"url"</code> server): <code>https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=install</code></p>

  <h3 id="price-watch">Price-drop webhooks (hosted only, free, opt-in)</h3>
  <p>The hosted endpoint also has four opt-in tools for GPU price alerts. Call <code>create_watch_key</code> with a public <code>https</code> webhook URL (email optional, contact only, nothing is mailed); it returns an <code>api_key</code> and a <code>webhook_signing_secret</code> <strong>once</strong>. Then <code>watch_price(gpu="H100", max_hourly_usd=2.0)</code> (optional <code>region</code>, <code>kinds</code> of <code>down</code>/<code>up</code>/<code>new</code>), <code>list_watches</code> and <code>delete_watch</code>, passing <code>api_key</code> or an <code>Authorization: Bearer</code> header. After each daily refresh, matching changes are POSTed once per event with <code>X-Lantern-Signature: t=&lt;unix&gt;,v1=&lt;HMAC-SHA256(secret, "t.body")&gt;</code>. Stored for this opt-in only: a hash of the key, the webhook URL, the optional email, your watches and per-key daily counts (never call arguments otherwise). The local server has no keys and no watches.</p>

  <h2 id="claude-code">Claude Code</h2>
  {_pre("claude mcp add lantern-works-deals -- uvx lantern-works-deals-mcp")}

  <p>Or as a Claude Code plugin (skill + MCP server) from our free, self-hosted marketplace:</p>
  {_pre("/plugin marketplace add connormatthewdouglas/agent-work-stack-deals" + chr(10) + "/plugin install lantern-works-deals@lantern-works")}

  <h2 id="claude-desktop">Claude Desktop</h2>
  <p>Settings → Developer → Edit Config (<code>claude_desktop_config.json</code>):</p>
  {_pre(desktop)}
  <p>Restart Claude Desktop. If <code>uvx</code> isn't on Claude's PATH, use the absolute path from <code>which uvx</code>.</p>

  <h2 id="cursor">Cursor</h2>
  <p><a href="{html.escape(CURSOR_LINK)}">One-click install</a>, or add the same JSON to <code>~/.cursor/mcp.json</code> / <code>.cursor/mcp.json</code>.</p>

  <h2 id="vscode">VS Code (Copilot agent mode)</h2>
  <p><a href="{html.escape(VSCODE_LINK)}">Install in VS Code</a>, or <code>.vscode/mcp.json</code>:</p>
  {_pre(vscode)}

  <h2 id="cline">Cline</h2>
  <p>MCP Servers → Configure → <code>cline_mcp_settings.json</code> (tested {TESTED_ON}: this exact config started the server and <code>tools/list</code> returned all {len(TOOLS)} tools):</p>
  {_pre(desktop)}

  <h2 id="llamaindex">LlamaIndex</h2>
  <p>Uses <code>pip install llama-index-tools-mcp</code> (<a href="https://developers.llamaindex.ai/python/framework/module_guides/mcp/llamaindex_mcp/">LlamaIndex MCP docs</a>). This uses the hosted endpoint; for the local server use <code>BasicMCPClient("uvx", args=["lantern-works-deals-mcp"])</code>:</p>
  {_pre(LLAMA)}
  <p class="meta">Tested {TESTED_ON}: both clients listed all {len(TOOLS)} tools and <code>compare_gpu_prices</code> returned live rates.</p>

  <h2 id="openwebui">Open WebUI</h2>
  <p>Open WebUI 0.6.31+ connects to MCP servers over streamable HTTP (<a href="https://docs.openwebui.com/features/extensibility/mcp/">Open WebUI MCP docs</a>). As an admin: Settings → Admin → Integrations → External Tool Servers → + Add Connection, set <strong>Type</strong> to <strong>MCP (Streamable HTTP)</strong> (not OpenAPI), Server URL:</p>
  {_pre("https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=install")}
  <p>No auth is needed. To run the local server instead, bridge it with <a href="https://github.com/open-webui/mcpo">mcpo</a> and add <code>http://localhost:8000</code> as an <strong>OpenAPI</strong> connection:</p>
  {_pre("uvx mcpo --port 8000 -- uvx lantern-works-deals-mcp")}
  <p class="meta">Tested {TESTED_ON}: the hosted URL answers MCP <code>tools/list</code> with all {len(TOOLS)} tools; through mcpo all {len(TOOLS)} tools appeared as OpenAPI routes and <code>compare_gpu_prices</code> returned rates. If mcpo fails to start with an import or <code>ssl_certfile</code> error, a dependency release broke it; <code>uvx --with "mcp&lt;2" --with "fastapi&lt;0.120" mcpo …</code> worked.</p>

  <h2 id="roo-code">Roo Code</h2>
  <p>MCP icon → Edit Global MCP (<code>mcp_settings.json</code>) or Edit Project MCP (<code>.roo/mcp.json</code>) (<a href="https://docs.roocode.com/features/mcp/using-mcp-in-roo">Roo Code MCP docs</a>):</p>
  {_pre(desktop)}
  <p>Hosted endpoint instead (Roo needs <code>"type"</code> for URL servers):</p>
  {_pre(ROO_HTTP)}

  <h2 id="continue">Continue</h2>
  <p>Save as <code>.continue/mcpServers/lantern-works-deals.yaml</code> in your workspace; MCP tools work in Agent mode (<a href="https://docs.continue.dev/customize/deep-dives/mcp">Continue MCP docs</a>):</p>
  {_pre(CONTINUE)}
  <p>Hosted endpoint instead: replace the <code>command</code> and <code>args</code> lines with <code>type: streamable-http</code> and <code>url: https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=install</code>.</p>
  <p class="meta">Tested {TESTED_ON} (Roo Code, Continue): the configs above parse, and the exact command and URL in them start or reach the server and list all {len(TOOLS)} tools. Not yet tested inside the editors themselves.</p>

  <h2>Skills-based agents (Claude Code skills, OpenClaw)</h2>
  {_pre("npx skills add connormatthewdouglas/agent-work-stack-deals")}
  <p>Installs <a href="{base}/SKILL.md">SKILL.md</a> (checked {TESTED_ON} with <code>-a claude-code</code>). For OpenClaw MCP, use the generic stdio config below.</p>

  <h2 id="generic">Any MCP client (generic)</h2>
  <p>Command <code>uvx</code>, args <code>["lantern-works-deals-mcp"]</code>, transport stdio. pipx: <code>pipx run lantern-works-deals-mcp</code>. Docker: build the repo's <code>Dockerfile</code> and run <code>docker run -i --rm &lt;image&gt;</code>. Optional env: <code>LANTERN_DEALS_FILE</code>, <code>LANTERN_GPU_PRICES_FILE</code> (offline JSON).</p>
  <p>The server only fetches the two public JSON files below and sends <code>User-Agent: lantern-works-deals-mcp/&lt;version&gt;</code>, nothing that identifies you.</p>

  <h2>Demo: cheapest H100 for 100 hours</h2>
  <p>A ~30-second terminal recording with live data from 2026-10-28. It starts <code>uvx lantern-works-deals-mcp</code>, calls <code>compare_gpu_prices</code> for H100, then compares the 100-hour total of the cheapest tracked rate with the next one and with the most expensive one. Each rate shows its source and check time, and referral links are labeled. Prices change; tracked providers only.</p>
  <p><img src="/docs/demo/cheapest-h100-100h.gif" alt="Terminal demo: compare_gpu_prices for H100, 100-hour totals for tracked providers" width="1094" height="605" loading="lazy" style="max-width:100%;height:auto"></p>
  <p>Recording: <a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/docs/demo/cheapest-h100-100h.cast">asciinema .cast</a> (play with <code>asciinema play</code>) · script: <a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/docs/demo/demo.py">docs/demo/demo.py</a></p>

  <h2 id="examples">Framework examples</h2>
  <ul>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/langgraph-cheapest-h100">LangGraph / LangChain</a>: cheapest H100 via <code>langchain-mcp-adapters</code> (tool called directly, no LLM key needed)</li>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/crewai-cheapest-gpu">CrewAI</a>: cheapest GPU for a described job via <code>MCPServerAdapter</code> (direct tool path tested; LLM agent path untested)</li>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/openai-agents-cheapest-gpu">OpenAI Agents SDK</a>: cheapest GPU for a described job via <code>MCPServerStdio</code> (direct tool path tested; LLM agent path untested)</li>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/stack-optimizer">Stack optimizer (OpenAI Agents SDK)</a>: describe an agent's job and get the cheapest cited stack via <code>optimize_agent_stack</code> (direct tool path tested; LLM agent path untested). Browser version: <a href="https://thelanternworks.com/stack/">/stack/</a></li>
    <li><a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/tree/main/examples/gpu-price-watcher">GPU price watcher</a>: prints tracked GPU price moves since a date via <code>get_price_changes</code>, each with the vendor source URL, plus a sample cron line (0.3.8+)</li>
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
""" + COPY_JS
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell("Install Lantern Works in your agent (MCP: Claude, Cursor, VS Code, LlamaIndex, Open WebUI, Roo Code, Continue)",
                                "Add the free, read-only Lantern Works MCP server to Claude Code, Claude Desktop, Cursor, VS Code, LlamaIndex, Open WebUI, Roo Code, Continue or any MCP client: uvx lantern-works-deals-mcp.",
                                f"{base}/{PATH}/", body), encoding="utf-8")
    return PATH
