"""SEO landing pages for GPU rental prices, generated only from verified rates in core/gpu.py.

/gpu/cheapest-<model>-rental/ exists only for models with >= MIN_OFFERS verified offers from
>= MIN_VENDORS vendors; everything else is covered on /gpu/price-comparison/.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core.gpu import load_vendor_files, HOURS_PER_MONTH, MIN_OFFERS, MIN_VENDORS, SERVERLESS, build_rates, estimate, families, family_of  # noqa: E402
from install_page import link_snippet as install_link_snippet

CALC = "tools/gpu-cost-calculator"
DEFAULT_HOURS = 100


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _vendor_url(gen, r: dict) -> str:
    return f"{gen.BASE}/deals/{gen.slug_for(r['deal_id'])}/" if r.get("deal_id") else (r.get("source_url") or "")


def _vendor_link(gen, r: dict) -> str:
    rel = "" if r.get("deal_id") else ' rel="noopener"'
    return f"<a href=\"{gen.esc(_vendor_url(gen, r))}\"{rel}>{gen.esc(r['advertiser'])}</a>"


def _rate_str(r: dict) -> str:
    if r["unit"] == "hour":
        s = f"${r['price_usd']:g}/hr"
        if r.get("price_status") == "marketplace":
            s += f" (variable marketplace median; lowest offer ${r['lowest_offer_usd']:g}/hr, {r['offer_count']} offers)"
        if (r.get("min_gpus") or 1) > 1:
            s += f" (sold only as {r['min_gpus']}-GPU instances)"
        return s
    if (r.get("gpu_count") or 1) > 1:
        return f"${r['price_usd']:,.2f}/GPU-mo ({r['gpu_count']}-GPU server ${r['server_price_usd']:,.2f}/mo)"
    return f"${r['price_usd']:,.2f}/mo"


def _avail_cell(gen, r: dict) -> str:
    a = r.get("availability") or {}
    if a.get("in_stock") is None:
        return "unknown"
    bits = [a["status"]]
    if a.get("stock_level"):
        bits.append(f"stock {a['stock_level']}")
    if a.get("offer_count") is not None:
        bits.append(f"{a['offer_count']} offers")
    if a.get("available_regions"):
        bits.append("regions " + "/".join(a["available_regions"][:6]) + ("…" if len(a["available_regions"]) > 6 else ""))
    if a.get("source_label"):
        bits.append(a["source_label"])
    t = (a.get("checked_at") or "").replace("T", " ")[:16]
    sep = " (separate later check)" if r.get("advertiser") == "Vast.ai" else ""
    return gen.esc(", ".join(bits) + (f", snapshot {t} UTC" if t else "") + sep)


def _verified_cell(r: dict, esc) -> str:
    if r.get("price_check") == "manual snapshot":
        return esc(f"manual snapshot {r['snapshot_at'][:16].replace('T', ' ')} UTC; held after {r['hold_after'][:10]} unless re-checked")
    return esc(f"{(r['verified_at'] or '')[:10]} (daily)")


def _pick_cheapest(rs: list[dict]) -> dict:
    """Headline cheapest per model: pay-as-you-go only, like compare_gpu_prices (reserved/commitment rows never win)."""
    payg = [r for r in rs if r.get("tier_class") != "reserved"] or rs
    return min(payg, key=lambda r: (r["hourly_equiv_usd"], r["advertiser"]))


def _table(gen, rows: list[dict], full: dict[tuple, float]) -> str:
    """H5: reserved/term-commitment rows get their own section, sorted by effective hourly rate with the term shown."""
    payg = [r for r in rows if r.get("tier_class") != "reserved"]
    res = sorted((r for r in rows if r.get("tier_class") == "reserved"), key=lambda r: (r["hourly_equiv_usd"], r["advertiser"], r["gpu"]))
    out = _table_one(gen, payg, full) if payg else ""
    if res:
        out += ("\n<h3 id=\"reserved-rates\">Reserved and term-commitment prices</h3>\n<p class=\"meta\">These need a reservation or minimum term "
                "(shown in the Type column), so they are kept out of the list above and are not ranked among pay-as-you-go rates. "
                "Sorted by effective hourly rate.</p>\n" + _table_one(gen, res, full, show_filter=False))
    return out


def _table_one(gen, rows: list[dict], full: dict[tuple, float], show_filter: bool = True) -> str:
    esc = gen.esc
    trs = []
    for i, r in enumerate(rows, 1):
        tc = r.get("tier_class") or "on-demand"
        badge = "" if tc == "on-demand" else f" <strong>[{esc(tc)}]</strong>"
        trs.append(
            f"<tr data-tier=\"{esc(tc)}\"><td data-label=\"#\">{i}</td><td data-label=\"GPU\">{esc(r['gpu'])}{(' ' + str(r['vram_gb']) + ' GB') if r.get('vram_gb') else ''}</td>"
            f"<td data-label=\"Vendor\">{_vendor_link(gen, r)}</td>"
            f"<td data-label=\"Type\">{esc(r['tier'])}{badge}</td><td data-label=\"Rate\">{esc(_rate_str(r))}</td>"
            f"<td data-label=\"{DEFAULT_HOURS} h/month\"><strong>{_money(r['monthly_cost_usd'])}</strong></td><td data-label=\"Full month\">{_money(full[_key(r)])}</td>"
            f"<td data-label=\"Vendor quote\"><a href=\"{esc(r['source_url'] or '')}\" rel=\"noopener\">“{esc(r['evidence']['quote'])}”</a></td>"
            f"<td data-label=\"Verified\">{_verified_cell(r, esc)}</td><td data-label=\"Availability\">{_avail_cell(gen, r)}</td><td data-label=\"Label\">{'referral' if r['affiliate'] else 'public'}</td></tr>")
    tid = "rt" + hashlib.sha1(repr([_key(r) for r in rows]).encode()).hexdigest()[:8]
    filt = (f"<p><label><input type=\"checkbox\" onchange=\"document.querySelectorAll('#{tid} tbody tr').forEach("
            f"function(t){{t.hidden=this.checked&&t.dataset.tier!=='on-demand'}}.bind(this))\"> On-demand only</label> "
            "(hides spot/interruptible, community-hosted, marketplace and flat monthly rates; those are labelled in the Type column)</p>")
    if not show_filter:
        filt = ""
    return (filt + f"<div class=\"tscroll rates-cards\"><table class=\"howto\" id=\"{tid}\"><thead><tr><th>#</th><th>GPU</th><th>Vendor</th><th>Type</th>"
            f"<th>Rate</th><th>{DEFAULT_HOURS} h/month</th><th title=\"hourly rate x {HOURS_PER_MONTH} h (x GPUs billed); monthly plans at their flat price\">Full month ({HOURS_PER_MONTH} h: rate × {HOURS_PER_MONTH}; flat plans as listed)</th><th>Vendor quote (verbatim)</th>"
            "<th>Price verified</th><th>Availability (manual snapshot, time shown)</th><th>Label</th></tr></thead><tbody>\n" + "\n".join(trs) + "\n</tbody></table></div>"
            "<p class=\"meta\">Availability: \u201cunknown\u201d means no availability signal from this vendor for that offer. Where a status is shown, "
            "it is a manual snapshot at the time in the row; stock changes within minutes, so it is not a guarantee. Vast.ai offer counts come from a "
            "separate, later check than the price quote, so counts and minimums can differ.</p>")


def _jsonld(page_url: str, name: str, rows: list[dict], faqs: list[tuple[str, str]], gen) -> str:
    items = [{"@type": "ListItem", "position": i, "name": f"{r['advertiser']} {r['gpu']} ({r['tier']}) {_rate_str(r)}",
              "url": _vendor_url(gen, r)} for i, r in enumerate(rows, 1)]
    graph = [{"@type": "ItemList", "name": name, "url": page_url, "itemListOrder": "https://schema.org/ItemListOrderAscending",
              "numberOfItems": len(items), "itemListElement": items},
             {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q,
                                                   "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs]}]
    data = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{data}</script>'


def _faq_html(gen, faqs) -> str:
    return "\n".join(f"<h3>{gen.esc(q)}</h3>\n<p>{gen.esc(a)}</p>" for q, a in faqs)


def _od_note(gen, rows, cheapest) -> str:
    """When the overall cheapest isn't on-demand, say so and name the cheapest on-demand rate (audit T9/M6)."""
    tc = cheapest.get("tier_class") or "on-demand"
    if tc == "on-demand":
        return " (on-demand)"
    od = next((r for r in rows if (r.get("tier_class") or "on-demand") == "on-demand"), None)
    tail = (f"; cheapest <strong>on-demand</strong> among tracked providers: {gen.esc(od['advertiser'])} {gen.esc(od['gpu'])} ({gen.esc(od['tier'])}) at "
            f"{_money(od['monthly_cost_usd'])}") if od else "; no on-demand rate is tracked for this model"
    return f" — note: that rate is <strong>{gen.esc(tc)}</strong>{tail}"


def _full_map(rates):
    """Full-month cost per row, keyed by the row's full identity. (deal_id, gpu, tier) was NOT unique: vendors without a
    deal_id (Lambda, Verda, DigitalOcean...) collided, so a row could show another row's monthly total. Per row:
    hourly rate x 730 h x GPUs billed (min_gpus when sold only as multi-GPU instances); flat monthly = monthly price."""
    out = {}
    for r in rates:
        k = _key(r)
        assert k not in out, f"duplicate GPU rate identity {k}"
        out[k] = estimate([r], HOURS_PER_MONTH)[0]["monthly_cost_usd"]
    return out


def _freshness(rows) -> str:
    return max((r["verified_at"] or "")[:10] for r in rows)


def write_model_page(gen, slug: str, fam: dict, all_rates: list[dict]) -> str:
    name = fam["name"]
    rows = estimate(fam["rates"], DEFAULT_HOURS)
    full = _full_map(fam["rates"])
    hourly = sorted((r for r in rows if r["unit"] == "hour"), key=lambda r: r["price_usd"])
    by_full = sorted(rows, key=lambda r: full[_key(r)])
    fresh = _freshness(rows)
    path = f"gpu/cheapest-{slug}-rental"
    url = f"{gen.BASE}/{path}/"
    calc = f"{gen.BASE}/{CALC}/?" + urlencode({"hours": DEFAULT_HOURS, "gpus": 1, "gpu": name})
    cheapest = rows[0]
    title = f"{name} rental, cheapest among tracked providers: {len(rows)} verified prices ({fresh})"
    desc = (f"{name} cloud rental among tracked providers from {_rate_str(hourly[0]) if hourly else _rate_str(cheapest)}: {len(rows)} verified offers from "
            f"{', '.join(fam['vendors'])}, sorted by monthly cost, with vendor quotes and dates.")
    faqs = []
    if hourly:
        h = hourly[0]
        faqs.append((f"What is the cheapest {name} per hour among tracked providers?",
                     f"{h['advertiser']} {h['gpu']} ({h['tier']}) at {_rate_str(h)}, per the vendor's pricing page checked {h['verified_at'][:10]}. "
                     f"That's {_money(h['price_usd'] * DEFAULT_HOURS)} for {DEFAULT_HOURS} GPU hours."))
    f0 = by_full[0]
    faqs.append((f"What does a full month of {name} cost?",
                 f"Running one GPU all month ({HOURS_PER_MONTH} h), the lowest verified option among tracked providers is {f0['advertiser']} {f0['gpu']} "
                 f"({f0['tier']}) at about {_money(full[_key(f0)])}."))
    if any(r["tier"] == "On-demand (Community Cloud)" for r in rows):
        faqs.append(("What is the difference between RunPod Community Cloud and Secure Cloud?",
                     "Both are per-hour pods. Community Cloud runs on vetted third-party hosts and costs less; Secure Cloud runs in "
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
  <h1>{gen.esc(name)} rental: cheapest among tracked providers</h1>
  <p class="meta">Prices verified through {fresh} · {len(rows)} offers from {len(fam['vendors'])} vendors · sorted by cost for {DEFAULT_HOURS} GPU hours/month</p>
  <p>Cheapest among tracked providers for {DEFAULT_HOURS} hours a month: <strong>{gen.esc(cheapest['advertiser'])} {gen.esc(cheapest['gpu'])} ({gen.esc(cheapest['tier'])})</strong> at {_money(cheapest['monthly_cost_usd'])}{_od_note(gen, rows, cheapest)}. <a href="{calc}">Change hours or GPU count in the calculator</a>.</p>
{_table(gen, rows, full)}
  <p>Basis: hourly rate × hours; dedicated servers are a flat monthly price. One GPU. Excludes storage, egress and tax.</p>
{accuracy_html(gen, fam['rates'])}{changes_html(gen, slug)}  <h2>FAQ</h2>
{_faq_html(gen, faqs)}
  <h2>More</h2>
  <ul><li><a href="{calc}">GPU cost calculator ({gen.esc(name)} prefilled)</a></li>{_more_links(gen, exclude=path)}<li><a href="{gen.BASE}/compare/cheap-gpu-rental/">GPU rental deals comparison</a></li><li><a href="{gen.BASE}/api/v1/gpu-prices.json">gpu-prices.json</a> for agents</li></ul>
  {_jsonld(url, title, rows, faqs, gen)}
"""
    out = ROOT / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell(title, desc, url, body + install_link_snippet(gen.BASE)), encoding="utf-8")
    return path


def rate_count_note(gen, deals: list[dict]) -> str:
    """#31: say exactly what the 'N rates from M vendors' headline counts vs the rows in gpu-prices.json."""
    from collections import Counter
    doc = build_rates(deals)
    rates = doc["rates"]
    tc = Counter(r.get("tier_class") or "on-demand" for r in rates)
    parts = ", ".join(f"{n} {k}" for k, n in sorted(tc.items(), key=lambda kv: (-kv[1], kv[0])))
    held = doc.get("held_stale") or []
    held_n = sum(len(h.get("records") or []) for h in held)
    held_v = sorted({h["vendor"] for h in held})
    unp = doc.get("unpriced") or []
    out = (f"How we count: the headline is every row in <code>rates[]</code> of <a href=\"{gen.BASE}/api/v1/gpu-prices.json\">gpu-prices.json</a> "
           f"({len(rates)} rates from {len({r['advertiser'] for r in rates})} vendors: {gen.esc(parts)}). ")
    if held_n:
        out += f"Not counted: {held_n} held_stale record{'s' if held_n != 1 else ''} from {len(held_v)} vendor{'s' if len(held_v) != 1 else ''} (stale or too thin a marketplace, never ranked)"
        out += f" and {len(unp)} unpriced vendor{'s' if len(unp) != 1 else ''} (no verifiable price). " if unp else ". "
    elif unp:
        out += f"Not counted: {len(unp)} unpriced vendor{'s' if len(unp) != 1 else ''} (no verifiable price). "
    return out + "Reserved rates are counted but kept out of the pay-as-you-go ranking."


def write_overview(gen, rates: list[dict], fams: dict, pages: dict[str, str]) -> str:
    path = "gpu/price-comparison"
    url = f"{gen.BASE}/{path}/"
    rows = sorted(estimate(rates, DEFAULT_HOURS), key=lambda r: ((r.get("tier_class") == "reserved"), r["hourly_equiv_usd"], r["advertiser"]))  # reserved after all pay-as-you-go
    full = _full_map(rates)
    fresh = _freshness(rows)
    vendors = sorted({r["advertiser"] for r in rates})
    summary = []
    for slug, f in fams.items():
        if not f["rates"]:
            continue
        lo = _pick_cheapest(f["rates"])
        link = f'<a href="{gen.BASE}/{pages[slug]}/">{gen.esc(f["name"])}</a>' if slug in pages else gen.esc(f["name"])
        note = "" if f["page"] else " <em>(few verified offers)</em>"
        summary.append(f"<tr><td>{link}{note}</td><td>{len(f['rates'])}</td><td>{gen.esc(', '.join(f['vendors']))}</td>"
                       f"<td>{gen.esc(lo['advertiser'])} {gen.esc(_rate_str(lo))}</td></tr>")
    # Every ranked rate is counted exactly once in the model table (audit T6/M3): families first, then each other model.
    others = {}
    for r in rates:
        if family_of(r["gpu"]) is None:
            others.setdefault(r["gpu"], []).append(r)
    for name in sorted(others):
        rs = others[name]
        lo = _pick_cheapest(rs)
        summary.append(f"<tr><td>{gen.esc(name)} <em>(few verified offers)</em></td><td>{len(rs)}</td>"
                       f"<td>{gen.esc(', '.join(sorted({r['advertiser'] for r in rs})))}</td>"
                       f"<td>{gen.esc(lo['advertiser'])} {gen.esc(_rate_str(lo))}</td></tr>")
    counted = sum(len(f["rates"]) for f in fams.values()) + sum(len(v) for v in others.values())
    assert counted == len(rates) == gen.live_rate_count(), (counted, len(rates), gen.live_rate_count())
    title = f"GPU rental price comparison: {gen.live_rate_count()} verified rates (H100, H200, A100, L40S, RTX 4090) — {fresh}"
    desc = f"Compare verified cloud GPU rental prices from {', '.join(vendors)}: per-hour and monthly, sorted by cost, with vendor quotes and dates."
    faqs = [
        ("Which GPU rental is cheapest per hour among tracked providers?",
         f"Among verified offers, {rows[0]['advertiser']} {rows[0]['gpu']} ({rows[0]['tier']}) at {_rate_str(rows[0])}. The lowest hourly rate isn't always the lowest cost per job; compare VRAM and speed for your model."),
        ("How often are prices checked?", f"Each rate shows the date it was verified against the vendor's pricing page. The newest check on this page is {fresh}."),
        ("Why is my provider missing?", "Only offers with a price we could verify on the vendor's own page are listed. Marketplace providers with live, per-host prices (such as Vast.ai) aren't given a fixed rate."),
        ("Do referral links affect the ranking?", "No. Order is by estimated cost only; referral links are labelled."),
    ]
    body = f"""  <nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › <a href="{gen.BASE}/categories/gpu-compute/">GPU &amp; compute</a> › GPU price comparison</nav>
  <h1>GPU rental price comparison</h1>
  <p class="meta">Prices verified through {fresh} · {gen.live_rate_count()} rates from {len(vendors)} vendors · sorted by effective hourly cost</p>
  <p class="meta"><small>{rate_count_note(gen, _DEALS)}</small></p>
  <p>Verified per-hour and monthly prices for cloud GPUs, from each vendor's own pricing page. Use the <a href="{gen.BASE}/{CALC}/">GPU cost calculator</a> to price your exact hours.</p>
  <h2>By GPU model (all {len(rates)} rates)</h2>
  <table class="howto"><thead><tr><th>Model</th><th>Verified offers</th><th>Vendors</th><th>Lowest pay-as-you-go rate (reserved excluded)</th></tr></thead><tbody>
{chr(10).join(summary)}
  </tbody></table>
  <p>Comparisons: {" · ".join(f'<a href="{gen.BASE}/{p}/">{n}</a>' for p, n in _LINKS)}</p>
  <p>Models get their own page once they have at least {MIN_OFFERS} verified offers from {MIN_VENDORS} vendors.</p>
  <h2>All verified rates</h2>
{_table(gen, rows, full)}
{accuracy_html(gen, rates)}  <h2>FAQ</h2>
{_faq_html(gen, faqs)}
  {_jsonld(url, title, rows, faqs, gen)}
"""
    out = ROOT / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell(title, desc, url, body + install_link_snippet(gen.BASE)), encoding="utf-8")
    return path


# ---------- original comparisons, built only from rates verified on the latest check date ----------

def _key(r):
    """Unique identity of one published rate (vendor + GPU + VRAM + tier + GPUs per server + unit)."""
    return (r["advertiser"], r["gpu"], r.get("vram_gb"), r["tier"], r.get("gpu_count") or 1, r["unit"])


def _today_rates(rates):
    """All current hourly rates (stale vendors are already held out upstream); day = newest check among them.
    Previously only rates checked on the single newest day were used, which emptied the pages whenever one vendor
    was verified a day later than the rest."""
    rs = [r for r in rates if r["unit"] == "hour"]
    return max((r["verified_at"] or "")[:10] for r in rs), rs


def _cmp_page(gen, path, title, desc, h1, crumb, intro, sections, rows_ld, faqs, day):
    url = f"{gen.BASE}/{path}/"
    body = f"""  <nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › <a href="{gen.BASE}/gpu/price-comparison/">GPU prices</a> › {gen.esc(crumb)}</nav>
  <h1>{gen.esc(h1)}</h1>
  <p class="meta">Prices checked through {day} (each row is from its vendor's public pricing page) · sorted by cost · referral status never affects order</p>
  <p>{intro}</p>
{sections}
{accuracy_html(gen, rows_ld)}  <h2>FAQ</h2>
{_faq_html(gen, faqs)}
  <h2>More</h2>
  <ul>{_more_links(gen, exclude=path)}</ul>
  {_jsonld(url, title, rows_ld, faqs, gen)}
"""
    out = ROOT / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell(title, desc, url, body + install_link_snippet(gen.BASE)), encoding="utf-8")
    return path


def _simple_table(head, rows):
    return ("<div style=\"overflow-x:auto\"><table class=\"howto\"><thead><tr>" + "".join(f"<th>{h}</th>" for h in head)
            + "</tr></thead><tbody>\n" + "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
            + "\n</tbody></table></div>")


def _vendor_cell(gen, r):
    return _vendor_link(gen, r)


def _quote_cell(gen, r):
    return f"<a href=\"{gen.esc(r['source_url'] or '')}\" rel=\"noopener\">“{gen.esc(r['evidence']['quote'])}”</a>"


TRACKED = "cheapest among tracked providers"


def accuracy_html(gen, rates: list[dict]) -> str:
    """Caveats shown on every GPU page, compare page and the calculator: GPU-hours vs wall-clock, hardware,
    cited egress/storage extras (or 'Not published'), interruptible vs on-demand. Built only from data/gpu_pricing records."""
    esc = gen.esc
    names = {r["advertiser"] for r in rates}
    docs = [d for d in load_vendor_files() if not names or d["vendor"] in names]

    def cell(x):
        if x["status"] != "published":
            return f"Not published: {esc(x['text'])} (<a href=\"{esc(x['source_url'])}\" rel=\"noopener\">checked {esc(x['checked_at'][:10])}</a>)"
        return f"{esc(x['text'])} (<a href=\"{esc(x['source_url'])}\" rel=\"noopener\">source, {esc(x['checked_at'][:10])}</a>)"
    extras = _simple_table(["Vendor", "Egress", "Storage", "Interruption / billing terms"],
                           [[esc(d["vendor"]), cell(d["extras"]["egress"]), cell(d["extras"]["storage"]), cell(d["extras"]["interruption"])]
                            for d in sorted(docs, key=lambda d: d["vendor"])])
    hw = sorted({(r["gpu"], r.get("vram_gb"), r.get("form_factor") or "not stated") for r in rates}, key=lambda t: (t[0], t[2], t[1] or 0))
    hw_txt = "; ".join(f"{esc(g)}{f' {v} GB' if v else ''} ({esc(ff)})" for g, v, ff in hw)
    intr = sorted({f"{r['advertiser']} {r['gpu']}" for r in rates if r.get("interruptible")})
    intr_txt = (f"Interruptible (preemptible) rates listed here: {esc(', '.join(intr))}. All other rates are on-demand: the vendor doesn't publish preemption for them."
                if intr else "Every rate listed here is on-demand; none is marked interruptible by its vendor.")
    return f"""  <h2>Read before comparing</h2>
  <p>Rankings are the {TRACKED} on our check date, not across the whole market. Vendors we don't track may cost less.</p>
  <h3>GPU-hours vs wall-clock time</h3>
  <p>Prices are per GPU-hour: one GPU for one hour. Four GPUs for 10 wall-clock hours is 40 GPU-hours. Per-second billing (serverless) charges only while your code runs; hourly pods bill from start to stop, idle time included; monthly servers bill a flat price whatever you use. A faster GPU can finish the same job in fewer GPU-hours, so the lowest hourly rate isn't always the lowest cost per job.</p>
  <h3>Hardware differences</h3>
  <p>The same GPU name can mean different hardware. SXM modules link GPUs over NVLink and run at higher power limits than PCIe cards, so an H100 SXM is usually faster than an H100 PCIe, especially for multi-GPU training. Interconnect between GPUs and nodes (NVLink, InfiniBand, plain Ethernet) is rarely listed on pricing pages; treat it as unknown unless the vendor states it. VRAM decides which models fit at all. Hardware as listed: {hw_txt}.</p>
  <h3>Egress and storage extras</h3>
  <p>Totals on this page exclude these. Each cell cites the vendor page it came from; "Not published" means the vendor doesn't publish it there.</p>
{extras}
  <h3>Interruptible vs on-demand</h3>
  <p>Interruptible (preemptible or spot) capacity can be stopped by the vendor mid-job and is usually cheaper; on-demand runs until you stop it. {intr_txt}</p>
"""


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
    t2 = _simple_table(["Vendor", "Lowest-priced H100 (tracked)", "Billing and extras"],
                       [[_vendor_cell(gen, r), f"{gen.esc(r['gpu'])} ({gen.esc(r['tier'])}) {gen.esc(_rate_str(r))}", gen.esc(_VENDOR_FACTS[v])]
                        for v, r in best.items()])
    c = rows[0]
    secure = [r for r in rows if r["tier"] != "On-demand (Community Cloud)"]
    faqs = [("Which of RunPod, Thunder Compute and Modal is cheapest among tracked providers for an H100?",
             f"As of {day}, the lowest listed H100 rate of the three was {c['advertiser']} {c['gpu']} ({c['tier']}) at {_rate_str(c)}, "
             f"or {_money(c['monthly_cost_usd'])} for {DEFAULT_HOURS} GPU hours."),
            ("What is the cheapest tracked H100 outside a community marketplace?",
             f"{secure[0]['advertiser']} {secure[0]['gpu']} ({secure[0]['tier']}) at {_rate_str(secure[0])}." if secure else "None listed."),
            ("When does Modal cost less than an hourly H100?",
             "When your GPU sits idle a lot. Modal charges per second only while code runs, so a spiky inference workload can cost less "
             "even at a higher listed rate. For a GPU busy most of the hour, the lower hourly rate wins."),
            ("What isn't included?", "Storage, extra CPU/RAM, egress and taxes (see the cited extras above). Confirm on each vendor page before you rent.")]
    return _cmp_page(gen, H100_VS, f"RunPod vs Thunder Compute vs Modal for H100: prices checked {day}",
                     f"H100 rental prices on RunPod, Thunder Compute and Modal, checked {day} on each vendor's pricing page, with monthly costs and billing differences.",
                     "RunPod vs Thunder Compute vs Modal for H100", "RunPod vs Thunder Compute vs Modal (H100)",
                     f"Every H100 option these three vendors list publicly, priced for {DEFAULT_HOURS} GPU hours and a full month. Cheapest among tracked providers first.",
                     f"{t1}\n  <h2>How they bill</h2>\n{t2}", rows, faqs, day)


def write_per_vram(gen, rates):
    day, rs = _today_rates(rates)
    rows = sorted((r for r in rs if r.get("vram_gb")), key=lambda r: (r["price_usd"] / r["vram_gb"], r["advertiser"], r["gpu"]))
    t = _simple_table(["#", "GPU", "Vendor", "Type", "Rate", "$ per GB VRAM-hour", "Vendor quote"],
                      [[i, f"{gen.esc(r['gpu'])} {r['vram_gb']} GB", _vendor_cell(gen, r), gen.esc(r["tier"]), gen.esc(_rate_str(r)),
                        f"<strong>${r['price_usd'] / r['vram_gb']:.4f}</strong>", _quote_cell(gen, r)] for i, r in enumerate(rows, 1)])
    c = rows[0]
    big = [r for r in rows if r["vram_gb"] >= 80]
    faqs = [("Which cloud GPU is cheapest per GB of VRAM among tracked providers?",
             f"On {day}: {c['advertiser']} {c['gpu']} {c['vram_gb']} GB ({c['tier']}) at ${c['price_usd'] / c['vram_gb']:.4f} per GB-hour ({_rate_str(c)})."),
            ("Which 80 GB+ GPU is cheapest per GB among tracked providers?",
             f"{big[0]['advertiser']} {big[0]['gpu']} {big[0]['vram_gb']} GB ({big[0]['tier']}) at ${big[0]['price_usd'] / big[0]['vram_gb']:.4f} per GB-hour." if big else "None listed."),
            ("Why rank by VRAM?", "Model size usually decides which GPU you can use at all. Price per GB of VRAM shows the lowest-cost way among tracked providers to fit a "
             "model in memory; it ignores speed, so a faster GPU can still finish a job for less."),
            ("Which rates are included?", f"Only hourly rates checked on {day} on the vendor's own pricing page. Monthly dedicated servers are excluded.")]
    return _cmp_page(gen, PER_VRAM, f"Cloud GPU price per GB of VRAM, cheapest among tracked providers ({day})",
                     f"Cloud GPU rental ranked by price per GB of VRAM per hour: the hourly-billed subset of {gen.live_rate_count()} tracked rates, checked {day} on vendor pricing pages.",
                     "Cloud GPU per GB of VRAM: cheapest among tracked providers", "Price per GB of VRAM",
                     "Hourly rate divided by GPU memory. Useful when you need a model to fit and are deciding which card to rent.",
                     t, rows, faqs, day)


def write_runpod_tiers(gen, rates):
    day, rs = _today_rates(rates)
    rp = [r for r in rs if r["advertiser"] == "RunPod"]
    sec = {r["gpu"]: r for r in rp if r["tier"] == "On-demand (Secure Cloud)"}
    pairs = sorted(((sec[r["gpu"]], r) for r in rp if r["tier"] == "On-demand (Community Cloud)" and r["gpu"] in sec),
                   key=lambda p: -(1 - p[1]["price_usd"] / p[0]["price_usd"]))
    t = _simple_table(["GPU", "Secure Cloud", "Community Cloud", "Saving", f"Saving over {HOURS_PER_MONTH} h"],
                      [[f"{gen.esc(s['gpu'])} {s['vram_gb']} GB", gen.esc(_rate_str(s)), gen.esc(_rate_str(c)),
                        f"<strong>{(1 - c['price_usd'] / s['price_usd']) * 100:.0f}%</strong>", _money((s['price_usd'] - c['price_usd']) * HOURS_PER_MONTH)]
                       for s, c in pairs])
    top, low = pairs[0], pairs[-1]
    rows_ld = [p[1] for p in pairs]
    faqs = [("How much less does RunPod Community Cloud cost?",
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
    out = [(f"gpu/cheapest-{slug}-rental", f"{f['name']}: cheapest among tracked providers") for slug, f in fams.items() if f["page"]]
    return out + [(H100_VS, "RunPod vs Thunder Compute vs Modal (H100)"), (PER_VRAM, "GPU price per GB of VRAM"),
                  (RUNPOD_TIERS, "RunPod Community vs Secure Cloud")]


def links_html(base: str, deals: list[dict]) -> str:
    return " · ".join(f'<a href="{base}/{p}/">{n}</a>' for p, n in page_links(deals))


_DEALS: list[dict] = []


def write_all(gen, deals: list[dict]) -> list[str]:
    _DEALS[:] = deals
    rates = build_rates(deals)["rates"]
    import gpu_model_json
    gpu_model_json.write(gen, rates)
    fams = families(rates)
    _LINKS[:] = page_links(deals)
    pages = {slug: write_model_page(gen, slug, f, rates) for slug, f in fams.items() if f["page"]}
    cmps = [write_h100_vs(gen, rates), write_per_vram(gen, rates), write_runpod_tiers(gen, rates)]
    return [write_hub(gen, rates), write_overview(gen, rates, fams, pages)] + list(pages.values()) + cmps


def _history():
    p = ROOT / "api" / "v1" / "gpu-prices" / "history.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _pct(x) -> str:
    return "" if x is None else f"{x:+.1f}%"


def changes_html(gen, gpu_family: str | None = None, days: int = 30, limit: int = 15) -> str:
    """'Recent price changes' (among tracked providers) from the daily snapshots."""
    from core import gpu_history
    h = _history()
    if not h.get("series"):
        return ""
    ch = gpu_history.recent_changes(h, days=days)
    if gpu_family:
        ch = [c for c in ch if family_of(c["gpu"]) == gpu_family]
    api = f"{gen.BASE}/api/v1/gpu-prices/history.json"
    head = f"  <h2>Recent price changes</h2>\n"
    since = h.get("first_snapshot")
    if not ch:
        return (head + f"  <p>No price changes among tracked providers in the last {days} days "
                f"(daily snapshots since {gen.esc(since or '')}). Full series: <a href=\"{api}\">price history JSON</a>.</p>\n")
    rows = "".join(
        f"<tr><td>{gen.esc(c['date'])}</td><td>{gen.esc(c['vendor'])}</td><td>{gen.esc(c['gpu'])} ({gen.esc(c['tier'])})</td>"
        f"<td>${c['from_hourly_usd']:g} → ${c['to_hourly_usd']:g}/hr</td>"
        f"<td>{_pct(c.get('change_pct'))}</td></tr>"
        for c in ch[:limit])
    return (head + f"  <p>Price changes among tracked providers in the last {days} days, per GPU-hour, from daily snapshots "
            f"since {gen.esc(since or '')}. Full series: <a href=\"{api}\">price history JSON</a>.</p>\n"
            "  <div class=\"tscroll\"><table class=\"howto sticky1\"><thead><tr><th>Date</th><th>Provider</th><th>GPU</th><th>Price</th><th>Change</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>\n")


def write_hub(gen, rates: list[dict]) -> str:
    """/gpu/ hub: entry point linking every GPU page, tool and data endpoint."""
    path = "gpu"
    url = f"{gen.BASE}/{path}/"
    fresh = _freshness(rates) if rates else ""
    extra = [(p, n) for p, n in (("compare/cheap-gpu-rental", "Cheap GPU rental deals"),)
             if (ROOT / p / "index.html").exists()]
    li = lambda items: "".join(f'<li><a href="{gen.BASE}/{p}/">{n}</a></li>' for p, n in items)
    cheapest = [(p, n) for p, n in _LINKS if p.startswith("gpu/cheapest-")]
    cmps = [(p, n) for p, n in _LINKS if not p.startswith("gpu/cheapest-")] + extra
    title = "GPU rental prices, calculator and comparisons | Lantern Works"
    desc = "Hub for cloud GPU rental pricing: cost calculator, cheapest-GPU pages by model, side-by-side comparisons and the public GPU pricing API."
    body = f"""  <nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › GPU</nav>
  <h1>GPU rental prices</h1>
  <p class="meta">{gen.live_rate_count()} tracked rates{(" · newest check " + fresh) if fresh else ""} · "cheapest" means cheapest among tracked providers</p>
{changes_html(gen)}  <h2>Tools</h2>
  <ul><li><a href="{gen.BASE}/{CALC}/">GPU cost calculator</a></li><li><a href="{gen.BASE}/gpu/price-comparison/">All tracked GPU rental prices</a></li></ul>
  <h2>Cheapest GPU by model</h2>
  <ul>{li(cheapest)}</ul>
  <h2>Comparisons</h2>
  <ul>{li(cmps)}</ul>
  <h2>Deals and data</h2>
  <ul><li><a href="{gen.BASE}/categories/gpu-compute/">GPU &amp; compute deals</a></li><li><a href="{gen.BASE}/api/v1/gpu-prices.json">GPU pricing API (JSON)</a></li><li><a href="{gen.BASE}/api/v1/gpu-prices/history.json">GPU price history (JSON)</a></li><li><a href="{gen.BASE}/api/v1/stack-pricing.json">Stack pricing API (JSON)</a></li></ul>
"""
    out = ROOT / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell(title, desc, url, body + install_link_snippet(gen.BASE)), encoding="utf-8")
    return path
