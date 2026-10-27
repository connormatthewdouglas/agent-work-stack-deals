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
from core.gpu import HOURS_PER_MONTH, MIN_OFFERS, MIN_VENDORS, SERVERLESS, build_rates, estimate, families  # noqa: E402

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
    if any(r["tier"] == SERVERLESS for r in rows):
        faqs.append(("How does Modal's per-second price compare with an hourly pod?",
                     "Modal bills GPU time per second only while your function runs, so idle time costs nothing. Its listed rates are for "
                     "preemptible functions; non-preemptible execution is 3x and choosing a region adds 1.15-1.75x (per modal.com/pricing). "
                     "The hourly figure shown is the per-second rate x 3600."))
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
  <ul><li><a href="{calc}">GPU cost calculator ({gen.esc(name)} prefilled)</a></li>{_more_links(gen, exclude=path)}<li><a href="{gen.BASE}/compare/cheap-gpu-rental/">Cheap GPU rental comparison</a></li><li><a href="{gen.BASE}/api/v1/gpu-prices.json">gpu-prices.json</a> for agents</li></ul>
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
    title = f"GPU rental price comparison: {len(rates)} verified rates (H100, H200, A100, L40S, RTX 4090) — {fresh}"
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
  <p>Comparisons: {" · ".join(f'<a href="{gen.BASE}/{p}/">{n}</a>' for p, n in _LINKS)}</p>
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


# ---------- original comparisons, built only from rates verified on the latest check date ----------

def _key(r):
    return (r["deal_id"], r["gpu"], r["tier"])


def _today_rates(rates):
    day = max((r["verified_at"] or "")[:10] for r in rates)
    return day, [r for r in rates if (r["verified_at"] or "")[:10] == day and r["unit"] == "hour"]


def _cmp_page(gen, path, title, desc, h1, crumb, intro, sections, rows_ld, faqs, day):
    url = f"{gen.BASE}/{path}/"
    body = f"""  <nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › <a href="{gen.BASE}/gpu/price-comparison/">GPU prices</a> › {gen.esc(crumb)}</nav>
  <h1>{gen.esc(h1)}</h1>
  <p class="meta">Checked on {day} against each vendor's public pricing page · sorted by cost · referral status never affects order</p>
  <p>{intro}</p>
{sections}
  <h2>FAQ</h2>
{_faq_html(gen, faqs)}
  <h2>More</h2>
  <ul>{_more_links(gen, exclude=path)}</ul>
  {_jsonld(url, title, rows_ld, faqs, gen)}
"""
    out = ROOT / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell(title, desc, url, body), encoding="utf-8")
    return path


def _simple_table(head, rows):
    return ("<div style=\"overflow-x:auto\"><table class=\"howto\"><thead><tr>" + "".join(f"<th>{h}</th>" for h in head)
            + "</tr></thead><tbody>\n" + "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
            + "\n</tbody></table></div>")


def _vendor_cell(gen, r):
    return f"<a href=\"{gen.BASE}/deals/{gen.slug_for(r['deal_id'])}/\">{gen.esc(r['advertiser'])}</a>"


def _quote_cell(gen, r):
    return f"<a href=\"{gen.esc(r['source_url'] or '')}\" rel=\"noopener\">“{gen.esc(r['basis'])}”</a>"


H100_VS = "compare/runpod-vs-thunder-compute-vs-modal-h100"
PER_VRAM = "compare/cheapest-gpu-per-gb-vram"
RUNPOD_TIERS = "compare/runpod-community-vs-secure-cloud-prices"
_VS_VENDORS = ("RunPod", "Thunder Compute", "Modal")
_VENDOR_FACTS = {  # billing facts read from the same pricing pages on the check date
    "RunPod": "Pods billed per hour (per-second view available); storage extra, network volumes from $0.05/GB/mo.",
    "Thunder Compute": "Instances billed per minute while running; first 100 GB disk per GPU included; no egress fees.",
    "Modal": "Serverless, billed per second while running; listed rates are preemptible (non-preemptible 3x); $30/month free compute on Starter.",
}


def write_h100_vs(gen, rates):
    day, rs = _today_rates(rates)
    rows = estimate([r for r in rs if r["gpu"].startswith("H100") and r["advertiser"] in _VS_VENDORS], DEFAULT_HOURS)
    full = _full_map(rows)
    best = {}
    for r in rows:
        best.setdefault(r["advertiser"], r)
    t1 = _simple_table(["#", "Vendor", "H100 option", "Rate", f"{DEFAULT_HOURS} h/month", f"Full month ({HOURS_PER_MONTH} h)", "Vendor quote"],
                       [[i, _vendor_cell(gen, r), f"{gen.esc(r['gpu'])} · {gen.esc(r['tier'])}", gen.esc(_rate_str(r)),
                         f"<strong>{_money(r['monthly_cost_usd'])}</strong>", _money(full[_key(r)]), _quote_cell(gen, r)]
                        for i, r in enumerate(rows, 1)])
    t2 = _simple_table(["Vendor", "Cheapest H100", "Billing and extras"],
                       [[_vendor_cell(gen, r), f"{gen.esc(r['gpu'])} ({gen.esc(r['tier'])}) {gen.esc(_rate_str(r))}", gen.esc(_VENDOR_FACTS[v])]
                        for v, r in best.items()])
    c = rows[0]
    secure = [r for r in rows if r["tier"] != "Community Cloud"]
    faqs = [(f"Which is cheapest for an H100: RunPod, Thunder Compute or Modal?",
             f"On {day}, the lowest listed H100 rate of the three was {c['advertiser']} {c['gpu']} ({c['tier']}) at {_rate_str(c)}, "
             f"or {_money(c['monthly_cost_usd'])} for {DEFAULT_HOURS} GPU hours."),
            ("What is the cheapest H100 outside a community marketplace?",
             f"{secure[0]['advertiser']} {secure[0]['gpu']} ({secure[0]['tier']}) at {_rate_str(secure[0])}." if secure else "None listed."),
            ("When is Modal cheaper than an hourly H100?",
             "When your GPU sits idle a lot. Modal charges per second only while code runs, so a spiky inference workload can cost less "
             "even at a higher listed rate. For a GPU busy most of the hour, the lower hourly rate wins."),
            ("What isn't included?", "Storage, extra CPU/RAM, egress and taxes. Confirm on each vendor page before you rent.")]
    return _cmp_page(gen, H100_VS, f"RunPod vs Thunder Compute vs Modal for H100: prices checked {day}",
                     f"H100 rental prices on RunPod, Thunder Compute and Modal, checked {day} on each vendor's pricing page, with monthly costs and billing differences.",
                     "RunPod vs Thunder Compute vs Modal for H100", "RunPod vs Thunder Compute vs Modal (H100)",
                     f"Every H100 option these three vendors list publicly, priced for {DEFAULT_HOURS} GPU hours and a full month. Cheapest first.",
                     f"{t1}\n  <h2>How they bill</h2>\n{t2}", rows, faqs, day)


def write_per_vram(gen, rates):
    day, rs = _today_rates(rates)
    rows = sorted((r for r in rs if r.get("vram_gb")), key=lambda r: (r["price_usd"] / r["vram_gb"], r["advertiser"], r["gpu"]))
    t = _simple_table(["#", "GPU", "Vendor", "Type", "Rate", "$ per GB VRAM-hour", "Vendor quote"],
                      [[i, f"{gen.esc(r['gpu'])} {r['vram_gb']} GB", _vendor_cell(gen, r), gen.esc(r["tier"]), gen.esc(_rate_str(r)),
                        f"<strong>${r['price_usd'] / r['vram_gb']:.4f}</strong>", _quote_cell(gen, r)] for i, r in enumerate(rows, 1)])
    c = rows[0]
    big = [r for r in rows if r["vram_gb"] >= 80]
    faqs = [("Which cloud GPU is cheapest per GB of VRAM?",
             f"On {day}: {c['advertiser']} {c['gpu']} {c['vram_gb']} GB ({c['tier']}) at ${c['price_usd'] / c['vram_gb']:.4f} per GB-hour ({_rate_str(c)})."),
            ("Which 80 GB+ GPU is cheapest per GB?",
             f"{big[0]['advertiser']} {big[0]['gpu']} {big[0]['vram_gb']} GB ({big[0]['tier']}) at ${big[0]['price_usd'] / big[0]['vram_gb']:.4f} per GB-hour." if big else "None listed."),
            ("Why rank by VRAM?", "Model size usually decides which GPU you can use at all. Price per GB of VRAM shows the cheapest way to fit a "
             "model in memory; it ignores speed, so a faster GPU can still finish a job for less."),
            ("Which rates are included?", f"Only hourly rates checked on {day} on the vendor's own pricing page. Monthly dedicated servers are excluded.")]
    return _cmp_page(gen, PER_VRAM, f"Cheapest cloud GPU per GB of VRAM: {len(rows)} rates checked {day}",
                     f"Cloud GPU rental ranked by price per GB of VRAM per hour, from {len(rows)} hourly rates checked {day} on vendor pricing pages.",
                     "Cheapest cloud GPU per GB of VRAM", "Price per GB of VRAM",
                     "Hourly rate divided by GPU memory. Useful when you need a model to fit and are deciding which card to rent.",
                     t, rows, faqs, day)


def write_runpod_tiers(gen, rates):
    day, rs = _today_rates(rates)
    rp = [r for r in rs if r["advertiser"] == "RunPod"]
    sec = {r["gpu"]: r for r in rp if r["tier"] == "Secure Cloud"}
    pairs = sorted(((sec[r["gpu"]], r) for r in rp if r["tier"] == "Community Cloud" and r["gpu"] in sec),
                   key=lambda p: -(1 - p[1]["price_usd"] / p[0]["price_usd"]))
    t = _simple_table(["GPU", "Secure Cloud", "Community Cloud", "Saving", f"Saving over {HOURS_PER_MONTH} h"],
                      [[f"{gen.esc(s['gpu'])} {s['vram_gb']} GB", gen.esc(_rate_str(s)), gen.esc(_rate_str(c)),
                        f"<strong>{(1 - c['price_usd'] / s['price_usd']) * 100:.0f}%</strong>", _money((s['price_usd'] - c['price_usd']) * HOURS_PER_MONTH)]
                       for s, c in pairs])
    top, low = pairs[0], pairs[-1]
    rows_ld = [p[1] for p in pairs]
    faqs = [("How much cheaper is RunPod Community Cloud?",
             f"On {day}, between {(1 - low[1]['price_usd'] / low[0]['price_usd']) * 100:.0f}% and {(1 - top[1]['price_usd'] / top[0]['price_usd']) * 100:.0f}% "
             f"below Secure Cloud for the same GPU. The biggest gap was the {top[0]['gpu']}."),
            ("What is the difference between Community Cloud and Secure Cloud?",
             "Community Cloud runs on vetted third-party hosts; Secure Cloud runs in RunPod's partner data centers. Use Secure Cloud for sensitive data or stricter uptime needs."),
            ("Where do these prices come from?", f"runpod.io/pricing, checked {day}. Both tiers are per-hour on-demand pod rates.")]
    return _cmp_page(gen, RUNPOD_TIERS, f"RunPod Community Cloud vs Secure Cloud prices: {len(pairs)} GPUs compared ({day})",
                     f"How much RunPod Community Cloud saves over Secure Cloud per GPU, from runpod.io/pricing checked {day}.",
                     "RunPod Community Cloud vs Secure Cloud prices", "RunPod Community vs Secure",
                     "Same GPU, two RunPod tiers. Sorted by the size of the Community Cloud discount.",
                     t, rows_ld, faqs, day)


_LINKS: list[tuple[str, str]] = []


def _more_links(gen, exclude=None):
    items = [(f"{gen.BASE}/gpu/price-comparison/", "All verified GPU rental prices")] + [(f"{gen.BASE}/{p}/", n) for p, n in _LINKS if p != exclude]
    items += [(f"{gen.BASE}/{CALC}/", "GPU cost calculator"), (f"{gen.BASE}/categories/gpu-compute/", "GPU &amp; compute deals")]
    return "".join(f'<li><a href="{u}">{n}</a></li>' for u, n in items)


def page_links(deals: list[dict]) -> list[tuple[str, str]]:
    """(path, label) for every GPU landing page and comparison, for hubs and nav."""
    fams = families(build_rates(deals)["rates"])
    out = [(f"gpu/cheapest-{slug}-rental", f"cheapest {f['name']}") for slug, f in fams.items() if f["page"]]
    return out + [(H100_VS, "RunPod vs Thunder Compute vs Modal (H100)"), (PER_VRAM, "GPU price per GB of VRAM"),
                  (RUNPOD_TIERS, "RunPod Community vs Secure Cloud")]


def links_html(base: str, deals: list[dict]) -> str:
    return " · ".join(f'<a href="{base}/{p}/">{n}</a>' for p, n in page_links(deals))


def write_all(gen, deals: list[dict]) -> list[str]:
    rates = build_rates(deals)["rates"]
    fams = families(rates)
    _LINKS[:] = page_links(deals)
    pages = {slug: write_model_page(gen, slug, f, rates) for slug, f in fams.items() if f["page"]}
    cmps = [write_h100_vs(gen, rates), write_per_vram(gen, rates), write_runpod_tiers(gen, rates)]
    return [write_overview(gen, rates, fams, pages)] + list(pages.values()) + cmps
