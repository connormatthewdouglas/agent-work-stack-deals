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

  <h2 id="availability-expiry">Stock claims expire</h2>
  <p>Every stock claim (<code>availability.in_stock</code> true or false) in the GPU price feeds carries <code>checked_at</code> and <code>availability_expires_at</code> as UTC instants. A claim is still valid at the exact expiry instant: if now equals <code>availability_expires_at</code>, it is not yet unknown. It becomes unknown only when now is after that instant &mdash; not in stock, and not sold out. The clock is UTC: the current UTC time on the server or worker that applies the rule. There is no grace period and no clock-skew tolerance on this boundary.</p>
  <p>The hosted MCP tools, including <code>compare_gpu_prices</code> and <code>find_available_gpus</code>, apply this rule at request time and are the source of truth. Static JSON and HTML are written with a 25-minute build cutoff, so a claim that would expire within 25 minutes is already published as unknown; that cutoff is only for static output, not a consumer-side grace. Feed readers must still enforce <code>availability_expires_at</code> themselves.</p>

  <h2 id="probe-error">Availability probe errors</h2>
  <p>When an availability (stock or terms) probe raises an error, the affected row may carry <code>probe_error</code> and <code>probe_attempted_at</code>. These fields appear only when a probe raised an error; they are absent if none has. <code>probe_error</code> is an object with <code>type</code> (the exception class) and a sanitized <code>message</code> of at most 200 characters (secrets, tokens and credential-bearing URLs are stripped). <code>probe_attempted_at</code> is the attempt time (UTC). It is not a successful check: it does not refresh <code>verified_at</code> or the success <code>checked_at</code> used for freshness, the 72-hour ceiling and held-row expiry.</p>

  <h2 id="price-alerts">Hosted price alerts</h2>
  <p>The hosted MCP server also offers poll-only <code>create_alert</code>, <code>check_alerts</code> and <code>delete_alert</code>. An alert never fires on a <code>held_stale</code> row or a row whose last price verification is more than 48 hours old (or undated). Those rows appear in <code>skipped_stale</code> with <code>would_have_crossed</code>. That flag is computed for the current poll only and is not stored. The next <code>check_alerts</code> call re-evaluates the current feed: if the row is fresh again and the current price still crosses the threshold, it can fire on that poll. That is a new evaluation of the current price, not a delayed fire of the earlier stale crossing. If the now-fresh price no longer crosses, it does not fire.</p>
  <p><code>data_age_hours</code> (and the 48-hour alert rule) is measured from that row's own last price verification (<code>verified_at</code>, or <code>checked_at</code> if <code>verified_at</code> is missing), not from <code>feed_updated_at</code> or the time the feed file was written.</p>

  <h2 id="rent-here">Rent here links on top price rows</h2>
  <p>The top 3 rows of <code>compare_gpu_prices</code> (<code>results[]</code>), <code>find_available_gpus</code> (<code>available[]</code>) and <code>estimate_job_cost</code> (<code>results[]</code>) carry a clear <code>rent_here</code> line (the text &quot;Rent here: &quot; plus the URL) and a <code>rent_url</code> field. Both use the same counted <code>/go/?src=mcp</code> booking link as <code>tracked_url</code>, in brief and full mode. Show those links to the user. The top-level <code>referral_disclosure</code> is unchanged. Ranking never reads these fields, and quote <code>receipt</code> lines do not include them. These links are for a human to open; agents must not follow them automatically. The same facts are on the <a href="{base}/for-agents/#rent-here">For agents</a> page.</p>

  <h2 id="estimate-job-cost"><code>estimate_job_cost</code>: <code>job_days</code> and <code>tracked_url</code></h2>
  <p><code>job_days</code> is an optional input on the hosted and local <code>estimate_job_cost</code> tool (a number greater than 0; default omitted). It is wall-clock days, not GPU-days: the tool sets <code>job_hours = job_days &times; 24</code>. You may give <code>job_days</code>, or <code>job_hours</code>, or <code>work_units</code> plus a throughput, but not more than one of those three. Giving both <code>job_days</code> and <code>job_hours</code> returns <code>invalid_argument</code>. The converted duration must be at most 20,000 hours (hours, not GPU-hours), the same cap as <code>job_hours</code>; 834 days is rejected because 834 &times; 24 exceeds that cap. The response always includes <code>job_days</code> (and <code>job_hours</code>) at the top level and on each <code>results[]</code> row, rounded to four decimal places: if you passed hours, <code>job_days</code> is hours &divide; 24. A multi-day figure is a compute subtotal at current rates, not a reservation or a future-stock claim.</p>
  <p><code>tracked_url</code> is a response field only, on each <code>results[]</code> row that names a vendor (brief and full mode). It is a counted <code>/go/</code> booking link of the form <code>https://lantern-works-telemetry.lantern-works.workers.dev/go/&lt;deal-id&gt;?src=mcp</code> when the rate has a deal id, otherwise <code>.../go/v/&lt;vendor-slug&gt;?src=mcp</code>. The redirect target is taken from the served feeds (a disclosed referral URL, or the vendor's checked source page), not from the caller. Counts are aggregate only. Ranking never reads this field. Quote <code>receipt</code> lines do not include it. When any <code>tracked_url</code> is present, the result also has a top-level <code>referral_disclosure</code>. These links are for a human to open; agents must not follow them automatically. The same fields are described on the <a href="{base}/for-agents/#estimate-job-cost">For agents</a> page.</p>

  <h2>See also</h2>
  <ul>
    <li><a href="{base}/methodology/">Methodology</a> — how prices are checked and ranked.</li>
    <li><a href="{base}/for-agents/">For agents</a> — MCP tools and feed contract, including <code>estimate_job_cost</code>.</li>
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
