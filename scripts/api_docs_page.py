"""/api/: public JSON feeds and hosted MCP documentation."""
from __future__ import annotations

from pathlib import Path

PATH = "api"
ROOT = Path(__file__).resolve().parents[1]


def write(g) -> str:
    base = g.BASE
    body = f"""  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › API</nav>
  <h1>Public API</h1>
  <p>Lantern Works publishes GPU rental prices and deal data as JSON on this site, and a hosted MCP server. The feeds and the MCP server are public: no API key is required.</p>

  <h2 id="endpoints">JSON feeds</h2>
  <p>These URLs are already linked from pages on this site. Each returned HTTP 200 when checked, with no Authorization header.</p>
  <ul>
    <li><a href="{base}/api/v1/gpu-prices.json"><code>{base}/api/v1/gpu-prices.json</code></a> — complete GPU price feed. Top-level fields include <code>feed_updated_at</code>, <code>license</code>, <code>methodology</code>, <code>ranking</code>, <code>hours_per_month</code> (730), <code>rates</code>, <code>unpriced</code> and <code>held_stale</code>. Each <code>rates</code> row includes <code>advertiser</code>, <code>gpu</code>, <code>vram_gb</code>, <code>price_usd</code>, <code>unit</code>, <code>tier</code>, <code>hourly_equiv_usd</code>, <code>billing</code>, <code>source_url</code> and <code>verified_at</code>.</li>
    <li><a href="{base}/api/v1/gpu-price-changes.json"><code>/api/v1/gpu-price-changes.json</code></a> — rates that went down, up, newly tracked or dropped between the last two daily snapshots (RSS: <a href="{base}/api/v1/gpu-price-changes.xml"><code>/api/v1/gpu-price-changes.xml</code></a>).</li>
    <li><a href="{base}/api/v1/gpu-prices/history.json"><code>/api/v1/gpu-prices/history.json</code></a> — daily price history.</li>
    <li><a href="{base}/api/v1/gpu/index.json"><code>/api/v1/gpu/index.json</code></a> — small per-model index. Each model has a feed such as <a href="{base}/api/v1/gpu/h100.json"><code>/api/v1/gpu/h100.json</code></a>.</li>
    <li><a href="{base}/api/v1/deals.json"><code>/api/v1/deals.json</code></a> — deal feed. <a href="{base}/deals.json"><code>/deals.json</code></a> is a legacy alias of the same feed.</li>
    <li><a href="{base}/api/v1/stack-pricing.json"><code>/api/v1/stack-pricing.json</code></a> — cited plan prices for stack cost estimates.</li>
    <li><a href="{base}/api/v1/coverage.json"><code>/api/v1/coverage.json</code></a> — GPU model × vendor coverage matrix.</li>
    <li><a href="{base}/api/v1/gpu-price-index.json"><code>/api/v1/gpu-price-index.json</code></a> and <a href="{base}/api/v1/gpu-price-index.csv"><code>.csv</code></a> — historical index used on the GPU index pages.</li>
    <li><a href="{base}/api/v1/receipts.json"><code>/api/v1/receipts.json</code></a> and <a href="{base}/api/v1/receipts-proof-pack.json"><code>/api/v1/receipts-proof-pack.json</code></a> — receipt records linked from the <a href="{base}/receipts/">receipts</a> page.</li>
  </ul>

  <h2 id="mcp">Hosted MCP</h2>
  <p>Streamable HTTP at <code>https://lantern-works-mcp.lantern-works.workers.dev/mcp</code>. The endpoint accepts POST JSON-RPC. A GET request returns 405 and states that Server-sent event streams are not offered; use POST. No API key is required for the public tools: an <code>initialize</code> call with no Authorization header returned HTTP 200.</p>

  <h2 id="auth">Authentication</h2>
  <p>No API key is required for the JSON feeds or the hosted MCP server. A GET of <code>/api/v1/gpu-prices.json</code> and an MCP <code>initialize</code> with no Authorization header both returned HTTP 200.</p>

  <h2 id="cors">CORS</h2>
  <p>JSON feeds (checked on <code>/api/v1/gpu-prices.json</code>): GET and HEAD responses include <code>Access-Control-Allow-Origin: *</code> and no other <code>Access-Control-*</code> headers. An OPTIONS preflight with an <code>Origin</code> header returned 405 and sent no <code>Access-Control-*</code> headers.</p>
  <p>Hosted MCP: OPTIONS (204), GET and POST responses include <code>Access-Control-Allow-Origin: *</code>, <code>Access-Control-Allow-Headers: content-type, authorization, mcp-protocol-version, mcp-session-id</code>, and <code>Access-Control-Allow-Methods: GET, POST, OPTIONS</code>.</p>

  <h2 id="rate-limits">Rate limits</h2>
  <p>There is no published rate limit for the public JSON feeds or the hosted MCP endpoint, in response headers or in the worker source for those endpoints. Please use them reasonably.</p>

  <h2 id="license">License and attribution</h2>
  <p>The price and deal data is licensed under <a href="https://creativecommons.org/licenses/by/4.0/" rel="license noopener">Creative Commons Attribution 4.0 (CC BY 4.0)</a>; see <a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/LICENSE-DATA" rel="noopener">LICENSE-DATA</a>. You may copy, share and adapt the data, including commercially, as long as you credit <strong>Lantern Works</strong> and link to <a href="{base}/">thelanternworks.com</a>. The site's generators and the MCP server package are released under the <a href="https://github.com/connormatthewdouglas/agent-work-stack-deals/blob/main/LICENSE" rel="license noopener">MIT License</a>. The same terms appear in the <code>license</code> field of the JSON feeds and on the <a href="{base}/methodology/#license">Methodology</a> page.</p>

  <h2>See also</h2>
  <ul>
    <li><a href="{base}/methodology/">Methodology</a> — how prices are checked and ranked.</li>
    <li><a href="{base}/privacy/">Privacy</a>.</li>
    <li><a href="{base}/disclosure/">Affiliate disclosure</a>.</li>
  </ul>
"""
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell(
        "Public API | Lantern Works",
        "Public JSON feeds and hosted MCP for Lantern Works GPU prices and deals: endpoints, authentication, CORS, rate limits and license.",
        f"{base}/{PATH}/",
        body,
    ), encoding="utf-8")
    return PATH
