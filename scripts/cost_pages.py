"""/cost/{gpu}-{hours}-hours/ (T24 part A, spec /workspace/pulse/specs/t24-workload-pages-ready.md): "Cost to rent
{GPU} for N hours" on 1 GPU, pure feed math (rate x hours x 1). Fail closed: on-demand, non-interruptible, non-serverless,
hourly/per-second billing, min_gpus == 1, vendor not held; reserved/thin/held/marketplace/monthly rows never appear.
Variants (exact gpu + vram) are never mixed; a variant needs >= 2 vendors, and "cheapest" needs >= 3.
Replace the math with T35 quote() when it ships; do not grow a second pricing engine here."""
from __future__ import annotations

import html
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

GPUS = {"h100": "H100", "a100": "A100", "l40s": "L40S", "rtx-4090": "RTX 4090"}
HOURS = (10, 100, 730)
ET = ZoneInfo("America/New_York")
LABEL = ("Compute subtotal only, excludes storage, egress, vCPU, tax. Among tracked providers. "
         "Not an availability claim. Assumes {h} h on 1 GPU.")


def eligible(feed: dict, family: str) -> dict[tuple, list[dict]]:
    held = {h.get("vendor") for h in feed.get("held_stale") or []}
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
    return {k: sorted(v, key=lambda r: (r["hourly_equiv_usd"], r["advertiser"])) for k, v in out.items()
            if len({r["advertiser"] for r in v}) >= 2}


def _et(ts: str | None) -> str:
    if not ts:
        return "n/a"
    d = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET)
    return d.strftime("%Y-%m-%d %H:%M ET")


def page(g, feed: dict, slug: str, hours: int) -> str:
    esc, base = html.escape, g.BASE
    fam = GPUS[slug]
    groups = eligible(feed, fam)
    title = f"Cost to rent {fam} for {hours} hours (1 GPU)"
    canon = f"{base}/cost/{slug}-{hours}-hours/"
    parts = [f"<h1>{esc(title)}</h1>",
             f"<p>Compute cost of {hours} GPU-hours on one {esc(fam)}, from each vendor's published on-demand rate, "
             f"among tracked providers. {esc(LABEL.format(h=hours))}</p>"]
    faq = []
    if not groups:
        parts.append("<p>No variant of this GPU has two or more eligible vendors today, so no comparison is shown.</p>")
    for (gpu, vram), rows in sorted(groups.items(), key=lambda kv: -len({r['advertiser'] for r in kv[1]})):
        subs = [round(r["hourly_equiv_usd"] * hours, 2) for r in rows]
        nv = len({r["advertiser"] for r in rows})
        lo, md, hi = min(subs), statistics.median(subs), max(subs)
        head = f"{gpu} {vram}GB" if vram else gpu
        spread = (f"Lowest ${lo:,.2f}, median ${md:,.2f}, highest ${hi:,.2f} across {len(rows)} rates from {nv} vendors "
                  f"(spread ${hi - lo:,.2f}).")
        if nv >= 3:
            tied = sorted({r["advertiser"] for r, s in zip(rows, subs) if s == lo})
            who = tied[0] if len(tied) == 1 else " and ".join(tied) + " (tie)"
            spread = f"Cheapest among tracked providers: {who} at ${lo:,.2f}. " + spread
            faq.append((f"How much does it cost to rent an {head} for {hours} hours?",
                        f"{spread} {LABEL.format(h=hours)}"))
        trs = "".join(
            f"<tr><td data-label=\"Vendor\">{esc(r['advertiser'])}</td><td data-label=\"Tier\">{esc(r.get('tier') or '')}</td>"
            f"<td data-label=\"$/GPU-hr\">${r['hourly_equiv_usd']:g}</td><td data-label=\"{hours} h subtotal\"><strong>${s:,.2f}</strong></td>"
            f"<td data-label=\"Verified\">{esc(_et(r.get('verified_at')))}</td>"
            f"<td data-label=\"Source\"><a rel=\"nofollow noopener\" href=\"{esc(r['source_url'])}\">vendor page</a></td>"
            f"<td data-label=\"Link\">{'Referral link' if r.get('affiliate') else 'Direct link'}</td></tr>"
            for r, s in zip(rows, subs))
        parts.append(f"<h2>{esc(head)}</h2><p>{esc(spread)}</p><div class=\"tscroll\"><table class=\"howto sticky1\"><thead><tr>"
                     f"<th>Vendor</th><th>Tier</th><th>$/GPU-hr</th><th>{hours} h subtotal</th><th>Verified</th><th>Source</th><th>Link</th>"
                     f"</tr></thead><tbody>{trs}</tbody></table></div>")
    other = " · ".join(f'<a href="{base}/cost/{slug}-{h}-hours/">{h} h</a>' for h in HOURS if h != hours)
    parts.append(
        "<h2>What's not included</h2><p>Storage, egress, vCPU/RAM add-ons, region, tax and availability (stock is not checked "
        "here). Multi-GPU and 8-GPU-only offers are left out: multi-GPU quotes need whole-instance pricing, coming later. "
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
    return paths
