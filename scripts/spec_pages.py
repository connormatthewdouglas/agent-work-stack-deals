"""Pulse-spec pages built only from the public feeds in api/v1/:
- /gpu/{slug}-rental-price/        (per-gpu-pages-spec.md)
- /compare/{a}-vs-{b}-gpu-prices/  (vendor-vs-vendor-spec.md)
- /gpu/changes/ + /gpu/changes.xml (same data as get_price_changes: history.json `changes`)
- /docs/watch-gpu-prices/
Fails closed: a missing feed or an unknown schema version (see SCHEMAS) raises before anything is written.
Reserved tier is never in a "cheapest" headline or a win count.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.sax.saxutils import escape as xesc

import gpu_pages as gp

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api" / "v1"
# Accepted schema versions per feed. history /2 (T38) only adds ids (rate_id, event_id, seq, snapshot_id).
SCHEMAS = {"prices": ("gpu-prices.json", ("lantern-works-gpu-prices/1",)),
           "changes": ("gpu-price-changes.json", ("lantern-works-gpu-price-changes/1",)),
           "history": ("gpu-prices/history.json", ("lantern-works-gpu-price-history/1", "lantern-works-gpu-price-history/2"))}
FAMILY_MAP = {"H100": "H100", "H100 SXM": "H100", "H100 PCIe": "H100",
              "H200": "H200", "H200 SXM": "H200",
              "A100": "A100", "A100 SXM": "A100", "A100 PCIe": "A100"}
MIN_VENDORS = 3
PAIRS = [("RunPod", "Verda (formerly DataCrunch)"), ("Lambda", "RunPod"), ("CoreWeave", "Nebius")]
MIN_SHARED = 3
DISCLOSURE = "Some links are referral links; Lantern Works may earn credit. Affiliate status is not a ranking factor."
ET = timezone(timedelta(hours=-4))  # display only; label says ET
SPEC_PATHS: list[str] = []
# Near-duplicate of an older page: rel=canonical points there and the URL stays out of the sitemap.
CANONICAL_OVERRIDE: dict[str, str] = {}  # none: /gpu/<gpu>-rental-price/ pages are canonical


def load_feeds() -> dict:
    out = {}
    for k, (f, schemas) in SCHEMAS.items():
        p = API / f
        d = json.loads(p.read_text(encoding="utf-8"))  # raises if missing -> keep last good build
        if d.get("schema") not in schemas:
            raise SystemExit(f"spec_pages: {f} schema {d.get('schema')!r} not in {list(schemas)!r}; keeping last good build")
        out[k] = d
    return out


def family(gpu: str) -> str:
    return FAMILY_MAP.get(gpu, gpu)


def slug(s: str) -> str:
    return s.lower().replace("(formerly datacrunch)", "").strip().replace(" ", "-").replace(".", "")


def short_vendor(v: str) -> str:
    return v.split(" (formerly")[0]


def key(r) -> str:
    return f"{r['advertiser']}|{r['gpu']}|{r['tier']}|{r['vram_gb']}|{r['gpu_count']}"


def bucket(r) -> str:
    t = (r.get("tier") or "")
    if r.get("tier_class") == "reserved":
        return "Reserved"
    if r.get("billing_unit") == "monthly":
        return "Monthly"
    if "Serverless" in t:
        return "Serverless"
    if r.get("interruptible") or any(w in t for w in ("Spot", "Community", "Marketplace")) or r.get("price_status") == "marketplace":
        return "Spot & community"
    return "On-demand"


BUCKETS = ["On-demand", "Spot & community", "Serverless", "Monthly", "Reserved"]


def rankable(prices):
    return [r for r in prices["rates"] if r.get("hourly_equiv_usd") is not None]


def m(x) -> str:
    return f"${x:,.2f}"


def ts(iso: str) -> str:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return f"{d:%Y-%m-%d %H:%M} UTC ({d.astimezone(ET):%H:%M} ET)"


def max_verified(rows) -> str:
    return max((r["verified_at"] for r in rows), key=lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")))


def change_text(gen, ch, k, prev):
    c = ch.get(k)
    if not c:
        return "no change"
    if c["change"] == "new":
        return "newly tracked"
    if c["change"] == "removed":
        return "removed"
    return f"{c['change']} {c['pct']:+g}% since {gen.esc(prev)}"


def seven_day_ready(history) -> bool:
    f = datetime.fromisoformat(history["first_snapshot"]); l = datetime.fromisoformat(history["last_snapshot"])
    return (l - f).days >= 7


def price_cell(gen, r) -> str:
    s = m(r["hourly_equiv_usd"])
    if r.get("price_status") == "marketplace":
        s += f" (median of {r['offer_count']} offers; lowest ${r['lowest_offer_usd']:g})"
    if (r.get("min_gpus") or 1) > 1:
        s += f" (sold as {r['min_gpus']}-GPU only; server {m(r['server_hourly_usd'])}/hr)" if r.get("server_hourly_usd") else f" (sold as {r['min_gpus']}-GPU only)"
    if r.get("billing_unit") == "monthly":
        s = f"{m(r['price_usd'])}/mo monthly flat"
    if r.get("interruptible"):
        s += " · may be preempted"
    return s


def vendor_link(gen, r) -> str:
    q = gen.esc((r.get("evidence") or {}).get("quote") or "")
    out = f'<a href="{gen.esc(r["source_url"])}" title="{q}" rel="noopener">{gen.esc(r["advertiser"])}</a>'
    return out


def link_word(r) -> str:
    return "Referral link" if r.get("affiliate") else "Direct link"


def link_cell(gen, r) -> str:
    """H4: link type in words, plus the redeem link when there is one."""
    w = link_word(r)
    return f'<a href="{gen.esc(r["redeem_url"])}" rel="sponsored nofollow noopener">{w}</a>' if r.get("redeem_url") else w


LEGEND = ("<p class=\"meta\"><strong>Link:</strong> \u201cReferral link\u201d means Lantern Works may earn credit if you sign up through it; "
          "\u201cDirect link\u201d goes to the vendor with no referral. Neither affects order. ")


def deal_link(gen, r) -> str:
    return f'<a href="{gen.esc(r["redeem_url"])}" rel="sponsored nofollow noopener">Get deal</a>' if r.get("redeem_url") else ""


def recheck_flag(r) -> str:
    return " <small>last re-check failed to parse</small>" if r["verified_at"] < r["checked_at"] else ""


def faq_block(gen, faqs):
    html = "".join(f"<h3>{gen.esc(q)}</h3><p>{gen.esc(a)}</p>" for q, a in faqs)
    ld = {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs]}
    return html, ld


def write(gen, path: str, title: str, desc: str, canonical: str, body: str, ld: list) -> str:
    body += '\n<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": ld}, ensure_ascii=False) + "</script>\n"
    out = ROOT / path / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(gen.page_shell(title, desc, canonical, body), encoding="utf-8")
    SPEC_PATHS.append(path)
    return path


def feed_links(gen) -> str:
    b = gen.BASE
    return (f'<a href="{b}/api/v1/gpu-prices.json">gpu-prices.json</a> · <a href="{b}/api/v1/gpu-price-changes.json">gpu-price-changes.json</a>'
            f' (<a href="{b}/api/v1/gpu-price-changes.xml">RSS</a>) · <a href="{b}/api/v1/gpu-prices/history.json">history.json</a>')


# ---------- per-GPU ----------
def qualifying_families(rates) -> dict[str, list]:
    fams: dict[str, list] = {}
    for r in rates:
        fams.setdefault(family(r["gpu"]), []).append(r)
    return {f: rs for f, rs in fams.items() if len({r["advertiser"] for r in rs if bucket(r) != "Reserved"}) >= MIN_VENDORS}


def gpu_url(gen, fam: str) -> str:
    return f"{gen.BASE}/gpu/{slug(fam)}-rental-price/"


def write_gpu_page(gen, fam, rows, feeds, quals) -> str:
    esc = gen.esc
    prices, changes, history = feeds["prices"], feeds["changes"], feeds["history"]
    ch = {c["key"]: c for c in changes["changes"]}
    prev = changes["previous_date"]
    vend = {v["vendor"]: v for v in prices["vendors"]}
    by_b = {b: sorted([r for r in rows if bucket(r) == b], key=lambda r: r["hourly_equiv_usd"]) for b in BUCKETS}
    od = [r for r in by_b["On-demand"] if r["billing_unit"] in ("hourly", "per-second")]
    sp = by_b["Spot & community"]
    nv = len({r["advertiser"] for r in rows if bucket(r) != "Reserved"})
    mv = max_verified(rows); day = mv[:10]
    canon = CANONICAL_OVERRIDE.get(fam, gpu_url(gen, fam))
    title = f"Rent {fam}: price today | Lantern Works"
    desc = (f"{fam} rental from {m(od[0]['hourly_equiv_usd'])}/GPU-hr on-demand ({od[0]['advertiser']}) across {nv} tracked providers."
            if od else f"{fam} rental prices across {nv} tracked providers.")
    if sp:
        desc += f" Spot/community from {m(sp[0]['hourly_equiv_usd'])}."
    desc += f" Checked {day}."
    body = [f'<nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › <a href="{gen.BASE}/gpu/">GPU prices</a> › {esc(fam)}</nav>',
            f"<h1>Rent {esc(fam)}: price today</h1>",
            f'<p class="meta">Prices verified {ts(mv)}. Per GPU-hour, among tracked providers only.</p>']
    cards = []
    if od:
        r = od[0]
        extra = f" Sold as {r['min_gpus']}-GPU only ({m(r['server_hourly_usd'])}/hr per server)." if (r.get("min_gpus") or 1) > 1 and r.get("server_hourly_usd") else ""
        cards.append(f"<div class=\"card\"><h2>Cheapest on-demand among tracked providers</h2><p><strong>{m(r['hourly_equiv_usd'])}/GPU-hr</strong> · {vendor_link(gen, r)} · {esc(r['gpu'])} · {esc(r['tier'])}.{extra}</p></div>")
    if sp:
        r = sp[0]
        note = " May be preempted." if r.get("interruptible") else ""
        if r.get("price_status") == "marketplace":
            note += f" Median of {r['offer_count']} offers; lowest ${r['lowest_offer_usd']:g}."
        cards.append(f"<div class=\"card\"><h2>Cheapest spot / community among tracked providers</h2><p><strong>{m(r['hourly_equiv_usd'])}/GPU-hr</strong> · {vendor_link(gen, r)} · {esc(r['gpu'])} · {esc(r['tier'])}.{note}</p></div>")
    body += cards
    body.append(f"<p><em>{DISCLOSURE}</em></p>")
    show7 = seven_day_ready(history)
    for b in BUCKETS:
        rs = by_b[b]
        if not rs:
            continue
        has_av = any(((r.get("availability") or {}).get("in_stock") is not None) for r in rs)
        hdr = ("<tr><th>Vendor</th><th>Variant</th><th>VRAM</th><th>Tier</th><th>$/GPU-hr</th><th>Since " + esc(prev) + "</th><th>Egress / storage</th><th>Vendor quote</th><th>Verified</th>"
               + ("<th>Availability (manual snapshot)</th>" if has_av else "") + "<th>Link</th></tr>")
        trs = []
        for r in rs:
            ex = (vend.get(r["advertiser"]) or {}).get("extras") or {}
            ext = "; ".join(f"{k}: {esc(ex[k]['text'])}" if ex.get(k, {}).get("status") == "published" else f"{k}: not published / not verified" for k in ("egress", "storage"))
            trs.append(f"<tr><td data-label=\"Vendor\">{vendor_link(gen, r)}</td><td data-label=\"Variant\">{esc(r['gpu'])}</td><td data-label=\"VRAM\">{r['vram_gb'] or ''} GB</td><td data-label=\"Tier\">{esc(r['tier'])}</td><td data-label=\"$/GPU-hr\">{esc(price_cell(gen, r))}</td>"
                       f"<td data-label=\"Since {esc(prev)}\">{change_text(gen, ch, key(r), prev)}</td><td data-label=\"Egress / storage\"><small>{ext}</small></td><td data-label=\"Vendor quote\">{gp._quote_html(esc, r)}</td>"
                       f"<td data-label=\"Verified\"><small>{ts(r['verified_at'])}</small>{recheck_flag(r)}</td>" + (f"<td data-label=\"Availability\">{gp._avail_cell(gen, r)}</td>" if has_av else "")
                       + f"<td data-label=\"Link\">{link_cell(gen, r)}</td></tr>")
        label = b + (" (reservation / term contract; excluded from the cheapest among tracked providers ranking)" if b == "Reserved" else "")
        av_note = ("<strong>Availability:</strong> \u201c\u2014\u201d means no stock signal for that offer; where shown, it is a manual snapshot and stock changes within minutes, so it is not a guarantee."
                   if has_av else "<strong>Availability</strong> is hidden because no vendor here publishes a stock signal yet.")
        body.append(f"<h2>{esc(label)}</h2><div class=\"tscroll rates-cards\"><table class=\"howto\"><thead>{hdr}</thead><tbody>{''.join(trs)}</tbody></table></div>"
                    + LEGEND + "<strong>Vendor quote:</strong> a short excerpt of the vendor's pricing page; open it for the full text and source. " + av_note + "</p>")
    if not show7:
        body.append(f"<p><small>7-day change appears once price history spans 7 days (history starts {esc(history['first_snapshot'])}).</small></p>")
    held = [h for h in prices.get("held_stale", []) if any(family(x.get("gpu", "")) == fam for x in h.get("records", []))]
    for h in held:
        body.append(f"<p><small>{esc(h['vendor'])} not shown: held until re-verified (vendor pricing page last updated {esc(h.get('page_last_updated') or 'unknown')}).</small></p>")
    faqs = []
    if od:
        faqs.append((f"What is the cheapest {fam} among tracked providers per hour?", f"Among tracked providers, {od[0]['advertiser']} at {m(od[0]['hourly_equiv_usd'])} per GPU-hour on-demand ({od[0]['tier']}), verified {od[0]['verified_at'][:10]}."))
    if od and sp:
        faqs.append((f"Is spot cheaper for {fam}?", f"The cheapest spot/community rate among tracked providers is {m(sp[0]['hourly_equiv_usd'])} ({sp[0]['advertiser']}) vs {m(od[0]['hourly_equiv_usd'])} on-demand. Spot or interruptible capacity may be preempted."))
    faqs.append(("Are egress and storage included?", "No. Totals exclude storage, egress, extra vCPU and taxes; each vendor's published terms (or 'not published') are shown in the table."))
    faqs.append(("How often are prices checked?", "A daily job re-reads every vendor pricing page; a rate not re-verified for 7 days is held and never ranked."))
    fh, fld = faq_block(gen, faqs)
    body.append(__import__("gpu_pages").accuracy_html(gen, rows))
    body.append("<h2>FAQ</h2>" + fh)
    sib = " · ".join(f'<a href="{gpu_url(gen, f)}">{esc(f)}</a>' for f in sorted(quals) if f != fam)
    body.append(f"<h2>More</h2><p>Other GPUs: {sib}</p><p><a href=\"{gen.BASE}/gpu/\">GPU price hub</a> · <a href=\"{gen.BASE}/gpu/changes/\">price changes</a> · Data source: {feed_links(gen)}</p>")
    hourly = [r for r in rows if bucket(r) not in ("Monthly", "Reserved")]
    ld = [{"@type": "Product", "name": f"NVIDIA {fam} GPU rental (per GPU-hour)",
           "offers": {"@type": "AggregateOffer", "priceCurrency": "USD", "lowPrice": min(r["hourly_equiv_usd"] for r in hourly),
                      "highPrice": max(r["hourly_equiv_usd"] for r in hourly), "offerCount": len(hourly),
                      "offers": [{"@type": "Offer", "seller": {"@type": "Organization", "name": r["advertiser"]}, "price": r["hourly_equiv_usd"],
                                  "priceCurrency": "USD", "url": r["source_url"], "description": r["tier"]} for r in hourly]}},
          {"@type": "Dataset", "name": f"{fam} rental prices", "url": canon, "dateModified": mv,
           "distribution": [{"@type": "DataDownload", "contentUrl": f"{gen.BASE}/api/v1/gpu-prices.json", "encodingFormat": "application/json"}]}, fld]
    return write(gen, f"gpu/{slug(fam)}-rental-price", title, desc, canon, "\n".join(body), ld)


# ---------- vendor vs vendor ----------
def cells(rates, vendor):
    out = {}
    for r in rates:
        if r["advertiser"] != vendor or bucket(r) == "Reserved":
            continue
        k = (bucket(r), r["gpu"], r["vram_gb"])
        if k not in out or r["hourly_equiv_usd"] < out[k]["hourly_equiv_usd"]:
            out[k] = r
    return out


def write_pair(gen, a, b, feeds, quals) -> str | None:
    esc = gen.esc
    prices, changes = feeds["prices"], feeds["changes"]
    vend = {v["vendor"]: v for v in prices["vendors"]}
    held = {h["vendor"] for h in prices.get("held_stale", [])}
    if a not in vend or b not in vend or a in held or b in held:
        return None
    rates = rankable(prices)
    ca, cb = cells(rates, a), cells(rates, b)
    shared = sorted(set(ca) & set(cb), key=lambda k: (BUCKETS.index(k[0]), k[1], k[2] or 0))
    if len(shared) < MIN_SHARED:
        return None
    ch = {c["key"]: c for c in changes["changes"]}; prev = changes["previous_date"]
    sa, sb = short_vendor(a), short_vendor(b)
    path = f"compare/{slug(sa)}-vs-{slug(sb)}-gpu-prices"
    canon = f"{gen.BASE}/{path}/"
    wins = {"a": 0, "b": 0, "t": 0}; per_bucket: dict[str, dict] = {}
    for k in shared:
        x, y = ca[k]["hourly_equiv_usd"], cb[k]["hourly_equiv_usd"]
        w = "t" if x == y else ("a" if x < y else "b")
        wins[w] += 1; per_bucket.setdefault(k[0], {"a": 0, "b": 0, "t": 0})[w] += 1
    gpus = sorted({k[1] for k in shared})
    mv = max_verified([ca[k] for k in shared] + [cb[k] for k in shared]); day = mv[:10]
    title = f"{sa} vs {sb} GPU prices: {len(shared)} GPUs compared | Lantern Works"
    desc = (f"{sa} vs {sb} on {len(gpus)} GPUs ({', '.join(gpus[:4])}): {sa} cheaper on {wins['a']}, {sb} on {wins['b']}"
            + (f", ties {wins['t']}" if wins["t"] else "") + f" among tracked providers. Same-tier, per GPU-hour. Checked {day}.")
    body = [f'<nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › <a href="{gen.BASE}/gpu/">GPU prices</a> › {esc(sa)} vs {esc(sb)}</nav>',
            f"<h1>{esc(a)} vs {esc(b)}: GPU rental prices compared</h1>",
            f'<p class="meta">Prices verified {ts(mv)}. Cheaper means cheaper in our tracked rates.</p>']
    summ = "; ".join(f"{bk}: {sa} {v['a']}, {sb} {v['b']}" + (f", ties {v['t']}" if v["t"] else "") for bk, v in per_bucket.items())
    body.append(f"<div class=\"card\"><h2>Summary</h2><p>{esc(sa)} cheaper in {wins['a']} of {len(shared)}, {esc(sb)} in {wins['b']}, ties {wins['t']}. ({esc(summ)})</p></div>")
    body.append(f"<p><em>{DISCLOSURE}</em></p>")
    for bk in BUCKETS:
        ks = [k for k in shared if k[0] == bk]
        if not ks:
            continue
        trs = []
        for k in ks:
            ra, rb = ca[k], cb[k]; x, y = ra["hourly_equiv_usd"], rb["hourly_equiv_usd"]
            diff = abs(x - y); pct = diff / max(x, y) * 100 if max(x, y) else 0
            win = "tie" if x == y else (sa if x < y else sb)
            fam = family(k[1]); g = f'<a href="{gpu_url(gen, fam)}">{esc(k[1])}</a>' if fam in quals else esc(k[1])
            trs.append(f"<tr><td data-label=\"GPU\">{g}</td><td data-label=\"VRAM\">{k[2] or ''} GB</td><td data-label=\"{esc(sa)} $/GPU-hr\">{esc(price_cell(gen, ra))} <small>({esc(ra['tier'])})</small> · {link_cell(gen, ra)}<br>{gp._quote_html(esc, ra)}</td>"
                       f"<td data-label=\"{esc(sb)} $/GPU-hr\">{esc(price_cell(gen, rb))} <small>({esc(rb['tier'])})</small> · {link_cell(gen, rb)}<br>{gp._quote_html(esc, rb)}</td><td data-label=\"Diff (vs dearer)\">{m(diff)} ({pct:.0f}%)</td>"
                       f"<td data-label=\"Since {esc(prev)}\">{esc(sa)}: {change_text(gen, ch, key(ra), prev)}<br>{esc(sb)}: {change_text(gen, ch, key(rb), prev)}</td><td data-label=\"Cheaper\"><strong>{esc(win)}</strong></td></tr>")
        body.append(f"<h2>{esc(bk)}</h2><div class=\"tscroll rates-cards\"><table class=\"howto\"><thead><tr><th>GPU</th><th>VRAM</th><th>{vendor_link(gen, ca[ks[0]]).split('</a>')[0]}</a> $/GPU-hr</th>"
                    f"<th>{esc(sb)} $/GPU-hr</th><th>Diff (vs dearer)</th><th>Since {esc(prev)}</th><th>Cheaper</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
                    + LEGEND + "Each price cell has a short excerpt of the vendor's pricing page; open it for the full text and source.</p>")
    only = {v: sorted({k[1] for k in c} - set(gpus)) for v, c in ((sa, ca), (sb, cb))}
    if any(only.values()):
        body.append("<details><summary>GPUs only one vendor prices</summary>" + "".join(f"<p>{esc(v)}: {esc(', '.join(g))}</p>" for v, g in only.items() if g) + "</details>")
    def bill(v):
        d = vend[v]; ex = d.get("extras") or {}
        lines = [f"Billing granularity: {esc(d.get('billing_granularity') or 'not stated in feed')}"]
        for k in ("egress", "storage", "interruption"):
            e = ex.get(k) or {}
            lines.append(f"{k}: " + (f"{esc(e['text'])} (<a href=\"{esc(e['source_url'])}\">source</a>)" if e.get("status") == "published" else "not published / not verified"))
        return f"<div class=\"card\"><h3>{esc(short_vendor(v))}</h3><p>" + "<br>".join(lines) + "</p></div>"
    body.append("<h2>Billing &amp; extras</h2>" + bill(a) + bill(b))
    faqs = [(f"Is {sa} or {sb} cheaper for {k[1]} ({k[0]})?",
             (f"Tie at {m(ca[k]['hourly_equiv_usd'])}" if ca[k]["hourly_equiv_usd"] == cb[k]["hourly_equiv_usd"] else
              f"{sa if ca[k]['hourly_equiv_usd'] < cb[k]['hourly_equiv_usd'] else sb} is cheaper in our tracked rates") +
             f": {sa} {m(ca[k]['hourly_equiv_usd'])} vs {sb} {m(cb[k]['hourly_equiv_usd'])} per GPU-hour.") for k in shared[:3]]
    faqs.append(("Are egress and storage included?", "No. Comparisons are compute-only; totals exclude storage, egress, extra vCPU and taxes. See Billing & extras."))
    fh, fld = faq_block(gen, faqs)
    body.append(__import__("gpu_pages").accuracy_html(gen, [ca[k] for k in shared] + [cb[k] for k in shared]))
    body.append("<h2>FAQ</h2>" + fh + f"<h2>More</h2><p><a href=\"{gen.BASE}/gpu/\">GPU price hub</a> · <a href=\"{gen.BASE}/gpu/changes/\">price changes</a> · Data: {feed_links(gen)}</p>")
    def prod(v, c):
        hr = [c[k] for k in shared if k[0] not in ("Monthly",)]
        return {"@type": "Product", "name": f"{short_vendor(v)} GPU rental (per GPU-hour)",
                "offers": {"@type": "AggregateOffer", "priceCurrency": "USD", "lowPrice": min(r["hourly_equiv_usd"] for r in hr), "highPrice": max(r["hourly_equiv_usd"] for r in hr),
                           "offerCount": len(hr), "offers": [{"@type": "Offer", "price": r["hourly_equiv_usd"], "priceCurrency": "USD", "url": r["source_url"], "description": f"{r['gpu']} {r['vram_gb']}GB {r['tier']}"} for r in hr]}}
    ld = [{"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": i + 1, "item": {"@type": "Organization", "name": v, "url": vend[v]["source_url"]}} for i, v in enumerate((a, b))]},
          prod(a, ca), prod(b, cb),
          {"@type": "Dataset", "name": f"{sa} vs {sb} GPU prices", "url": canon, "dateModified": mv,
           "distribution": [{"@type": "DataDownload", "contentUrl": f"{gen.BASE}/api/v1/gpu-prices.json", "encodingFormat": "application/json"}]}, fld]
    return write(gen, path, title, desc, canon, "\n".join(body), ld)


# ---------- changes page + feed ----------
def write_changes(gen, feeds) -> str:
    esc = gen.esc
    h = feeds["history"]; chs = sorted(h.get("changes", []), key=lambda c: (c["date"], c["vendor"], c["gpu"]), reverse=True)
    canon = f"{gen.BASE}/gpu/changes/"
    trs = "".join(f"<tr><td>{esc(c['date'])}</td><td><a href=\"{esc(c['source_url'])}\" rel=\"noopener\">{esc(c['vendor'])}</a></td><td>{esc(c['gpu'])}</td><td>{esc(c['tier'])}</td>"
                  f"<td>{m(c['from_hourly_usd'])} → {m(c['to_hourly_usd'])}</td><td>{c['change_pct']:+g}%</td></tr>" for c in chs)
    body = (f'<nav class="crumbs"><a href="{gen.BASE}/">Lantern Works</a> › <a href="{gen.BASE}/gpu/">GPU prices</a> › Changes</nav>'
            f"<h1>GPU price changes</h1><p class=\"meta\">Per GPU-hour moves among tracked providers, {esc(h['first_snapshot'])} to {esc(h['last_snapshot'])} ({h['snapshot_count']} daily snapshots). Same data as the <code>get_price_changes</code> MCP tool.</p>"
            f"<p>Subscribe: <a href=\"{gen.BASE}/gpu/changes.xml\">/gpu/changes.xml</a> (RSS) · JSON: {feed_links(gen)}</p>"
            + (f"<div class=\"tscroll\"><table class=\"howto sticky1\"><thead><tr><th>Date</th><th>Vendor</th><th>GPU</th><th>Tier</th><th>Old → new</th><th>Change</th></tr></thead><tbody>{trs}</tbody></table></div>" if chs else "<p>No price moves recorded yet.</p>")
            + __import__("gpu_pages").accuracy_html(gen, rankable(feeds["prices"]))
            + f"<p><a href=\"{gen.BASE}/docs/watch-gpu-prices/\">How to watch GPU prices from an agent</a></p>")
    write(gen, "gpu/changes", "GPU price changes (daily) | Lantern Works", "Daily GPU rental price moves among tracked providers, with old and new per-GPU-hour prices and vendor sources.", canon, body,
          [{"@type": "Dataset", "name": "GPU price changes", "url": canon, "dateModified": h["last_snapshot"],
            "distribution": [{"@type": "DataDownload", "contentUrl": f"{gen.BASE}/api/v1/gpu-prices/history.json", "encodingFormat": "application/json"}]}])
    items = "".join(
        f"<item><title>{xesc(c['vendor'])} {xesc(c['gpu'])}: ${c['from_hourly_usd']:g} → ${c['to_hourly_usd']:g}/GPU-hr ({c['change_pct']:+g}%)</title>"
        f"<link>{xesc(c['source_url'])}</link><guid isPermaLink=\"false\">{xesc(c['date'] + '|' + c['key'])}</guid>"
        f"<pubDate>{datetime.fromisoformat(c['date']).replace(tzinfo=timezone.utc):%a, %d %b %Y 00:00:00 +0000}</pubDate>"
        f"<description>{xesc(c['tier'])}. Among tracked providers.</description></item>" for c in chs)
    rss = (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel><title>Lantern Works GPU price changes</title>'
           f"<link>{canon}</link><atom:link href=\"{gen.BASE}/gpu/changes.xml\" rel=\"self\" type=\"application/rss+xml\"/>"
           f"<description>Daily GPU rental price moves among tracked providers.</description>{items}</channel></rss>\n")
    (ROOT / "gpu" / "changes.xml").write_text(rss, encoding="utf-8")
    return "gpu/changes"


def write_watch_doc(gen) -> str:
    b = gen.BASE
    body = f"""<nav class="crumbs"><a href="{b}/">Lantern Works</a> › Docs › Watch GPU prices</nav>
<h1>Watch GPU prices</h1>
<p>Three ways to follow GPU rental price moves among tracked providers. Prices refresh daily.</p>
<h2>1. RSS</h2><p>Add <a href="{b}/gpu/changes.xml">{b}/gpu/changes.xml</a> to any feed reader, or browse <a href="{b}/gpu/changes/">/gpu/changes/</a>.</p>
<h2>2. MCP tool</h2><pre><code>uvx lantern-works-deals-mcp</code></pre>
<p>Or the hosted endpoint (no install): <code>https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=docs-watch</code>. Call <code>get_price_changes(since="YYYY-MM-DD")</code> for every move on or after a date (optional <code>gpu</code> filter); without <code>since</code> it returns the latest day's moves. <code>compare_gpu_prices(gpu="H100", include_history=true)</code> adds per-rate history.</p>
<h2>3. JSON</h2><p>{feed_links(gen)}. The changes feed compares the two latest daily snapshots; history.json carries every change point since {json.loads((API / 'gpu-prices/history.json').read_text())['first_snapshot']}.</p>
<p>Full install options: <a href="{b}/install/">/install/</a>.</p>"""
    return write(gen, "docs/watch-gpu-prices", "Watch GPU prices (RSS, MCP, JSON) | Lantern Works",
                 "Follow daily GPU rental price changes via RSS, the get_price_changes MCP tool, or JSON feeds.", f"{b}/docs/watch-gpu-prices/", body, [])


def write_all(gen) -> list[str]:
    SPEC_PATHS.clear()
    feeds = load_feeds()
    rates = rankable(feeds["prices"])
    quals = qualifying_families(rates)
    for fam, rows in sorted(quals.items()):
        write_gpu_page(gen, fam, rows, feeds, quals)
    for a, b in PAIRS:
        write_pair(gen, a, b, feeds, quals)
    write_changes(gen, feeds)
    write_watch_doc(gen)
    dup = {f"gpu/{slug(f)}-rental-price" for f in CANONICAL_OVERRIDE}
    return [p for p in SPEC_PATHS if p not in dup]


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import generate_seo_pages as gen
    print("\n".join(write_all(gen)))
