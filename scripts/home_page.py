"""Homepage: GPU price comparison for agents, checked daily. Everything numeric is computed from the feed
(core.gpu.build_rates over deals.json + data/gpu_pricing/), and a small script refreshes the spread from
/api/v1/gpu-prices.json in the browser. The deals directory lives at /deals/ (old /?q=… and /#cat-… links
are forwarded there)."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERO = "GPU price comparison for agents, checked daily"
SPREAD = (("h100", "H100"), ("a100", "A100"), ("rtx-4090", "RTX 4090"))
INSTALL_UVX = "uvx lantern-works-deals-mcp"
INSTALL_PIP = "pip install lantern-works-deals-mcp"


def spread(rates: list[dict]) -> list[dict]:
    sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
    from core.gpu import family_of
    out = []
    for slug, name in SPREAD:
        rs = sorted((r for r in rates if family_of(r["gpu"]) == slug and r.get("hourly_equiv_usd") is not None),
                    key=lambda r: (r["hourly_equiv_usd"], r["advertiser"], r["gpu"]))
        if not rs:
            continue
        vals = [r["hourly_equiv_usd"] for r in rs]
        lo = rs[0]
        out.append({"slug": slug, "name": name, "n": len(rs), "vendors": len({r["advertiser"] for r in rs}),
                    "min": vals[0], "median": statistics.median(vals), "max": vals[-1],
                    "cheapest_vendor": lo["advertiser"], "cheapest_gpu": lo["gpu"], "cheapest_tier": lo.get("tier"),
                    "checked": (lo.get("verified_at") or lo.get("checked_at") or "")[:10], "source_url": lo.get("source_url")})
    return out


JS = r"""  <script>
  (function(){
  const FAM={"h100":"H100","a100":"A100","rtx-4090":"RTX 4090"};
  function fam(g){for(const k in FAM){const n=FAM[k];if(g===n||g.startsWith(n+" "))return k}return null}
  const m=v=>"$"+v.toFixed(2);
  fetch("/api/v1/gpu-prices.json",{cache:"no-cache"}).then(r=>r.ok?r.json():null).then(d=>{
    if(!d||!Array.isArray(d.rates))return;
    const c=document.querySelectorAll("[data-live-count]");c.forEach(e=>e.textContent=d.rates.length);
    for(const k in FAM){
      const rs=d.rates.filter(r=>fam(r.gpu)===k&&r.hourly_equiv_usd!=null).sort((a,b)=>a.hourly_equiv_usd-b.hourly_equiv_usd);
      const row=document.querySelector(`tr[data-fam="${k}"]`);if(!row||!rs.length)continue;
      const v=rs.map(r=>r.hourly_equiv_usd),mid=v.length%2?v[(v.length-1)/2]:(v[v.length/2-1]+v[v.length/2])/2;
      row.querySelector(".lo").textContent=m(v[0]);row.querySelector(".med").textContent=m(mid);row.querySelector(".hi").textContent=m(v[v.length-1]);
      row.querySelector(".n").textContent=v.length;row.querySelector(".who").textContent=rs[0].advertiser+" ("+rs[0].gpu+", "+(rs[0].tier||"")+")";
    }
  }).catch(()=>{});
  })();
  </script>
"""

REDIRECT_JS = r"""  <script>
  // Old homepage deal-directory links (/?q=…, /?cat=…, /#cat-…) now live at /deals/.
  (function(){const s=location.search,h=location.hash;if(/[?&](q|cat|offer|max|free|verified)=/.test(s)||/^#cat-/.test(h))location.replace("/deals/"+s+h)})();
  </script>
"""


def write(gen, deals: list[dict], feed_updated: str) -> Path:
    sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None
    from core.gpu import build_rates
    from core.gpu_changes import build_changes, change_title
    esc, BASE = gen.esc, gen.BASE
    rates = build_rates(deals)["rates"]
    count = gen.live_rate_count()
    vendors = len({r["advertiser"] for r in rates})
    fresh = max(((r.get("verified_at") or "")[:10] for r in rates), default="")
    rows = "".join(
        f'<tr data-fam="{s["slug"]}"><th scope="row"><a href="{BASE}/gpu/cheapest-{s["slug"]}-rental/">{esc(s["name"])}</a></th>'
        f'<td class="lo"><strong>${s["min"]:.2f}</strong></td><td class="med">${s["median"]:.2f}</td><td class="hi">${s["max"]:.2f}</td>'
        f'<td class="n">{s["n"]}</td><td class="who">{esc(s["cheapest_vendor"])} ({esc(s["cheapest_gpu"])}, {esc(s["cheapest_tier"] or "")})</td></tr>'
        for s in spread(rates))
    ch = build_changes()
    moved = [c for c in ch["changes"] if c["change"] in ("down", "up")][:5]
    moved_html = ("<ul>" + "".join(f'<li><a href="{esc(c["source_url"] or BASE + "/gpu/")}" rel="noopener">{esc(change_title(c))}</a></li>' for c in moved) + "</ul>") if moved else "<p>No tracked rate moved between the last two daily snapshots.</p>"
    counts = ch["counts"]
    title = f"{HERO} | Lantern Works"
    desc = (f"Cheapest H100, A100 and RTX 4090 rental prices among tracked providers, re-checked daily on vendor pricing pages. "
            f"{count} rates from {vendors} vendors, with quotes, dates, price history and an MCP server for agents.")
    body = f"""  <header>
    <h1>{esc(HERO)}</h1>
    <p>Hourly GPU rental prices re-read every day from each vendor's own pricing page, with the quote, source link and check date for every rate. <strong><span data-live-count>{count}</span> rates</strong> from {vendors} vendors, newest check {esc(fresh)}. "Cheapest" always means cheapest among tracked providers.</p>
    <p class="meta"><small>{__import__("gpu_pages").rate_count_note(gen, deals)}</small></p>
  </header>
  <main id="content">
  <section aria-labelledby="spread">
    <h2 id="spread">Today's spread (per GPU-hour, USD)</h2>
    <div style="overflow-x:auto"><table class="howto"><thead><tr><th>GPU</th><th>Cheapest</th><th>Median</th><th>Highest</th><th>Rates</th><th>Cheapest offer</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
    <p><a href="{BASE}/gpu/price-comparison/"><strong>Compare all GPU prices →</strong></a> · <a href="{BASE}/gpu/">GPU pages by model</a> · <a href="{BASE}/tools/gpu-cost-calculator/">cost calculator</a> · <a href="{BASE}/api/v1/gpu-prices/history.json">price history (JSON)</a></p>
  </section>
  <section aria-labelledby="install">
    <h2 id="install">Give your agent live GPU prices</h2>
    <pre>{esc(INSTALL_UVX)}</pre>
    <p>or <code>{esc(INSTALL_PIP)}</code>. Free MCP server, read-only, no API key. Lead tool: <code>compare_gpu_prices</code> (with <code>include_history</code> for price history). <a href="{BASE}/install/">Setup for Claude, Cursor, VS Code and more</a>.</p>
  </section>
  <section aria-labelledby="moved">
    <h2 id="moved">What moved since yesterday</h2>
    <p class="meta">Snapshot {esc(str(ch["previous_date"]))} → {esc(str(ch["date"]))}: {counts["down"]} down, {counts["up"]} up, {counts["new"]} newly tracked, {counts["removed"]} no longer ranked.</p>
    {moved_html}
    <p><a href="{BASE}/api/v1/gpu-price-changes.json">Price changes (JSON)</a> · <a href="{BASE}/api/v1/gpu-price-changes.xml">RSS</a> · <a href="{BASE}/api/v1/gpu-prices.json">all rates (JSON)</a></p>
  </section>
  <section aria-labelledby="more">
    <h2 id="more">Also on Lantern Works</h2>
    <p><a href="{BASE}/deals/">Agent work-stack deals</a>: compute, scraping and unblock, search APIs, email, hosting. <a href="{BASE}/tools/stack-optimizer/">Stack optimizer</a> · <a href="{BASE}/for-agents/">For agents</a> (JSON feed, schema).</p>
  </section>
  </main>
"""
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name='impact-site-verification' value='594aa2cb-9310-430a-8577-b47b45c91f8f'>
  <meta name="impact-site-verification" content="594aa2cb-9310-430a-8577-b47b45c91f8f" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}" />
  <meta name="robots" content="index,follow" />
  <link rel="canonical" href="{BASE}/" />
  <link rel="alternate" type="application/rss+xml" title="GPU price changes" href="{BASE}/api/v1/gpu-price-changes.xml" />
{gen.social_meta(title, desc, f"{BASE}/")}
  <script type="application/ld+json">
{gen.homepage_json_ld(deals, home=True)}
  </script>
  <style>{gen.CSS}</style>
{REDIRECT_JS}</head>
<body>
{gen.site_ui.nav_html(BASE, BASE + "/")}{body}
{JS}  <footer><p>Prices are re-checked daily; confirm on the vendor page before you rent. Some result links are referral links (marked); that never changes ranking or your price.</p>
    <p><strong>Lantern Works</strong> · <a href="{BASE}/gpu/">GPU prices</a> · <a href="{BASE}/deals/">Deals</a> · <a href="{BASE}/lanternworks/">About</a> · <a href="{BASE}/changelog/">Changelog</a> · Contact <a href="mailto:lanternworks@agentmail.to">lanternworks@agentmail.to</a></p>
  </footer>
{gen.analytics_snippet()}</body>
</html>
"""
    path = ROOT / "index.html"
    path.write_text(html_doc, encoding="utf-8")
    return path
