"""Keyword comparison pages (Phase 2 SEO). Built only from verified feed fields.

Price cells come from the deal's public pricing_note / unit text, quoted from the
vendor page we checked. If neither carries a price, the cell gives the pricing model (never a guessed number).
No numbers are invented here; prose below makes no vendor price claims of its own.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from install_page import link_snippet as install_link_snippet

PRICE_RE = re.compile(r"\$\s?\d|¢|free|\bfree\b|credits?", re.I)


def price_text(d: dict) -> str | None:
    for key in ("pricing_note", "unit"):
        t = (d.get(key) or "").strip()
        if t and re.search(r"\$\s?\d|¢|₹|\bfree\b", t, re.I):
            return t
    return None


def price_coverage_note(known: int, total: int) -> str:
    """Generated from the rows on the page, so it can't go stale."""
    if known == total:
        return f"Published prices from vendor pages are shown for all {total} providers below."
    return (f"Published prices from vendor pages are shown for {known} of {total} providers below; for the other "
            f"{total - known}, the cell gives the vendor's pricing model instead of a number (we don't guess prices).")


def short(t: str, n: int = 260) -> str:
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0].rstrip(",;:(")
    return cut + " …"


def facts(d: dict) -> tuple[list[str], list[str]]:
    """Honest pros/cons derived only from feed fields."""
    t = " ".join(filter(None, [d.get("pricing_note"), d.get("unit"), d.get("agent_instructions")]))
    pros, cons = [], []
    pt = price_text(d)
    if d.get("offer_type") == "verified_discount":
        pros.append("Vendor-published discount: " + short(d.get("unit") or "see deal page", 120))
    if d.get("offer_type") == "listed_discount":
        cons.append("Listed discount not confirmed on the vendor page: " + short(d.get("unit") or "see deal page", 120))
    if d.get("offer_type") == "free_tier" or re.search(r"\bfree (plan|tier|credits?|trial|usage|basic|developer|compute|starter)\b|\bfree \$|\$0(?![.\d])|credits? free|free credit", t, re.I):
        pros.append("Free plan, trial or credits to test before paying")
    if re.search(r"no card|no credit card|no payment method", t, re.I):
        pros.append("No card required to start (per vendor page)")
    if re.search(r"pay-as-you-go|pay as you go|per hour|/hr|per cpu second|never expire", t, re.I):
        pros.append("Usage-based billing, so idle months cost little or nothing")
    if re.search(r"\bmcp\b", t, re.I):
        pros.append("Offers an MCP server or agent integration")
    if pt:
        pros.append("Pricing is published, so you can budget before signing up")
    else:
        cons.append("No verified public price in our records; you must check the vendor site")
    if re.search(r"non-commercial", t, re.I):
        cons.append("Free tier is for personal / non-commercial use")
    if re.search(r"\bapply\b|eligibility", t, re.I):
        cons.append("Requires an application; approval is not guaranteed")
    if re.search(r"card required", t, re.I):
        cons.append("Some plans or trials require a card")
    if re.search(r"one-time|first month|first \d+ months|for month one|first purchase|new (accounts|clients)", t, re.I):
        cons.append("Part of the offer is one-time or intro-only; check the ongoing price")
    if re.search(r"verify at checkout|confirm at checkout|not shown", t, re.I):
        cons.append("Some terms could not be confirmed on the public page; verify at checkout")
    if not cons:
        cons.append("Limits and overage rates vary by plan; read them before committing")
    return pros[:4], cons[:3]


PAGES = [
    {
        "slug": "cheapest-residential-proxies",
        "title": "Residential Proxies (2026): Cheapest Among Tracked Providers, Verified Prices & Deals",
        "h1": "Residential proxies compared: cheapest among tracked providers",
        "desc": "Residential proxy providers compared on published per-GB / per-IP pricing and live discounts. Prices shown only where verified on the vendor page; otherwise the pricing model is given.",
        "intro": "Residential proxies route requests through consumer IP addresses, which makes them harder to block than datacenter IPs and far more expensive. The table lists the providers in our feed, the price we actually saw on the vendor's own page, and any vendor-published discount. Where a vendor doesn't publish a price, the cell says so rather than guessing.",
        "ids": ["deal-9proxy-001", "deal-proxyrack-001", "deal-brightdata-resi-001", "deal-oxylabs-001", "deal-dataimpulse-001", "deal-geonode-001", "deal-infatica-001", "deal-proxyempire-001", "deal-shifter-001", "deal-ipfoxy-001", "deal-lightningproxies-001"],
        "choose": [
            "Compare on the same unit. Some providers bill per GB of traffic, some per IP, some per thread with unmetered bandwidth. A low per-IP price is not comparable with a per-GB price until you estimate your traffic.",
            "Check minimum purchase and expiry. The lowest entry price often comes with a small, short-lived package.",
            "Separate intro offers from the ongoing rate. A first-month or first-deposit discount helps once; the list price is what you will pay afterward.",
            "Test success rate on your actual targets with a small package before buying volume. A cheaper pool that fails more often costs more per successful request.",
            "Confirm the provider's sourcing and acceptable-use policy, and only scrape what you are allowed to collect.",
        ],
        "faq": [
            ("Which residential proxy is cheapest among tracked providers?", "Among the providers whose prices we could verify, the lowest published entry price in our feed is shown in the table. Many providers do not publish comparable prices, so the lowest-cost option for your workload depends on traffic volume and success rate; test before committing."),
            ("Why do some rows show a pricing model instead of a price?", "We only show a price we read on the vendor's own pricing page. If we could not confirm it, we describe the pricing model instead of copying a number from a third-party list."),
            ("Are residential proxies better than datacenter proxies?", "They are harder to block but usually cost much more. If your targets do not block datacenter IPs, datacenter proxies or a scraping API may be cheaper."),
            ("Do these links cost me more?", "No. Some links are affiliate links; that never changes the price you pay, and it does not change the order of this table."),
        ],
        "hubs": ["proxies", "scraping-unblock"],
    },
    {
        "slug": "best-rotating-proxies-for-web-scraping",
        "title": "Best Rotating Proxies for Web Scraping: Providers & Scraping APIs Compared",
        "h1": "Rotating proxies for web scraping compared",
        "desc": "Rotating proxy pools and scraping APIs with built-in rotation, compared on verified pricing, free tiers and trade-offs.",
        "intro": "A rotating proxy hands each request (or each session) a different IP, so a scraper is not blocked for hitting a site from one address. You can buy a rotating pool and manage retries yourself, or use a scraping API that rotates IPs, retries and renders JavaScript for you. This page covers both, using only the prices we verified.",
        "ids": ["deal-proxyrack-001", "deal-9proxy-001", "deal-brightdata-resi-001", "deal-oxylabs-001", "deal-proxyscrape-001", "deal-dataimpulse-001", "deal-ipfoxy-001", "deal-zenrows-free-001", "deal-scrapingbee-free-001", "deal-scraperapi-001", "deal-brightdata-api-free-001"],
        "choose": [
            "Decide pool vs API. A raw rotating pool is cheaper per GB but you handle retries, CAPTCHAs and rendering. A scraping API costs more per request but returns finished HTML.",
            "Check rotation controls: per-request rotation, sticky sessions and geo targeting matter for logged-in or multi-step flows.",
            "Use free credits to measure success rate on your real targets before buying.",
            "Watch concurrency limits on free and entry plans; they cap throughput more than the credit count does.",
            "Respect robots.txt, site terms and data-protection law.",
        ],
        "faq": [
            ("Should I use a rotating proxy or a scraping API?", "If you already have a scraper with retry logic and only need IPs, a rotating pool is usually cheaper. If you want rendered HTML without managing blocks, a scraping API saves engineering time."),
            ("Which options have a free tier?", "The table marks free plans and credits we verified on vendor pages, for example recurring monthly credits on some scraping APIs."),
            ("How is this list ordered?", "By customer value: vendor discounts first, then verified free tiers, then standard signups, alphabetically. Affiliate status is not a ranking factor."),
        ],
        "hubs": ["proxies", "scraping-unblock"],
    },
    {
        "slug": "cheap-gpu-rental",
        "title": "GPU Rental & GPU Cloud Deals (2026): Cheapest Among Tracked Providers, Verified Prices",
        "h1": "GPU rental and cloud deals: cheapest among tracked providers",
        "desc": "GPU clouds and dedicated GPU servers compared on verified hourly or monthly pricing, free credits and billing model. No price is guessed.",
        "intro": "For inference, fine-tuning or agent workloads that need a GPU, renting beats buying unless the card is busy most of the day. Prices vary by GPU model, region and billing model (per-second serverless, hourly on-demand, or monthly dedicated). The table quotes the prices we read on each vendor's page.",
        "ids": ["deal-thundercompute-001", "deal-99stack-001", "deal-modal-free-001", "deal-gigagpu-001", "deal-runpod-001", "deal-vastai-001", "deal-novita-001"],
        "choose": [
            "Pick the GPU by memory first: the model must fit in VRAM. Then compare price for that card, not across different cards.",
            "Match billing to usage. Bursty inference suits per-second serverless; long training runs suit hourly on-demand; always-on services may suit a monthly dedicated server.",
            "Include storage and egress in the estimate; some providers bill disk while an instance is stopped.",
            "Use free monthly credits to benchmark your actual job before committing.",
        ],
        "faq": [
            ("What is the cheapest GPU to rent among tracked providers?", "It depends on the card you need. The table lists each provider's verified per-hour or per-month prices; compare like-for-like GPU models."),
            ("Is serverless GPU cheaper than an hourly instance?", "For intermittent workloads usually yes, because you pay only while code runs. For a GPU busy most of the hour, an on-demand instance is typically cheaper."),
            ("Why do some providers show no number?", "Their prices change often or were not on the page we checked, so we do not publish a number we cannot verify."),
        ],
        "hubs": ["gpu-compute", "compute"],
        "gpu": True,
    },
    {
        "slug": "h100-rental-price-comparison",
        # Superseded by the verified-rate landing page; canonicalized there and dropped from the sitemap.
        "canonical_to": "gpu/cheapest-h100-rental",
        "title": "H100 Rental Price Comparison: Verified Per-Hour Prices",
        "h1": "H100 rental price comparison",
        "desc": "NVIDIA H100 rental prices per hour from vendor pages we verified, plus GPU clouds where the H100 price is not yet verified (pricing model shown, no number).",
        "intro": "The H100 is the common choice for large-model inference and fine-tuning. Hourly rental prices differ by form factor (SXM vs PCIe), bundled vCPU/RAM and billing model. Only providers whose H100 price we read on their own page show a number; the rest show their pricing model so you can check them yourself.",
        "ids": ["deal-thundercompute-001", "deal-99stack-001", "deal-runpod-001", "deal-vastai-001", "deal-modal-free-001"],
        "focus": r"H100",
        "choose": [
            "Confirm the variant: H100 SXM and PCIe differ in interconnect and price.",
            "Compare the whole instance: vCPU, system RAM and local disk bundled with the GPU change the effective price.",
            "Check availability, not just price. A low-priced H100 that is rarely in stock does not help a deadline.",
            "For short jobs, per-second billing can beat a lower hourly rate with a minimum charge.",
        ],
        "faq": [
            ("How much does it cost to rent an H100?", "The verified per-hour prices we found are in the table. Prices change frequently, so confirm on the vendor page before launching."),
            ("Is a marketplace cheaper than a GPU cloud?", "Marketplaces can be cheaper but host reliability varies. Managed clouds charge more for consistency. Marketplace H100 prices are shown only where we verified them."),
        ],
        "hubs": ["gpu-compute", "compute"],
        "gpu": True,
    },
    {
        "slug": "cheapest-cloud-vps-for-ai-agents",
        "title": "Cloud VPS & Hosting for AI Agents: Cheapest Among Tracked Providers, Verified Prices & Free Tiers",
        "h1": "Cloud VPS and hosting for AI agents: cheapest among tracked providers",
        "desc": "Low-cost VPS, managed hosting and free app platforms for running AI agents, compared on verified pricing and free-tier limits.",
        "intro": "Most agents need a small always-on process, a cron or webhook endpoint, and a database. A $5/month VPS gives full control; a platform free tier removes server work but adds limits. The table puts both side by side with the prices and limits we verified.",
        "ids": ["deal-99stack-001", "deal-softshellweb-001", "deal-xcloud-001", "deal-cloudflare-workers-free-001", "deal-render-free-001", "deal-railway-trial-001", "deal-fly-trial-001", "deal-vercel-hobby-001", "deal-codespaces-free-001"],
        "choose": [
            "Long-running agents (polling loops, websockets, browsers) need a VPS or container host; request/response agents fit serverless free tiers.",
            "Check whether the free tier sleeps on idle; a sleeping agent misses scheduled work.",
            "Check commercial-use terms: some hobby tiers forbid business use.",
            "Budget RAM first. Headless browsers and local models need far more memory than the lowest-priced VPS plan.",
        ],
        "faq": [
            ("What is the cheapest way to host an AI agent among tracked providers?", "For light request/response agents, a free serverless tier. For always-on agents, the lowest-priced verified VPS plans in the table start around the prices shown."),
            ("Can I run a headless browser on a $5 VPS?", "Often only one at a time, and memory is tight. A hosted browser API may be cheaper than a larger VPS."),
        ],
        "hubs": ["hosting", "compute"],
    },
    {
        "slug": "email-verification-api-comparison",
        "title": "Email Verification API Comparison: Pricing, Free Credits & Trade-offs",
        "h1": "Email verification APIs compared",
        "desc": "Email verification and list-cleaning APIs compared on verified per-credit pricing, free credits and billing model.",
        "intro": "Verification checks whether an address can receive mail before you send, which protects sender reputation and cuts bounces. Vendors sell pay-as-you-go credit packs or monthly plans. The table quotes the pricing we saw on each vendor's page.",
        "ids": ["deal-mailveri-001", "deal-sealch-001", "deal-mailfloss-001", "deal-emaillistverify-001", "deal-clearbounce-001", "deal-snovio-001", "deal-prospeo-001", "deal-leadmagic-001"],
        "choose": [
            "Estimate monthly volume. Occasional list cleans suit non-expiring credit packs; continuous signup validation suits a subscription with an API.",
            "Ask how catch-all and unknown results are billed; some vendors charge only for definitive results.",
            "Check integrations (your ESP, CRM, or an MCP server for agents) and API rate limits.",
            "Verification is list hygiene, not permission: you still need consent or a lawful basis to email.",
        ],
        "faq": [
            ("What is the cheapest email verification API among tracked providers?", "Compare the per-1,000 cost at your volume using the verified prices in the table; pack pricing usually falls with size."),
            ("Do verification credits expire?", "It varies. Where the vendor page says credits never expire, the table shows it."),
            ("Does verifying emails make cold email legal?", "No. Follow CAN-SPAM, GDPR and similar laws regardless of verification."),
        ],
        "hubs": ["email-apis"],
    },
    {
        "slug": "cold-email-deliverability-warmup-tools",
        "title": "Cold Email Deliverability & Inbox Warmup Tools Compared (2026)",
        "h1": "Cold email deliverability and inbox warmup tools",
        "desc": "Warmup, mailbox providers, placement testing and DMARC tools compared on verified pricing. Honest pros and cons; no guessed prices.",
        "intro": "Deliverability depends on authenticated domains (SPF, DKIM, DMARC), mailbox reputation, sending volume and content people want. Tools here cover parts of that: buying sending mailboxes, warming them, testing inbox placement and monitoring DMARC. None of them fixes unwanted email.",
        "ids": ["deal-mailreach-001", "deal-folderly-001", "deal-inboxkit-001", "deal-zapmail-001", "deal-premiuminboxes-001", "deal-relay-mailboxes-001", "deal-dmarcly-001", "deal-heyo-001", "deal-reachinbox-001", "deal-salesforge-001"],
        "choose": [
            "Fix authentication first: SPF, DKIM and a DMARC policy. A DMARC monitor shows what is failing.",
            "Price mailboxes per mailbox per month, including domain costs and any warmup add-on.",
            "Use placement tests to measure, not guess, before scaling volume.",
            "Keep volume per mailbox modest and honor opt-outs; warmup cannot rescue a list that complains.",
            "Comply with CAN-SPAM, GDPR and other anti-spam laws.",
        ],
        "faq": [
            ("Does inbox warmup work?", "Warmup can help a new mailbox build sending history, but reputation ultimately follows recipient engagement and complaint rates."),
            ("How much do cold email mailboxes cost?", "Verified per-mailbox prices are in the table; compare including domain and warmup add-ons."),
            ("Do I need DMARC?", "Major mailbox providers expect SPF, DKIM and DMARC for bulk senders; monitoring helps you reach an enforced policy safely."),
        ],
        "hubs": ["email-apis"],
    },
    {
        "slug": "transactional-email-api-pricing",
        "title": "Transactional Email API Pricing Compared: Free Tiers & Paid Plans",
        "h1": "Transactional email API pricing",
        "desc": "Transactional email APIs and SMTP relays compared on verified free-tier limits and paid pricing, including agent-ready inbox APIs.",
        "intro": "Transactional email covers receipts, password resets, alerts and agent notifications. The deciding factors are deliverability, free-tier volume, price per extra thousand emails and API ergonomics. The table shows the limits and prices we verified.",
        "ids": ["deal-postmark-free-001", "deal-resend-free-001", "deal-agentmail-free-001", "deal-sendpulse-001", "deal-mailkite-001", "deal-smtp2go-001", "deal-postmark-001"],
        "choose": [
            "Keep transactional and marketing mail on separate streams or domains so promotions do not hurt receipts.",
            "Check daily caps as well as monthly totals on free tiers.",
            "If an agent must receive replies, pick a service with inbound webhooks or real inboxes.",
            "Compare overage pricing at your expected volume, not just the entry plan.",
        ],
        "faq": [
            ("Which transactional email API has the biggest free tier?", "Compare the verified monthly limits in the table; also note daily caps."),
            ("Can I use these for newsletters?", "Most transactional services restrict bulk marketing. Use a marketing platform for newsletters."),
        ],
        "hubs": ["email-apis", "hosting"],
    },
    {
        "slug": "serp-api-comparison",
        "title": "SERP API Comparison: Search APIs for Agents, Free Tiers & Pricing",
        "h1": "SERP and search APIs compared",
        "desc": "Google SERP scrapers and AI search APIs compared on verified free tiers and per-request pricing.",
        "intro": "Agents need search results either as raw SERP data (titles, links, positions) or as AI-ready search with extracted content. SERP APIs suit rank tracking and SEO; AI search APIs suit retrieval for agents. Both are compared here using verified free-tier limits and prices.",
        "ids": ["deal-serpapi-free-001", "deal-tavily-free-001", "deal-exa-001", "deal-brightdata-api-free-001", "deal-apilayer-001", "deal-scrapingdog-001", "deal-serptool-001"],
        "choose": [
            "Need exact Google positions and features? Use a SERP API. Need relevant pages with content for an LLM? Use an AI search API.",
            "Count successful requests: some vendors bill only for successful searches.",
            "Check locale and device targeting if you track rankings.",
            "Free monthly credits are enough to prototype; compare per-1,000 cost at scale.",
        ],
        "faq": [
            ("What is the best SERP API for AI agents?", "If the agent needs page content, an AI search API returning extracted text saves a second fetch. For rank data, a SERP API is the better fit."),
            ("Are there free SERP APIs?", "Several have free monthly allowances; verified ones are marked in the table."),
        ],
        "hubs": ["serp-apis"],
    },
    {
        "slug": "screenshot-api-comparison",
        "title": "Screenshot API & Headless Browser API Comparison",
        "h1": "Screenshot APIs and headless browser APIs compared",
        "desc": "A dedicated screenshot API versus hosted headless browsers that can capture screenshots, compared on verified free tiers and pricing.",
        "intro": "For page screenshots or PDFs you can call a dedicated screenshot API (one request, one image) or drive a hosted headless browser and capture it yourself. The first is simpler; the second handles logins and multi-step flows. Only verified limits and prices are shown.",
        "ids": ["deal-pdfcrowd-001", "deal-browserless-free-001", "deal-browserbase-001", "deal-steel-001", "deal-hyperbrowser-001", "deal-kernel-001"],
        "choose": [
            "Single public URL to image or PDF: a screenshot API is fewer moving parts.",
            "Logged-in or multi-step pages: a hosted browser session you control.",
            "Check concurrency and session-hour limits on free tiers.",
            "Confirm ad/cookie-banner blocking and full-page capture if you need clean images.",
        ],
        "faq": [
            ("Is a screenshot API cheaper than a headless browser?", "For simple captures usually yes in engineering time; per-capture cost depends on volume, so compare the verified plans in the table."),
            ("Can these render JavaScript-heavy pages?", "Yes; all listed options use real browsers, but timeouts and wait conditions differ."),
        ],
        "hubs": ["scraping-unblock", "compute"],
    },
    {
        "slug": "ai-seo-writing-tools-comparison",
        "title": "AI SEO Writing Tools Comparison: Pricing & Honest Trade-offs",
        "h1": "AI SEO writing and optimization tools compared",
        "desc": "AI article writers, internal-linking and SEO audit tools compared on verified pricing with honest pros and cons.",
        "intro": "AI writing tools speed up drafts, but rankings still depend on original, accurate content and a sound site. This page compares writers alongside the internal-linking and audit tools that help an existing site, using verified prices.",
        "ids": ["deal-seowritingai-001", "deal-contentbot-001", "deal-linkwhisper-001", "deal-seobility-001"],
        "choose": [
            "Use AI drafts as a starting point; fact-check and add first-hand information before publishing.",
            "Compare price per article or per 1,000 words at your real volume.",
            "Fix technical issues (audits) and internal links before producing more content.",
            "Avoid mass-producing thin pages; search engines treat scaled low-value content as spam.",
        ],
        "faq": [
            ("Will AI-written content rank?", "Content can rank regardless of how it is produced if it is helpful and accurate; unedited bulk output usually does not."),
            ("What is the cheapest AI SEO writer among tracked providers?", "See the verified prices in the table and compare at your monthly volume."),
        ],
        "hubs": ["ai-agents", "seo"],
    },
    {
        "slug": "web-scraping-api-deals",
        "title": "Web Scraping API Deals: Free Credits, Discounts & Pricing Compared",
        "h1": "Web scraping API deals",
        "desc": "Scraping and crawling APIs for agents compared on verified free credits, discounts and pricing.",
        "intro": "Scraping APIs fetch pages through rotating proxies, solve blocks and often render JavaScript or return LLM-ready markdown. Many offer recurring free credits, which is enough for light agent use. The table shows verified offers first.",
        "ids": ["deal-firecrawl-001", "deal-apify-startups-001", "deal-firecrawl-free-001", "deal-zenrows-free-001", "deal-scrapingbee-free-001", "deal-apify-free-001", "deal-brightdata-api-free-001", "deal-jina-reader-free-001", "deal-scraperapi-001", "deal-browseract-001", "deal-scrapedo-001", "deal-scrapingant-001", "deal-supadata-001"],
        "choose": [
            "Markdown for an LLM vs raw HTML for a parser: pick the API whose output fits your pipeline.",
            "Credits are not equal: JavaScript rendering and premium proxies often cost several credits per request.",
            "Prefer recurring monthly free credits over one-time signup credits for ongoing light use.",
            "Respect site terms, robots.txt and data-protection law.",
        ],
        "faq": [
            ("Which scraping API has the best free tier?", "Compare the verified recurring monthly credits in the table and how many credits a rendered request costs."),
            ("Are there discount codes?", "Only vendor-published discounts are listed; we do not invent codes."),
        ],
        "hubs": ["scraping-unblock"],
    },
]

PILLAR = {
    "slug": "ai-agent-tool-deals",
    "title": "AI Agent Tool Deals (2026): Verified Free Tiers, Discounts & Comparisons",
    "h1": "AI agent tool deals",
    "desc": "Hub for verified deals on the tools AI agents use: proxies, scraping and search APIs, GPUs, hosting and email. Links to every comparison and category.",
}


def deal_link(base: str, slug_for, d: dict) -> str:
    return f'{base}/deals/{slug_for(d["id"])}/'


def _bc(base, items):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(items)
        ],
    }


def write_compare_pages(g, deals: list[dict]) -> list[str]:
    """g = generator module (BASE, ROOT, esc, page_shell, slug_for, sort_deals_customer_value)."""
    base, esc = g.BASE, g.esc
    by_id = {d["id"]: d for d in deals}
    out = []
    hub_titles = {h["slug"]: h["title"] for h in g.HUBS}
    for p in PAGES:
        rows = [by_id[i] for i in p["ids"] if i in by_id]
        assert len(rows) >= 4, (p["slug"], len(rows))
        rows = g.sort_deals_customer_value(rows)
        url = f"{base}/compare/{p['slug']}/"
        canon = f"{base}/{p['canonical_to']}/" if p.get("canonical_to") else url
        if p.get("canonical_to"):  # H7: superseded page is a pointer only (no stale table); GitHub Pages has no server redirects
            body = (f'  <meta http-equiv="refresh" content="0; url={canon}" />\n'
                    f'  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › {esc(p["h1"])}</nav>\n'
                    f'  <h1>This page has moved</h1>\n  <p>Verified per-hour {esc(p["h1"].split(" ")[0])} prices, sorted by cost, are at '
                    f'<a href="{canon}">{canon}</a>.</p>\n')
            o = g.ROOT / "compare" / p["slug"] / "index.html"
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_text(g.page_shell(f"Moved: {p['h1']} — Lantern Works", "This page moved to the verified-rate page.", canon, body,
                                      robots="noindex,follow"), encoding="utf-8")
            continue
        crumbs = [("Home", f"{base}/"), ("AI agent tool deals", f"{base}/{PILLAR['slug']}/"), (p["h1"], url)]
        tr = []
        ptm = {}
        pc = []
        for d in rows:
            pt = price_text(d)
            if pt and p.get("focus"):
                parts = [x.strip() for x in re.split(r"[;,]\s|\.\s", pt) if re.search(p["focus"], x)]
                pt = "; ".join(parts) or None
            ptm[d["id"]] = pt
            if not pt:
                from core.gpu import build_rates
                from core.price_label import price_label
                rates = [r for r in build_rates(deals)["rates"] if not p.get("focus") or r["gpu"].startswith("H100")]
                lab, kind = price_label(d, rates)
                if kind == "gpu":
                    ptm[d["id"]] = lab
                price = esc(lab) if kind != "plans" else esc(lab)
            else:
                price = esc(short(pt, 320)) + ("" if d.get("verified_at") else " <em>(not verified)</em>")
            free = "Yes" if (d.get("offer_type") == "free_tier" or (pt and re.search(r"\bfree (plan|tier|credits?|trial|usage|basic|developer)\b|\$0(?![.\d])|free credit|credits? free", pt, re.I))) else "Not listed"
            kind = "Vendor discount" if d["offer_type"] == "verified_discount" else "Listed discount (unverified)" if d["offer_type"] == "listed_discount" else ("Free tier" if d["offer_type"] == "free_tier" else ("Trial" if d["offer_type"] == "trial" else "Standard signup"))
            tr.append(
                f'<tr><td><a href="{deal_link(base, g.slug_for, d)}">{esc(d["advertiser"])}</a></td>'
                f"<td>{esc(kind)}</td><td>{price}</td><td>{free}</td></tr>"
            )
            pros, cons = facts(d)
            pc.append(
                f'<h3><a href="{deal_link(base, g.slug_for, d)}">{esc(d["advertiser"])}</a></h3>'
                f'<p><strong>Pros:</strong></p><ul>{"".join(f"<li>{esc(x)}</li>" for x in pros) or "<li>None verified beyond the listing</li>"}</ul>'
                f'<p><strong>Cons:</strong></p><ul>{"".join(f"<li>{esc(x)}</li>" for x in cons)}</ul>'
            )
        known = sum(1 for d in rows if ptm.get(d["id"]))
        faq = p["faq"]
        faq_ld = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq
            ],
        }
        related = " · ".join(
            f'<a href="{base}/{o.get("canonical_to") or "compare/" + o["slug"]}/">{esc(o["h1"])}</a>' for o in PAGES if o["slug"] != p["slug"]
        )
        hubs = " · ".join(f'<a href="{base}/categories/{h}/">{esc(hub_titles.get(h, h))}</a>' for h in p["hubs"])
        gpu_block = ""
        if p.get("gpu"):
            import gpu_pages
            from core.gpu import build_rates
            grs = [r for r in build_rates(deals)["rates"] if r["deal_id"] in p["ids"] and (not p.get("focus") or r["gpu"].startswith("H100"))]
            gpu_block = gpu_pages.accuracy_html(g, grs)
        body = f"""
  <nav aria-label="Breadcrumb" class="crumbs"><a href="{base}/">Home</a> › <a href="{base}/{PILLAR['slug']}/">AI agent tool deals</a> › {esc(p['h1'])}</nav>
  <main>
  <h1>{esc(p['h1'])}</h1>
  {f'<p class="callout"><strong>Updated page:</strong> verified per-hour H100 prices, sorted by cost, are now at <a href="{canon}">{canon}</a>.</p>' if p.get("canonical_to") else ""}
  <p>{p['intro']}</p>
  <p><small>{price_coverage_note(known, len(rows))} Always confirm at checkout. Order: vendor discounts, then free tiers, then standard signups, A–Z. Affiliate status does not affect order.</small></p>
  <h2>Comparison table</h2>
  <div style="overflow-x:auto"><table>
  <thead><tr><th>Provider</th><th>Offer</th><th>Published pricing</th><th>Free option</th></tr></thead>
  <tbody>
  {''.join(tr)}
  </tbody></table></div>
  <h2>Pros and cons</h2>
  <p><small>Derived only from facts on the vendor pages we checked.</small></p>
  {''.join(pc)}
{gpu_block}  <h2>How to choose</h2>
  <ul>{''.join(f'<li>{esc(x)}</li>' for x in p['choose'])}</ul>
  <h2>FAQ</h2>
  {''.join(f'<h3>{esc(q)}</h3><p>{esc(a)}</p>' for q, a in faq)}
  <h2>Related</h2>
  <p>Categories: {hubs}</p>
  <p>Other comparisons: {related}</p>
  <script type="application/ld+json">{json.dumps(faq_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(_bc(base, crumbs), ensure_ascii=False)}</script>
  </main>
"""
        path = g.ROOT / "compare" / p["slug"] / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(g.page_shell(p["title"], p["desc"], canon, body + install_link_snippet(g.BASE)), encoding="utf-8")
        if not p.get("canonical_to"):  # canonicalized pages stay reachable but leave the sitemap
            out.append(f"compare/{p['slug']}")

    # Pillar
    url = f"{base}/{PILLAR['slug']}/"
    groups = {
        "Proxies & scraping": ["cheapest-residential-proxies", "best-rotating-proxies-for-web-scraping", "web-scraping-api-deals", "screenshot-api-comparison"],
        "Search": ["serp-api-comparison"],
        "GPU & hosting": ["cheap-gpu-rental", "h100-rental-price-comparison", "cheapest-cloud-vps-for-ai-agents"],
        "Email": ["email-verification-api-comparison", "cold-email-deliverability-warmup-tools", "transactional-email-api-pricing"],
        "Content & SEO": ["ai-seo-writing-tools-comparison"],
    }
    pmap = {p["slug"]: p for p in PAGES}
    sec = []
    for gname, slugs in groups.items():
        items = "".join(
            f'<li><a href="{base}/{pmap[s].get("canonical_to") or "compare/" + s}/">{esc(pmap[s]["h1"])}</a> — {esc(pmap[s]["desc"])}</li>' for s in slugs
        )
        if gname == "GPU & hosting":
            import gpu_pages
            items += "".join(f'<li><a href="{base}/{p}/">{esc(n[0].upper() + n[1:])}</a> — verified rates, checked dates</li>'
                             for p, n in gpu_pages.page_links(deals))
        sec.append(f"<h2>{esc(gname)}</h2><ul>{items}</ul>")
    discounts = [d for d in g.sort_deals_customer_value(deals) if d["offer_type"] == "verified_discount" and d.get("verified_at")]
    frees = [d for d in g.sort_deals_customer_value(deals) if d["offer_type"] == "free_tier" and d.get("verified_at")]
    dl = "".join(f'<li><a href="{deal_link(base, g.slug_for, d)}">{esc(d["advertiser"])}</a>: {esc(short(d.get("unit") or "", 140))}</li>' for d in discounts)
    fl = "".join(f'<li><a href="{deal_link(base, g.slug_for, d)}">{esc(d["advertiser"])}</a>: {esc(short(d.get("unit") or "", 140))}</li>' for d in frees)
    hubs = " · ".join(f'<a href="{base}/categories/{h["slug"]}/">{esc(h["title"])}</a>' for h in g.HUBS)
    faq = [
        ("How are deals verified?", "Each listing links to the vendor page it was checked against and carries a verified-on date. Prices are quoted only when seen on the vendor's own page; otherwise the listing gives the pricing model, never a guessed number."),
        ("How are deals ranked?", "Vendor-published discounts first, then verified free tiers, then standard signups, alphabetically by vendor. Whether a link is an affiliate link does not affect ranking."),
        ("Can agents read this data directly?", "Yes. The full feed is available as JSON, with a query script and MCP spec described on the homepage."),
    ]
    faq_ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}
    body = f"""
  <nav aria-label="Breadcrumb" class="crumbs"><a href="{base}/">Home</a> › AI agent tool deals</nav>
  <main>
  <h1>{esc(PILLAR['h1'])}</h1>
  <p>Verified offers on the infrastructure AI agents rely on, with side-by-side comparisons. {len(deals)} deals in the feed: {len(discounts)} vendor discounts and {len(frees)} verified free tiers; the rest are standard signups. Prices appear only where we confirmed them on the vendor's page.</p>
  {''.join(sec)}
  <h2>Current vendor discounts</h2><ul>{dl}</ul>
  <h2>Verified free tiers</h2><ul>{fl}</ul>
  <h2>Browse by category</h2><p>{hubs}</p>
  <h2>FAQ</h2>
  {''.join(f'<h3>{esc(q)}</h3><p>{esc(a)}</p>' for q, a in faq)}
  <script type="application/ld+json">{json.dumps(faq_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(_bc(base, [("Home", f"{base}/"), ("AI agent tool deals", url)]), ensure_ascii=False)}</script>
  </main>
"""
    path = g.ROOT / PILLAR["slug"] / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(g.page_shell(PILLAR["title"], PILLAR["desc"], url, body + install_link_snippet(g.BASE)), encoding="utf-8")
    out.insert(0, PILLAR["slug"])
    return out


def nav_html(base: str) -> str:
    links = " · ".join(f'<a href="{base}/{p.get("canonical_to") or "compare/" + p["slug"]}/">{p["h1"]}</a>' for p in PAGES)
    return (
        f'<nav class="compare-nav" style="margin-top:.5rem;"><strong>Comparisons:</strong> '
        f'<a href="{base}/{PILLAR["slug"]}/">AI agent tool deals (overview)</a> · {links}</nav>'
    )
