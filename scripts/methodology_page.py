"""/methodology/: how prices are collected, verified and held, in plain words. Every rule here is read from the
code (core/gpu.py constants, the refresh workflow cron) or the feed's own `methodology` list, so it can't drift."""
from __future__ import annotations

import html
import re
from pathlib import Path

PATH = "methodology"
ROOT = Path(__file__).resolve().parents[1]


def _const(name: str, src: str) -> int:
    return int(re.search(rf"^{name}\s*=\s*(\d+)", src, re.M).group(1))


def _crons() -> list[str]:
    wf = (ROOT / ".github" / "workflows" / "gpu-refresh.yml").read_text(encoding="utf-8")
    return re.findall(r'cron:\s*"(\d+ \d+) \* \* \*"', wf)


def _hhmm(c: str) -> str:
    m, h = c.split()
    return f"{int(h):02d}:{int(m):02d} UTC"


def write(g) -> str:
    base = g.BASE
    src = (ROOT / "core" / "gpu.py").read_text(encoding="utf-8")
    stale, market = _const("STALE_DAYS", src), _const("MIN_MARKET_OFFERS", src)
    crons = _crons()
    primary, fallback = (_hhmm(crons[0]), _hhmm(crons[1])) if len(crons) >= 2 else ("daily", "later the same day")
    repo = "https://github.com/connormatthewdouglas/agent-work-stack-deals"
    body = f"""  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › Methodology</nav>
  <h1>How Lantern Works collects and checks prices</h1>
  <p>This page explains, in plain words, where every price on this site comes from, how it is checked, when it is held back, and how you may reuse the data. The same rules are in the <code>methodology</code> field of the <a href="{base}/api/v1/gpu-prices.json">GPU price feed</a>.</p>

  <h2 id="collected">How prices are collected</h2>
  <ul>
    <li>Every price comes from the vendor's own public pricing page or API. Each rate keeps a link to that page (<code>source_url</code>) and the exact text found there (<code>evidence.quote</code>).</li>
    <li>A scheduled job re-reads every source page once a day. It respects each site's robots.txt and waits between requests.</li>
    <li>Prices are never guessed. If there is no single verified price, the price is left empty and a short label describes the pricing model instead.</li>
    <li>All GPU prices are per GPU. A multi-GPU server's price is divided by its number of GPUs; the whole-server price is kept alongside.</li>
    <li>For marketplaces where hosts set their own prices, the listed price is the median offer, shown with the lowest offer and the number of offers.</li>
    <li>Cost estimates leave out storage, data transfer (egress), extra CPU and taxes. Each vendor's published terms for these, or "not published", are listed with their source.</li>
  </ul>

  <h2 id="verified">How prices are verified</h2>
  <ul>
    <li>A price is updated only when the job actually read it from the vendor's page or API. <code>verified_at</code> is when the price was last read successfully; <code>checked_at</code> is the last attempt.</li>
    <li>A few vendors block automated checks. Their rows are manual snapshots: <code>snapshot_at</code> says when they were captured, and they are held automatically after <code>hold_after</code> unless checked again.</li>
    <li>Before any change goes live, the site's tests must pass. A separate daily check confirms that every source page is reachable and still shows the quoted price.</li>
    <li>Ranking is by estimated cost for the requested use. Whether a link is a referral link is never a ranking factor; referral links are labeled.</li>
  </ul>

  <h2 id="held">When prices are held</h2>
  <p>A held price is still listed with its reason, but it is never ranked or called the cheapest.</p>
  <ul>
    <li><strong>Not re-verified for {stale} days:</strong> the rate is held until a fresh check succeeds.</li>
    <li><strong>Thin marketplace:</strong> a marketplace rate with fewer than {market} available offers is held, because a handful of listings is not a reliable price.</li>
    <li><strong>Stale vendor page:</strong> if a vendor's published prices are out of date, all of that vendor's rates are held.</li>
  </ul>

  <h2 id="reserved">Why reserved rates are not "cheapest"</h2>
  <p>Some vendors publish lower prices that need a reservation, a contract or a minimum term. Those prices are real, so they are shown, but they are not comparable with pay-as-you-go rates you can start and stop at any time. They are always listed separately, after every pay-as-you-go rate, and are never counted when this site calls a rate the cheapest among tracked providers.</p>

  <h2 id="cadence">Update schedule</h2>
  <ul>
    <li>GPU prices are refreshed once a day. The job is scheduled for {primary}, with a backup run at {fallback} that only runs if the first one did not.</li>
    <li>Scheduled runs can start late. If the last refresh is more than a day old, an automatic check flags it.</li>
    <li>Each refresh is saved as a daily snapshot. What changed between snapshots is published at <a href="{base}/api/v1/gpu-price-changes.json">/api/v1/gpu-price-changes.json</a> (<a href="{base}/gpu/changes/">changes page</a>) and the full history at <a href="{base}/api/v1/gpu-prices/history.json">/api/v1/gpu-prices/history.json</a>.</li>
    <li>The deal feed shows when it was last updated (<code>updated_at</code>), and every deal shows when it was last verified (<code>verified_at</code>).</li>
  </ul>

  <h2 id="license">License</h2>
  <p>The price and deal data (the JSON feeds under <code>/api/v1/</code>, <code>deals.json</code>, the price history and the tables on this site) are licensed under <a href="https://creativecommons.org/licenses/by/4.0/" rel="license noopener">Creative Commons Attribution 4.0 (CC BY 4.0)</a>; see <a href="{repo}/blob/main/LICENSE-DATA" rel="noopener">LICENSE-DATA</a>. You may copy, share and adapt the data, including commercially, as long as you credit <strong>Lantern Works</strong> and link to <a href="{base}/">{html.escape(base.replace("https://", ""))}</a>, for example: &ldquo;GPU price data: Lantern Works, CC BY 4.0&rdquo;. Each JSON feed carries the same terms in its <code>license</code> field.</p>
  <p>The code (this site's generators and the MCP server package) is released under the <a href="{repo}/blob/main/LICENSE" rel="license noopener">MIT License</a>. Prices change; always confirm on the vendor's page before spending.</p>

  <p class="meta">More: <a href="{base}/for-agents/">For agents</a> (feed schema) · <a href="{base}/install/">Install the MCP server</a> · <a href="{base}/embed/">Embed a price badge</a> · <a href="{repo}">Source code</a></p>
"""
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell("Methodology: how Lantern Works collects, verifies and holds prices",
                                "Where Lantern Works prices come from, how they are checked daily, when they are held, why reserved rates are not ranked cheapest, and the license (CC BY 4.0 data, MIT code).",
                                f"{base}/{PATH}/", body), encoding="utf-8")
    return PATH
