"""/privacy/: what Lantern Works stores, kept accurate to the code and PRIVACY.md."""
from __future__ import annotations

from pathlib import Path

PATH = "privacy"
ROOT = Path(__file__).resolve().parents[1]


def write(g) -> str:
    base = g.BASE
    repo = "https://github.com/connormatthewdouglas/agent-work-stack-deals"
    body = f"""  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › Privacy</nav>
  <h1>Privacy</h1>
  <p>This page describes what Lantern Works stores. It matches the code in this repository and the longer notes in <a href="{repo}/blob/main/PRIVACY.md">PRIVACY.md</a> and <a href="{repo}/blob/main/docs/MEASUREMENT.md">docs/MEASUREMENT.md</a>.</p>

  <h2 id="mcp-telemetry">The MCP package (<code>lantern-works-deals-mcp</code>)</h2>
  <p>Telemetry is <strong>off by default</strong>. With nothing set, the server sends no telemetry and writes no telemetry file. Its only network requests fetch the public feeds, with <code>User-Agent: lantern-works-deals-mcp/&lt;version&gt;</code>.</p>
  <p>Set <code>LANTERN_TELEMETRY=1</code> to opt in to an anonymous tool-call counter. It is enabled only when the value is exactly <code>1</code>. At most once per UTC day the server sends aggregate counts only: tool name, package version, UTC day and number of calls. It does not send tool arguments, queries or results, or any user, host, client or install identifier. Local counts sit in a cache file until the day is over (at most 7 unsent days). Failures are ignored and never block a tool call.</p>
  <p>The collector stores only the total per (day, tool, version). Its rate limiter keeps an in-memory hash and does not write IP addresses to storage. Aggregate totals are public at the collector&rsquo;s <code>/v1/stats</code>. To turn telemetry off, unset <code>LANTERN_TELEMETRY</code> or set it to anything other than <code>1</code>.</p>

  <h2 id="hosted">The hosted MCP endpoint</h2>
  <p>The hosted worker at <code>https://lantern-works-mcp.lantern-works.workers.dev</code> keeps anonymous daily counters, public at <a href="https://lantern-works-mcp.lantern-works.workers.dev/stats.json">/stats.json</a>.</p>
  <ul>
    <li><strong>Call counts</strong> are totals per UTC day, kind (feed, tool or initialize), path or tool name, <code>ref</code> tag, user-agent class and source class. Those rows do not include an IP address or the raw user agent.</li>
    <li><strong>Distinct-caller counts</strong> (for <code>/mcp</code> POSTs and successful feed fetches) store only a <strong>daily-salted SHA-256 hash of the IP address and user agent</strong>, together with the same coarse buckets. The raw IP and user agent are never stored, logged or returned. A random salt is created for each UTC day and deleted when that day ends, so hashes from different days cannot be linked. The hashes themselves are kept for 120 days, then deleted. House and CI traffic is not counted.</li>
    <li><strong>Demand counts</strong> (for hosted GPU tool calls) are totals per UTC day, tool, GPU family, region group, price tier and cheapest provider. The GPU family and region group are bucketed to fixed lists, and anything else is stored as <code>other</code>; the price tier and provider describe the first result in our own answer. These rows do not include an IP address, the raw user agent, a caller hash, the tool arguments or any free text. They are kept for 120 days. House and CI traffic and known bots are not counted.</li>
    <li><strong>Opt-in price watches:</strong> if you create a watch key, the worker stores a hash of the key, the webhook URL, an optional email, your watches and per-key daily counts. Call arguments are not stored.</li>
  </ul>

  <h2 id="website">This website</h2>
  <p>The site uses Cloudflare Web Analytics for page views; it sets no cookies. Clicks on search, compare, calculator and outbound links are counted as virtual page views under <code>/e/...</code>. Deal links go through a <code>/go/&lt;deal-id&gt;</code> redirect on the telemetry worker, which adds one to an aggregate counter per UTC day, deal, provider, <code>src</code> and <code>?ref=</code> tag, then redirects to that deal&rsquo;s listed redeem URL. That worker does not store an IP address, cookie, user agent or other identifier.</p>

  <p class="meta">More: <a href="{base}/methodology/">Methodology</a> · <a href="{base}/install/">Install the MCP server</a> · <a href="{repo}">Source code</a></p>
"""
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell(
        "Privacy: what Lantern Works stores",
        "What Lantern Works stores: opt-in MCP telemetry, hosted daily-salted SHA-256 hashes of IP and user agent for distinct-caller counts, and cookie-free site analytics.",
        f"{base}/{PATH}/",
        body,
    ), encoding="utf-8")
    return PATH
