"""SEO landing pages for GPU rental prices, generated only from verified rates in core/gpu.py.

/gpu/cheapest-<model>-rental/ exists only for models with >= MIN_OFFERS verified offers from
>= MIN_VENDORS vendors; everything else is covered on /gpu/price-comparison/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core.gpu import HOURS_PER_MONTH, MIN_OFFERS, MIN_VENDORS, build_rates, estimate, families  # noqa: E402

CALC = "tools/gpu-cost-calculator"
DEFAULT_HOURS = 100


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _rate_str(r: dict) -> str:
    return f"${r['price_usd']:g}/hr" if r["unit"] == "hour" else f"${r['price_usd']:,.2f}/mo"


def _table(gen, rows: list[dict], full: dict[tuple, float]) -> str:
    esc = gen.esc
    trs = []
    for i, r in enumerate(rows, 1):
        trs.append(
            f"<tr><td>{i}</td><td>{esc(r['gpu'])}{(' ' + str(r['vram_gb']) + ' GB') if r.get('vram_gb') else ''}</td>"
            f"<td><a href=\"{gen.BASE}/deals/{gen.slug_for(r['deal_id'])}/\">{esc(r['advertiser'])}</a></td>"
            f"<td>{esc(r['tier'])}</td><td>{esc(_rate_str(r))}</td>"
            f"<td><strong>{_money(r['monthly_cost_usd'])}</strong></td><td>{_money(full[(r['deal_id'], r['gpu'], r['tier'])])}</td>"
            f"<td><a href=\"{esc(r['source_url'] or '')}\" rel=\"noopener\">“{esc(r['basis'])}”</a></td>"
            f"<td>{esc((r['verified_at'] or '')[:10])}</td><td>{'referral' if r['affiliate'] else 'public'}</td></tr>")
    return ("<div style=\"overflow-x:auto\"><table class=\"howto\"><thead><tr><th>#</th><th>GPU</th><th>Vendor</th><th>Type</th>"
            f"<th>Rate</th><th>{DEFAULT_HOURS} h/month</th><th>Full month ({HOURS_PER_MONTH} h)</th><th>Vendor quote</th>"
            "<th>Verified</th><th>Label</th></tr></thead><tbody>\n" + "\n".join(trs) + "\n</tbody></table></div>")


def _jsonld(page_url: str, name: str, rows: list[dict], faqs: list[tuple[str, str]], gen) -> str:
    items = [{"@type": "ListItem", "position": i, "name": f"{r['advertiser']} {r['gpu']} ({r['tier']}) {_rate_str(r)}",
              "url": f"{gen.BASE}/deals/{gen.slug_for(r['deal_id'])}/"} for i, r in enumerate(rows, 1)]
    graph = [{"@type": "ItemList", "name": name, "url": page_url, "itemListOrder": "https://schema.org/ItemListOrderAscending",
              "numberOfItems": len(items), "itemListElement": items},
             {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q,
                                                   "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs]}]
    data = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{data}</script>'


def _faq_html(gen, faqs) -> str:
    return "\n".join(f"<h3>{gen.esc(q)}</h3>\n<p>{gen.esc(a)}</p>" for q, a in faqs)


def _full_map(rates):
    return {(r["deal_id"], r["gpu"], r["tier"]): r["monthly_cost_usd"] for r in estimate(rates, HOURS_PER_MONTH)}


def _freshness(rows) -> str:
    return max((r["verified_at"] or "")[:10] for r in rows)


def write_model_page(gen, slug: str, fam: dict, all_rates: list[dict]) -> str:
    name = fam["name"]
    rows = estimate(fam["rates"], DEFAULT_HOURS)
    full = _full_map(fam["rates"])
    hourly = sorted((r for r in rows if r["unit"] == "hour"), key=lambda r: r["price_usd"])
    by_full = sorted(rows, key=lambda r: full[(r["deal_id"], r["gpu"], r["tier"])])
    fresh = _freshness(rows)
    path = f"gpu/cheapest-{slug}-rental"
    url = f"{gen.BASE}/{path}/"
    calc = f"{gen.BASE}/{CALC}/?" + urlencode({"hours": DEFAULT_HOURS, "gpus": 1, "gpu": name})
    cheapest = rows[0]
    title = f"Cheapest {name} rental: {len(rows)} verified prices compared ({fresh})"
    desc = (f"{name} cloud rental from {_rate_str(hourly[0]) if hourly else _rate_str(cheapest)}: {len(rows)} verified offers from "
            f"{', '.join(fam['vendors'])}, sorted by monthly cost, with vendor quotes and dates.")
    faqs = []
    if hourly:
        h = hourly[0]
        faqs.append((f"What is the cheapest {name} per hour?",
                     f"{h['advertiser']} {h['gpu']} ({h['tier']}) at {_rate_str(h)}, per the vendor's pricing page checked {h['verified_at'][:10]}. "
                     f"That's {_money(h['price_usd'] * DEFAULT_HOURS)} for {DEFAULT_HOURS} GPU hours."))
    f0 = by_full[0]
    faqs.append((f"What does a full month of {name} cost?",
                 f"Running one GPU all month ({HOURS_PER_MONTH} h), the lowest verified option is {f0['advertiser']} {f0['gpu']} "
                 f"({f0['tier']}) at about {_money(full[(f0['deal_id'], f0['gpu'], f0['tier'])])}."))
    if any(r["tier"] == "Community Cloud" for r in rows):
        faqs.append(("What is the difference between RunPod Community Cloud and Secure Cloud?",
                     "Both are per-hour pods. Community Cloud runs on vetted third-party hosts and is cheaper; Secure Cloud runs in "
                     "RunPod's partner data centers. Pick Secure Cloud for sensitive data or stricter uptime needs."))
    if any(r["unit"] == "month" for r in rows):
        faqs.append(("Why are dedicated servers listed with a flat price?",
                     "Dedicated GPU servers bill a fixed monthly price whatever your usage, so they only pay off when the GPU runs most of the month."))
    faqs.append(("What isn't included in these prices?",
                 "Storage, data egress, extra vCPU/RAM and taxes. Prices are list or 'from' prices; confirm on the vendor page before you rent."))
    faqs.append(("How are these prices verified?",
                 "Each row quotes the vendor's own pricing page and shows the date it was checked. Offers without a verified price aren't listed, "
                 "and referral links don't change the order."))
    body = f"""  <nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › <a href="{gen.BASE}/gpu/price-comparison/">GPU prices</a> › {gen.esc(name)}</nav>
  <h1>Cheapest {gen.esc(name)} rental: verified prices compared</h1>
  <p class="meta">Prices verified through {fresh} · {len(rows)} offers from {len(fam['vendors'])} vendors · sorted by cost for {DEFAULT_HOURS} GPU hours/month</p>
  <p>Cheapest for {DEFAULT_HOURS} hours a month: <strong>{gen.esc(cheapest['advertiser'])} {gen.esc(cheapest['gpu'])} ({gen.esc(cheapest['tier'])})</strong> at {_money(cheapest['monthly_cost_usd'])}. <a href="{calc}">Change hours or GPU count in the calculator</a>.</p>
{_table(gen, rows, full)}
  <p>Basis: hourly rate × hours; dedicated servers are a flat monthly price. One GPU. Excludes storage, egress and tax.</p>
  <h2>FAQ</h2>
{_faq_html(gen, faqs)}
  <h2>More</h2>
  <ul><li><a href="{gen.BASE}/gpu/price-comparison/">All verified GPU rental prices</a></li><li><a href="{calc}">GPU cost calculator ({gen.esc(name)} prefilled)</a></li><li><a href="{gen.BASE}/categories/gpu-compute/">GPU &amp; compute deals</a></li><li><a href="{gen.BASE}/compare/cheap-gpu-rental/">Cheap GPU rental comparison</a></li><li><a href="{gen.BASE}/api/v1/gpu-prices.json">gpu-prices.json</a> for agents</li></ul>
  {_jsonld(url, title, rows, faqs, gen)}
"""
    out = ROOT / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell(title, desc, url, body), encoding="utf-8")
    return path


def write_overview(gen, rates: list[dict], fams: dict, pages: dict[str, str]) -> str:
    path = "gpu/price-comparison"
    url = f"{gen.BASE}/{path}/"
    rows = sorted(estimate(rates, DEFAULT_HOURS), key=lambda r: (r["hourly_equiv_usd"], r["advertiser"]))
    full = _full_map(rates)
    fresh = _freshness(rows)
    vendors = sorted({r["advertiser"] for r in rates})
    summary = []
    for slug, f in fams.items():
        if not f["rates"]:
            continue
        lo = min(f["rates"], key=lambda r: r["hourly_equiv_usd"])
        link = f'<a href="{gen.BASE}/{pages[slug]}/">{gen.esc(f["name"])}</a>' if slug in pages else gen.esc(f["name"])
        note = "" if f["page"] else " <em>(few verified offers)</em>"
        summary.append(f"<tr><td>{link}{note}</td><td>{len(f['rates'])}</td><td>{gen.esc(', '.join(f['vendors']))}</td>"
                       f"<td>{gen.esc(lo['advertiser'])} {gen.esc(_rate_str(lo))}</td></tr>")
    title = f"GPU rental price comparison: {len(rates)} verified rates (H100, A100, RTX 4090) — {fresh}"
    desc = f"Compare verified cloud GPU rental prices from {', '.join(vendors)}: per-hour and monthly, sorted by cost, with vendor quotes and dates."
    faqs = [
        ("Which GPU rental is cheapest per hour?",
         f"Among verified offers, {rows[0]['advertiser']} {rows[0]['gpu']} ({rows[0]['tier']}) at {_rate_str(rows[0])}. The cheapest GPU isn't always cheapest per job; compare VRAM and speed for your model."),
        ("How often are prices checked?", f"Each rate shows the date it was verified against the vendor's pricing page. The newest check on this page is {fresh}."),
        ("Why is my provider missing?", "Only offers with a price we could verify on the vendor's own page are listed. Marketplace providers with live, per-host prices (such as Vast.ai) aren't given a fixed rate."),
        ("Do referral links affect the ranking?", "No. Order is by estimated cost only; referral links are labelled."),
    ]
    body = f"""  <nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › <a href="{gen.BASE}/categories/gpu-compute/">GPU &amp; compute</a> › GPU price comparison</nav>
  <h1>GPU rental price comparison</h1>
  <p class="meta">Prices verified through {fresh} · {len(rates)} rates from {len(vendors)} vendors · sorted by effective hourly cost</p>
  <p>Verified per-hour and monthly prices for cloud GPUs, from each vendor's own pricing page. Use the <a href="{gen.BASE}/{CALC}/">GPU cost calculator</a> to price your exact hours.</p>
  <h2>By GPU model</h2>
  <table class="howto"><thead><tr><th>Model</th><th>Verified offers</th><th>Vendors</th><th>Lowest rate</th></tr></thead><tbody>
{chr(10).join(summary)}
  </tbody></table>
  <p>Models get their own page once they have at least {MIN_OFFERS} verified offers from {MIN_VENDORS} vendors.</p>
  <h2>All verified rates</h2>
{_table(gen, rows, full)}
  <h2>FAQ</h2>
{_faq_html(gen, faqs)}
  {_jsonld(url, title, rows, faqs, gen)}
"""
    out = ROOT / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell(title, desc, url, body), encoding="utf-8")
    return path


def write_all(gen, deals: list[dict]) -> list[str]:
    rates = build_rates(deals)["rates"]
    fams = families(rates)
    pages = {slug: write_model_page(gen, slug, f, rates) for slug, f in fams.items() if f["page"]}
    return [write_overview(gen, rates, fams, pages)] + list(pages.values())
