"""/methodology/: how prices are collected, verified and held, in plain words. Every rule here is read from the
code (core/gpu.py constants, the refresh workflow cron) or the feed's own `methodology` list, so it can't drift."""
from __future__ import annotations

import html
import json
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


def like_for_like(rates: list[dict], hours: int) -> list[dict]:
    """T34 dollar demo: same canonical_model + stated form factor + VRAM + GPUs per instance, on-demand,
    non-interruptible listed rates only (reserved/spot/marketplace never enter). Per-GPU hourly_equiv_usd;
    one (cheapest) rate per vendor; groups need >= 3 vendors. Sorted by monthly gap, largest first."""
    groups: dict = {}
    for r in rates:
        if (r.get("tier_class") != "on-demand" or r.get("interruptible") or r.get("price_status") != "listed"
                or r.get("hourly_equiv_usd") is None or r.get("form_factor") in (None, "", "not stated")):
            continue
        key = (r["canonical_model"], r["form_factor"], r["vram_gb"], r.get("gpu_count") or 1)
        best = groups.setdefault(key, {})
        if r["advertiser"] not in best or r["hourly_equiv_usd"] < best[r["advertiser"]]["hourly_equiv_usd"]:
            best[r["advertiser"]] = r
    out = []
    for (model, form, vram, n), vend in groups.items():
        if len(vend) < 3:
            continue
        s = sorted(vend.values(), key=lambda r: (r["hourly_equiv_usd"], r["advertiser"]))
        lo, hi = s[0], s[-1]
        out.append({"model": model, "form": form, "vram": vram, "gpus": n, "vendors": len(vend), "lo": lo, "hi": hi,
                    "gap_month": round((hi["hourly_equiv_usd"] - lo["hourly_equiv_usd"]) * hours)})
    return sorted(out, key=lambda x: (-x["gap_month"], x["model"]))


def _hr(v: float) -> str:
    p = f"{v:.3f}"
    return "$" + (p[:-1] if p.endswith("0") else p)


def _demo_html(base: str) -> str:
    doc = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    hours = int(doc.get("hours_per_month") or 730)
    rows = like_for_like(doc["rates"], hours)
    if not rows:
        return ""
    e = html.escape

    def cell(r):
        return (f'<a href="{e(r["source_url"])}" rel="noopener">{e(r["advertiser"])}</a> {_hr(r["hourly_equiv_usd"])}/hr'
                f' (${r["hourly_equiv_usd"] * hours:,.0f}/mo)')
    trs = "".join(f'<tr><td>{e(x["model"])} {e(x["form"])} {x["vram"]} GB, {x["gpus"]}-GPU instance</td><td>{x["vendors"]}</td>'
                  f'<td>{cell(x["lo"])}</td><td>{cell(x["hi"])}</td><td><strong>${x["gap_month"]:,}/mo per GPU</strong></td></tr>'
                  for x in rows)
    t = rows[0]
    return f"""
  <h2 id="like-for-like">A like-for-like example, in dollars</h2>
  <p>The same GPU can cost very different amounts depending on the vendor. Today's largest gap between tracked providers for an identical setup ({e(t["model"])} {e(t["form"])} {t["vram"]} GB, {t["gpus"]}-GPU instance, on-demand): {cell(t["lo"])} vs {cell(t["hi"])}, about <strong>${t["gap_month"]:,} per GPU per month</strong> apart.</p>
  <p>Rows are grouped only when model, form factor, memory and GPUs per instance all match, and only pay-as-you-go (on-demand, non-interruptible) rates are compared; reserved, spot and marketplace rates are left out. Prices are per GPU-hour from each vendor's own page and exclude storage, egress and taxes; a month is {hours} hours (the feed's <code>hours_per_month</code>), running around the clock. Groups need at least three vendors. Computed from the <a href="{base}/api/v1/gpu-prices.json">GPU price feed</a> as of {e(doc.get("feed_updated_at", ""))}, so it moves when prices move. "Lowest" means lowest among tracked providers, not the whole market.</p>
  <table><thead><tr><th>Same setup</th><th>Vendors</th><th>Lowest</th><th>Highest</th><th>Gap</th></tr></thead><tbody>{trs}</tbody></table>
"""


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

{_demo_html(base)}
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
  <p>Report a wrong price: <a href="{base}/report-price/">/report-price/</a> (or the <a href="{repo}/issues/new?template=wrong-price.yml" rel="noopener">GitHub issue form</a>; agents see <a href="{repo}/blob/main/docs/REPORT-WRONG-PRICE.md" rel="noopener">docs/REPORT-WRONG-PRICE.md</a>).</p>

  <p class="meta">More: <a href="{base}/for-agents/">For agents</a> (feed schema) · <a href="{base}/install/">Install the MCP server</a> · <a href="{base}/embed/">Embed a price badge</a> · <a href="{repo}">Source code</a></p>
"""
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell("Methodology: how Lantern Works collects, verifies and holds prices",
                                "Where Lantern Works prices come from, how they are checked daily, when they are held, why reserved rates are not ranked cheapest, and the license (CC BY 4.0 data, MIT code).",
                                f"{base}/{PATH}/", body), encoding="utf-8")
    return PATH
