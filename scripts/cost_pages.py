"""/cost/{gpu}-{hours}-hours/ (T24 part A, spec /workspace/pulse/specs/t24-workload-pages-ready.md): "Cost to rent
{GPU} for N hours" on 1 GPU, pure feed math (rate x hours x 1). Fail closed: on-demand, non-interruptible, non-serverless,
hourly/per-second billing, min_gpus == 1, vendor not held; reserved/thin/held/marketplace/monthly rows never appear.
Variants (exact gpu + vram) are never mixed; a variant needs >= 2 vendors, and "cheapest" needs >= 3.
Replace the math with T35 quote() when it ships; do not grow a second pricing engine here."""
from __future__ import annotations

import html
import re
from html import escape as esc_
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

GPUS = {"h100": "H100", "a100": "A100", "l40s": "L40S", "rtx-4090": "RTX 4090"}
HOURS = (10, 100, 730)
ET = ZoneInfo("America/New_York")
LABEL = ("Compute subtotal only, excludes storage, egress, vCPU, tax. Among tracked providers. "
         "Not an availability claim, except rows marked out of stock when checked. Assumes {h} h on 1 GPU.")


NEVER_ON_COST = {"TensorDock", "Clore.ai"}


def eligible(feed: dict, family: str) -> dict[tuple, list[dict]]:
    # Record-level holds are already out of rates, so they don't exclude a vendor's other rows; TensorDock and Clore.ai never appear.
    held = {h.get("vendor") for h in feed.get("held_stale") or [] if h.get("scope") != "record"} | NEVER_ON_COST
    out: dict[tuple, list[dict]] = {}
    for r in feed["rates"]:
        g = r.get("gpu") or ""
        if not (g == family or g.startswith(family + " ")):
            continue
        if (r.get("advertiser") in held or r.get("hourly_equiv_usd") is None
                or r.get("billing_unit") not in ("hourly", "per-second") or r.get("tier_class") != "on-demand"
                or r.get("interruptible") or "serverless" in (r.get("tier") or "").lower()
                or (r.get("min_gpus") or 1) != 1 or r.get("price_status") not in (None, "listed")):
            continue
        out.setdefault((g, r.get("vram_gb")), []).append(r)
    return {k: sorted(v, key=lambda r: (oos(r), r["hourly_equiv_usd"], r["advertiser"])) for k, v in out.items()}


def oos(r: dict) -> bool:
    """Feed explicitly marks the row out of stock when checked (unknown is not out of stock)."""
    a = r.get("availability")
    return isinstance(a, dict) and a.get("in_stock") is False


def _tax_note(r: dict) -> str:
    t = ((r.get("tier") or "") + " " + json.dumps(r.get("evidence") or "")).lower()
    return " (excl. tax/VAT)" if ("excl" in t and ("tax" in t or "vat" in t)) else ""


def _oos_label(r: dict) -> str:
    a = r.get("availability") if isinstance(r.get("availability"), dict) else {}
    if a.get("availability_stale"):
        return f' <small class="av">({html.escape(a["status"])})</small>'
    if a.get("in_stock") is None:
        return ""
    # 0.3.30/re17: every stock claim shows its check time and its expiry (checked_at + 8 h); stale_js flips it after that
    from core.gpu_availability import et_hm
    t, exp = a.get("checked_at"), a.get("availability_expires_at") or ""
    word, cls = ("available", "av") if a["in_stock"] else ("out of stock", "oos")
    tail = f"; valid until {et_hm(exp)}; after that treat as unknown" if exp else ""
    return (f' <small class="{cls}" data-av-checked="{html.escape(t or "")}" data-av-expires="{html.escape(exp)}">({word} when checked at '
            f'{html.escape(_et(t))}{html.escape(tail)})</small>')


def _et(ts: str | None) -> str:
    if not ts:
        return "n/a"
    d = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET)
    return d.strftime("%Y-%m-%d %H:%M ET")


def page(g, feed: dict, slug: str, hours: int) -> str:
    esc, base = html.escape, g.BASE
    fam = GPUS[slug]
    allg = eligible(feed, fam)
    vendors_ok = lambda rows: len({r["advertiser"] for r in rows if not oos(r)}) >= 2
    groups = {k: v for k, v in allg.items() if vendors_ok(v)}
    single = {k: v for k, v in allg.items() if not vendors_ok(v)}
    title = f"Cost to rent {fam} for {hours} hours (1 GPU)"
    canon = f"{base}/cost/{slug}-{hours}-hours/"
    parts = [f"<h1>{esc(title)}</h1>",
             f"<p>Compute cost of {hours} GPU-hours on one {esc(fam)}, from each vendor's published on-demand rate, "
             f"among tracked providers. {esc(LABEL.format(h=hours))}</p>"]
    faq = []
    live_all = [((gpu, vram), r) for (gpu, vram), rows in allg.items() for r in rows if not oos(r)]
    if live_all:
        best = min(r["hourly_equiv_usd"] for _, r in live_all)
        by_label: dict[str, list[str]] = {}
        for (gpu, vram), r in live_all:
            if r["hourly_equiv_usd"] == best:
                lab = f"{gpu} {vram}GB" + ("" if fam in ("L40S", "RTX 4090") or re.search(r"SXM|PCIe|NVLink", gpu) else " (variant not stated)")
                by_label.setdefault(lab, []).append(r["advertiser"])
        names = " and ".join((f"{v[0]} {lab}" if len(v := sorted(set(vs))) == 1 else " and ".join(v) + f" (tie) {lab}")
                             for lab, vs in sorted(by_label.items()))
        amts = " / ".join(f"${best * h:,.2f}" for h in HOURS)
        hrs = " / ".join(str(h) for h in HOURS)
        if fam == "RTX 4090":  # I1 wording (single variant)
            line = f"Lowest on-demand {fam} on this page (not marked out of stock): {names} at {amts} ({hrs} h)"
        else:
            line = f"Lowest on-demand {fam} on this page (not marked out of stock): {names} at {amts} ({hrs} h) - variants differ, see tables."
        parts.append(f"<p class=\"pagelow\">{esc(line)}</p>")
        big = [((gpu, vram), r) for (gpu, vram), r in live_all if vram == 80] if fam == "A100" else []
        if big and any(v != 80 for (_, v), _ in live_all):  # K2: cheapest 80GB across every variant (SXM, PCIe, unlabelled)
            b80 = min(r["hourly_equiv_usd"] for _, r in big)
            n80 = " and ".join(sorted({f"{r['advertiser']} {gpu} 80GB" for (gpu, _), r in big if r["hourly_equiv_usd"] == b80}))
            n80 += " (tie)" if len({r["advertiser"] for _, r in big if r["hourly_equiv_usd"] == b80}) > 1 else ""
            parts.append(f"<p class=\"pagelow80\">{esc(f'Cheapest {fam} 80GB (any variant) among tracked providers: {n80} at ' + ' / '.join(f'${b80 * h:,.2f}' for h in HOURS))}</p>")
    if not groups:
        parts.append("<p>No variant of this GPU has two or more eligible vendors today, so no comparison is shown.</p>")
    for (gpu, vram), rows in sorted(groups.items(), key=lambda kv: -len({r['advertiser'] for r in kv[1]})):
        subs = [round(r["hourly_equiv_usd"] * hours, 2) for r in rows]
        live = [s for r, s in zip(rows, subs) if not oos(r)]
        nv = len({r["advertiser"] for r in rows if not oos(r)})
        n_oos = len(rows) - len(live)
        lo, md, hi = min(live), statistics.median(live), max(live)
        head = f"{gpu} {vram}GB" if vram else gpu
        spread = (f"Lowest ${lo:,.2f}, median ${md:,.2f}, highest ${hi:,.2f} across {len(live)} rates from {nv} vendors "
                  f"(spread ${hi - lo:,.2f})." + (f" {n_oos} out-of-stock rate{'s' if n_oos > 1 else ''} excluded and listed last." if n_oos else ""))
        if nv >= 3:
            tied = sorted({r["advertiser"] for r, s in zip(rows, subs) if s == lo and not oos(r)})
            who = tied[0] if len(tied) == 1 else " and ".join(tied) + " (tie)"
            spread = f"Cheapest {head} among tracked providers: {who} at ${lo:,.2f}. " + spread
            faq.append((f"How much does it cost to rent an {head} for {hours} hours?",
                        f"{spread} {LABEL.format(h=hours)}"))
        else:
            spread += (f" No 'cheapest' line: {nv} vendors not marked out of stock publish a comparable on-demand rate, and we "
                       "name a cheapest only with 3 or more (marketplace, community, interruptible and monthly rows are not comparable).")
        trs = "".join(
            f"<tr><td data-label=\"Vendor\">{esc(r['advertiser'])}{esc(_tax_note(r))}{_oos_label(r)}</td><td data-label=\"Tier\">{esc(r.get('tier') or '')}</td>"
            f"<td data-label=\"$/GPU-hr\">${r['hourly_equiv_usd']:g}</td><td data-label=\"{hours} h subtotal\"><strong>${s:,.2f}</strong></td>"
            f"<td data-label=\"Verified\">{esc(_et(r.get('verified_at')))}</td>"
            f"<td data-label=\"Source\"><a rel=\"nofollow noopener\" href=\"{esc(r['source_url'])}\">vendor page</a></td>"
            f"<td data-label=\"Link\">{'Referral link' if r.get('affiliate') else 'Direct link'}</td></tr>"
            for r, s in zip(rows, subs))
        parts.append(f"<h2>{esc(head)}</h2><p>{esc(spread)}</p><div class=\"tscroll\"><table class=\"howto sticky1\"><thead><tr>"
                     f"<th>Vendor</th><th>Tier</th><th>$/GPU-hr</th><th>{hours} h subtotal</th><th>Verified</th><th>Source</th><th>Link</th>"
                     f"</tr></thead><tbody>{trs}</tbody></table></div>")
    if single:
        items = "".join(
            f"<li>{esc(r['advertiser'])} {esc(gpu)} {vram}GB ({esc(r.get('tier') or '')}): ${r['hourly_equiv_usd']:g}/GPU-hr, "
            f"${r['hourly_equiv_usd'] * hours:,.2f} for {hours} h{esc(_tax_note(r))}{_oos_label(r)}</li>"
            for (gpu, vram), r in sorted(((k, r) for k, rows in single.items() for r in rows),
                                         key=lambda kr: (oos(kr[1]), kr[0][0], kr[0][1], kr[1]["hourly_equiv_usd"], kr[1]["advertiser"])))
        parts.append("<h2>Other variants (not compared)</h2><p>Listed but not ranked: no second vendor offers this exact variant in stock "
                     "(form factor and memory); variants are never mixed; rows marked out of stock come last.</p>"
                     f"<ul>{items}</ul>")
    other = " · ".join(f'<a href="{base}/cost/{slug}-{h}-hours/">{h} h</a>' for h in HOURS if h != hours)
    parts.append(
        "<h2>What's not included</h2><p>Storage, egress, vCPU/RAM add-ons, region and tax. Availability is an automated check at the time shown: "
        "rows marked out of stock when checked are listed last and left out of lowest, median and cheapest; other rows are "
        "not an availability claim. Multi-GPU and 8-GPU-only offers are left out: multi-GPU quotes need whole-instance pricing, coming later. "
        "Spot, community, marketplace, serverless, reserved and held or thin prices are never shown here.</p>"
        f"<p>Other durations: {other}. Full price list: <a href=\"{base}/gpu/{slug}-rental-price/\">{esc(fam)} rental prices</a>. "
        f"For your own hours or throughput, use the MCP tool <code>estimate_job_cost</code>.</p>"
        "<p class=\"meta\">Order is by cost only; referral links are labelled and never change the order. "
        f"Feed updated {esc(_et(feed.get('feed_updated_at')))}. Data CC BY 4.0, Lantern Works "
        f"(<a href=\"{base}/api/v1/gpu-prices.json\">gpu-prices.json</a>).</p>")
    body = "\n".join(parts)
    if faq:
        ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}
        body += f'\n<script type="application/ld+json">{json.dumps(ld)}</script>'
    return g.page_shell(title, f"{fam} cost for {hours} GPU-hours across tracked providers, from published on-demand rates.",
                        canon, body + "\n")


def write_all(g) -> list[str]:
    root = Path(g.ROOT)
    feed = json.loads((root / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    if not str(feed.get("schema", "")).startswith("lantern-works-gpu-prices/"):
        raise SystemExit("cost_pages: unexpected gpu feed schema")
    paths = []
    for slug in GPUS:
        for h in HOURS:
            p = f"cost/{slug}-{h}-hours"
            (root / p).mkdir(parents=True, exist_ok=True)
            (root / p / "index.html").write_text(page(g, feed, slug, h), encoding="utf-8")
            paths.append(p)
    rows = "".join(f"<li>{esc_(GPUS[slug])}: " + " · ".join(f'<a href="{g.BASE}/cost/{slug}-{h}-hours/">{h} hours</a>' for h in HOURS)
                   + "</li>" for slug in GPUS)
    body = ("<h1>GPU rental cost for a fixed number of hours</h1><p>Compute subtotal for 10, 100 or 730 GPU-hours on one GPU, "
            "from published on-demand rates among tracked providers, recomputed from the daily feed. Out-of-stock rows rank last "
            "and are excluded from lowest, median and cheapest.</p>" f"<ul>{rows}</ul>"
            f'<p>Full price lists: <a href="{g.BASE}/gpu/">GPU prices</a>.</p>\n')
    (root / "cost").mkdir(exist_ok=True)
    (root / "cost" / "index.html").write_text(g.page_shell("GPU rental cost by hours", "Cost of 10, 100 or 730 GPU-hours on H100, A100, L40S and RTX 4090 across tracked providers.",
                                                           f"{g.BASE}/cost/", body), encoding="utf-8")
    paths.append("cost")
    return paths
