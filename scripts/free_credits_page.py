"""/gpu/free-credits/ (T33): startup and research compute credit programs. Every amount is quoted from the
program's official page, with that page's URL and the date it was checked. No referral links on this page."""
from __future__ import annotations

import html
from pathlib import Path

PATH = "gpu/free-credits"
CHECKED = "2026-10-29"
# (program, official URL, what the official page says, who it's for). Re-check the page before changing a figure.
PROGRAMS = [
    ("AWS Activate", "https://aws.amazon.com/startups/credits/",
     "Up to $200,000 in AWS Activate credits (Portfolio tier). Self-funded founders: start with $1,000, up to $5,000 for select participants.",
     "Startups; the Portfolio tier needs an Organization ID from an Activate Provider (VC or accelerator)."),
    ("Google for Startups Cloud Program", "https://cloud.google.com/startup",
     "Up to $350,000 in Google Cloud credits. Start tier: $2,000; funded tiers (Scale, Scale AI): $200,000 to $350,000.",
     "Early-stage startups; the tier depends on funding stage."),
    ("Microsoft for Startups", "https://www.microsoft.com/en-us/startups",
     "Up to $150,000 in credits.", "Startups; eligibility per Microsoft's program terms."),
    ("Cloudflare for Startups", "https://www.cloudflare.com/startups/",
     "Up to $350,000 in credits for a year. Entry tier: $10,000, no minimum funding (bootstrapped or under $1M raised).",
     "Startups; the tier depends on funding."),
    ("Modal for Startups", "https://modal.com/startups",
     "Startup credit grants by tier (VC-backed via Modal's partner funds, or more than $1M raised); every account also gets $30/month of free compute.",
     "VC-backed startups for grants; the free monthly compute is for all accounts."),
    ("RunPod Startup Program", "https://www.runpod.io/startup-program",
     "Starter tier: $1,000 in credits. Growth tier: $25,000 in bonus credits when you commit $50,000 upfront (not free).",
     "Startups; the Growth tier is for venture-backed teams."),
    ("Lambda Research Grant", "https://lambda.ai/research",
     "Up to $5,000 in Lambda cloud credits for qualifying researchers.", "Academic and research projects."),
    ("DigitalOcean Hatch (Startups)", "https://www.digitalocean.com/startups",
     "Credits for 12 months (amount varies by program).", "Startups that have raised $10M or less."),
]


def write(g) -> str:
    esc, base = html.escape, g.BASE
    rows = "".join(
        f'<tr><td><a href="{esc(u)}" rel="noopener">{esc(n)}</a></td><td>{esc(w)}</td><td>{esc(who)}</td>'
        f'<td><a href="{esc(u)}" rel="noopener">source</a>, checked {CHECKED}</td></tr>'
        for n, u, w, who in PROGRAMS)
    body = f"""  <h1>Free GPU and cloud compute credits</h1>
  <p>Credit programs from cloud and GPU providers for startups and researchers. Each amount is quoted from the program's official page, checked on {CHECKED}. Amounts are "up to" figures and approval is at the provider's discretion. Terms change, so confirm on the linked page before applying.</p>
  <div style="overflow-x:auto"><table><thead><tr><th>Program</th><th>What's offered (per the official page)</th><th>Who it's for</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></div>
  <p class="meta">Links on this page go straight to each provider's official program page; none are referral links. For pay-as-you-go GPU rates after credits run out, see the <a href="{base}/gpu/price-comparison/">GPU price comparison</a> (some links there are referral links, disclosed on that page).</p>
"""
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell("Free GPU and cloud compute credits for startups and researchers",
                                f"Startup and research credit programs from cloud and GPU providers, each amount quoted from the official page (checked {CHECKED}).",
                                f"{base}/{PATH}/", body), encoding="utf-8")
    return PATH
