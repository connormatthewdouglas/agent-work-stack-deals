#!/usr/bin/env python3
"""Generate per-deal pages, category hubs, stack guides, changelog, sitemap, and refresh index.html from deals.json."""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEALS_PATH = ROOT / "deals.json"
GOTCHAS_PATH = ROOT / "data" / "deal_gotchas.json"
BASE = "https://connormatthewdouglas.github.io/agent-work-stack-deals"
LASTMOD = "2026-10-23"
VERIFIED = "2026-10-23"
SITE_NAME = "Lantern Works"
# No dedicated OG share image in the repo — omit og:image / twitter:image.

CSS = """
    :root { font-family: system-ui, sans-serif; color: #111; background: #fafafa; }
    body { max-width: 52rem; margin: 0 auto; padding: 1.25rem; line-height: 1.45; }
    h1 { font-size: 1.6rem; margin: 0 0 .5rem; }
    h2 { font-size: 1.25rem; margin: 1.5rem 0 .6rem; }
    .feed { background: #111; color: #eee; padding: .75rem 1rem; border-radius: 8px; font-size: .9rem; overflow-wrap: anywhere; }
    .feed a { color: #9cf; }
    .deal { background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 1rem; margin: .75rem 0; }
    .deal h2, .deal h1 { font-size: 1.1rem; margin: 0 0 .35rem; }
    .tag, .badge { display: inline-block; background: #eee; border-radius: 999px; padding: .1rem .5rem; font-size: .75rem; margin-right: .25rem; }
    .badge.agent { background: #e8f5e9; }
    .badge { background: #fff3cd; }
    .badge.public { background: #e3f2fd; color: #0d47a1; }
    .badge.affiliate { background: #e8f5e9; }
    .badge.example { background: #fce4ec; }
    .badge.fresh-new { background: #dcfce7; color: #14532d; }
    .badge.fresh-updated { background: #ede9fe; color: #4c1d95; }
    .freshness { font-size: .85rem; color: #555; }
    .changelog h2 { font-size: 1.15rem; margin: 1.4rem 0 .4rem; }
    .changelog ul { margin: .25rem 0 .75rem; padding-left: 1.2rem; }
    .changelog li { margin: .2rem 0; }
    .section-title { margin-top: 2rem; font-size: 1.25rem; }
    footer { margin-top: 2rem; color: #666; font-size: .85rem; }
    code { background: #f0f0f0; padding: .1rem .3rem; border-radius: 4px; }
    nav a { margin-right: .5rem; }
    .crumbs { font-size: .9rem; color: #555; margin-bottom: 1rem; }
    .meta { color: #333; }
    .verified { font-size: .85rem; color: #555; }
    a.cta { display: inline-block; margin-top: .5rem; font-weight: 600; }
    .howto { background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 1rem 1.1rem; margin: 1rem 0 1.5rem; }
    .howto pre { background: #111; color: #eee; padding: .75rem 1rem; border-radius: 8px; overflow-x: auto; font-size: .82rem; }
    .howto table { width: 100%; border-collapse: collapse; font-size: .9rem; margin: .5rem 0 1rem; }
    .howto th, .howto td { border: 1px solid #ddd; padding: .35rem .5rem; text-align: left; vertical-align: top; }
    .howto th { background: #f3f3f3; }
    .gotchas { background: #fff8e6; border: 1px solid #f0d78c; border-radius: 10px; padding: .85rem 1rem; margin: 1rem 0 1.25rem; }
    .gotchas h2 { font-size: 1.05rem; margin: 0 0 .45rem; }
    .gotchas ul { margin: .25rem 0 0; padding-left: 1.2rem; }
    .gotchas li { margin: .3rem 0; }
    .gotchas a { font-weight: 600; }
  """

CATEGORY_ORDER = ["compute", "email", "hosting", "proxies", "search", "seo", "templates", "unblock"]

CATEGORY_HUB_SLUG = {"email": "email-apis"}


def hub_slug(cat):
    return CATEGORY_HUB_SLUG.get(cat, cat)


HUBS = [
    {
        "slug": "scraping-unblock",
        "title": "Scraping & unblock deals",
        "description": "Agent-oriented scrape, unblock, and anti-bot API offers — affiliate and public free tiers.",
        "match": lambda d: d.get("category") == "unblock"
        or any(t in (d.get("tags") or []) for t in ("scrape", "unblock", "scraping", "actors")),
    },
    {
        "slug": "proxies",
        "title": "Proxy deals for agents",
        "description": "Residential and datacenter proxy offers agents use for unblock and scraping workloads.",
        "match": lambda d: any(t in (d.get("tags") or []) for t in ("proxy", "residential", "proxies")),
    },
    {
        "slug": "serp-apis",
        "title": "SERP & search API deals",
        "description": "Search and SERP API free tiers and affiliate offers for research agents.",
        "match": lambda d: d.get("category") == "search"
        or any(t in (d.get("tags") or []) for t in ("serp", "search", "crawl", "rag")),
    },
    {
        "slug": "gpu-compute",
        "title": "GPU & compute deals",
        "description": "GPU, browser sandboxes, and compute credits for agent runtimes.",
        "match": lambda d: d.get("category") == "compute"
        or any(t in (d.get("tags") or []) for t in ("gpu", "compute", "inference", "browser")),
    },
    {
        "slug": "email-apis",
        "title": "Email API deals",
        "description": "Transactional and agent inbox email APIs — free tiers and startup programs.",
        "match": lambda d: any(
            t in (d.get("tags") or []) for t in ("email", "agentmail", "resend", "smtp", "transactional", "postmark")
        ),
    },
    {
        "slug": "compute",
        "title": "Compute category hub",
        "description": "All compute-category deals on the Lantern Works agent deals board.",
        "match": lambda d: d.get("category") == "compute",
    },
    {
        "slug": "hosting",
        "title": "Hosting category hub",
        "description": "Hosting, PaaS, databases, and related free tiers for agent workers.",
        "match": lambda d: d.get("category") == "hosting",
    },
    {
        "slug": "search",
        "title": "Search category hub",
        "description": "Search and crawl API deals for agent research stacks.",
        "match": lambda d: d.get("category") == "search",
    },
    {
        "slug": "seo",
        "title": "SEO tool deals",
        "description": "SEO audit, rank tracking, and site-health tool offers for agent and human marketing stacks.",
        "match": lambda d: d.get("category") == "seo",
    },
    {
        "slug": "templates",
        "title": "Templates category hub",
        "description": "Template and ops-kit offers for agent workflows.",
        "match": lambda d: d.get("category") == "templates",
    },
    {
        "slug": "unblock",
        "title": "Unblock category hub",
        "description": "Unblock, scrape, and proxy category deals.",
        "match": lambda d: d.get("category") == "unblock",
    },
]

# Curated Best-for-X stack guides (not a coupon dump). Picks reference deals.json ids;
# redeem URLs always come from the live deal record at generate time.
GUIDES = [
    {
        "slug": "agent-scrape-unblock",
        "title": "Best agent scrape & unblock stack",
        "description": (
            "A short Lantern Works stack guide: scrape/unblock APIs plus a proxy layer "
            "agents actually use — curated picks with authorized redeem links."
        ),
        "intro": (
            "Agents that fetch the live web need a scrape or unblock API and, often, a "
            "proxy layer. This guide is a short curated stack from the Lantern Works "
            "agent work-stack directory — not a coupon dump. Each pick links to its deal "
            "page; redeem only through that deal’s authorized URL."
        ),
        "picks": [
            {
                "id": "deal-scrapedo-001",
                "why": "Simple scrape/unblock API with strong agent-friendly docs — a solid default when you need JS rendering and anti-bot handling without assembling proxies yourself.",
            },
            {
                "id": "deal-scrapingdog-001",
                "why": "Budget-friendly scrape/unblock API that covers SERP and general page fetch — useful when agents need many cheap requests with a single integration.",
            },
            {
                "id": "deal-scrapeops-001",
                "why": "Proxy routing and scrape ops tooling that helps agents fail over across providers instead of hard-coding one unblock endpoint.",
            },
            {
                "id": "deal-scrapingant-001",
                "why": "Browser-backed scraping API for pages that need a real rendering stack — good when headless fetch alone is not enough.",
            },
            {
                "id": "deal-proxyscrape-001",
                "why": "Proxy layer with a lanternworks referral — pair with a scrape API when you want to bring your own IPs or rotate residential/datacenter pools.",
            },
        ],
    },
    {
        "slug": "cheap-gpu-week",
        "title": "Cheap GPU week for agents",
        "description": (
            "A short Lantern Works stack guide to affordable GPU and inference for agent "
            "runtimes — curated affiliate picks plus one labeled free-tier option."
        ),
        "intro": (
            "When an agent needs a burst of GPU for fine-tunes, inference, or sandboxed "
            "jobs, spot and marketplace GPUs beat always-on cloud. Here are a few curated "
            "compute picks from the Lantern Works directory. Affiliate links are authorized; "
            "the free-tier option is labeled and non-affiliate."
        ),
        "picks": [
            {
                "id": "deal-runpod-001",
                "why": "On-demand and serverless GPU pods with a referral credit path — fast to spin up for agent workers that need a known GPU SKU for a few hours or days.",
            },
            {
                "id": "deal-vastai-001",
                "why": "Marketplace pricing on community and datacenter GPUs — often the cheapest week when you can tolerate variable hosts and shop by $/hr.",
            },
            {
                "id": "deal-novita-001",
                "why": "GPU inference API for agents that want a hosted model endpoint instead of managing a raw GPU instance.",
            },
            {
                "id": "deal-modal-free-001",
                "why": "Public Starter free compute credit (non-affiliate) — useful for prototyping agent jobs before you move heavier workloads to paid GPU providers.",
                "label": "free / public · non-affiliate",
            },
        ],
    },
    {
        "slug": "agent-email-outreach",
        "title": "Best agent email & outreach stack",
        "description": (
            "A short Lantern Works stack guide for agent email: find/verify, transactional "
            "send, and optional free inboxes — curated picks with authorized redeem links."
        ),
        "intro": (
            "Outbound and transactional email for agents usually needs find/verify plus a "
            "reliable send API (and sometimes a dedicated agent inbox). This curated stack "
            "from the Lantern Works directory keeps affiliate redeem links authorized and "
            "calls out free/public tiers when they help agents start without a card."
        ),
        "picks": [
            {
                "id": "deal-snovio-001",
                "why": "Email finder, verifier, and outreach in one stack — practical when an agent needs leads plus deliverability checks before send.",
            },
            {
                "id": "deal-clearbounce-001",
                "why": "Email verification API to keep agent lists clean — reduces bounces before you burn transactional quota.",
            },
            {
                "id": "deal-postmark-001",
                "why": "Transactional email API with strong deliverability — a solid send layer for agent receipts, alerts, and sequenced outreach.",
            },
            {
                "id": "deal-smtp2go-001",
                "why": "SMTP/API send with straightforward agent integration — good backup or primary transactional path alongside Postmark.",
            },
            {
                "id": "deal-agentmail-free-001",
                "why": "Free agent inbox tier (non-affiliate) — useful when the agent itself needs inbound mailboxes rather than only outbound SMTP.",
                "label": "free / public · non-affiliate",
            },
        ],
    },
]



def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def slug_for(deal_id: str) -> str:
    s = deal_id.strip()
    if s.startswith("deal-"):
        s = s[5:]
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", s).strip("-").lower()
    return s or deal_id


def is_example(deal: dict) -> bool:
    if deal.get("example"):
        return True
    for u in (deal.get("redeem_url") or "", deal.get("source_url") or ""):
        if "example.com" in u:
            return True
    return False


def sort_deals_affiliates_first(deals: list[dict]) -> list[dict]:
    """Affiliate==true first, then public/non-affiliate; stable within each group."""
    indexed = list(enumerate(deals))
    indexed.sort(key=lambda iv: (0 if iv[1].get("affiliate") is True else 1, iv[0]))
    return [d for _, d in indexed]



def load_curated_gotchas() -> dict[str, list[str]]:
    """Load durable curated notes from data/deal_gotchas.json (keyed by deal id)."""
    if not GOTCHAS_PATH.exists():
        return {}
    raw = json.loads(GOTCHAS_PATH.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if isinstance(v, list):
            out[k] = [str(x).strip() for x in v if str(x).strip()]
        elif isinstance(v, str) and v.strip():
            out[k] = [v.strip()]
    return out


def brand_key(deal: dict) -> str:
    adv = (deal.get("advertiser") or "").strip().lower()
    if adv:
        return adv
    title = deal.get("title") or ""
    return title.split("—")[0].strip().lower()


def is_free_tierish(deal: dict) -> bool:
    if deal.get("affiliate") is True:
        return False
    tags = [str(t).lower() for t in (deal.get("tags") or [])]
    if any(t in tags for t in ("free-tier", "non-affiliate", "public")):
        return True
    unit = (deal.get("unit") or "").lower()
    return "free" in unit


def build_twin_index(deals: list[dict]) -> dict[str, list[dict]]:
    """Map deal id -> sibling free/affiliate deals sharing the same advertiser/brand."""
    by_brand: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"aff": [], "free": []})
    for d in deals:
        if is_example(d):
            continue
        key = brand_key(d)
        if not key:
            continue
        if d.get("affiliate") is True:
            by_brand[key]["aff"].append(d)
        elif is_free_tierish(d):
            by_brand[key]["free"].append(d)
    twins: dict[str, list[dict]] = {}
    for groups in by_brand.values():
        if not groups["aff"] or not groups["free"]:
            continue
        for a in groups["aff"]:
            twins[a["id"]] = list(groups["free"])
        for f in groups["free"]:
            twins[f["id"]] = list(groups["aff"])
    return twins


def _dedupe_notes(notes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in notes:
        key = " ".join(n.lower().split())
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def auto_gotchas(deal: dict, twins: list[dict] | None = None) -> list[str]:
    """Safe baseline caveats derived only from deals.json schema fields."""
    notes: list[str] = []
    twins = twins or []
    promo = deal.get("promo_code")
    claim = deal.get("claim_note")
    ctype = str(deal.get("") or "")
    ctype_l = ctype.lower()
    unit = deal.get("unit") or ""
    unit_l = unit.lower()
    referral = str(deal.get("payout_status") or "").lower()

    if claim and "apply" in str(claim).lower():
        notes.append(
            f"Application / approval required (claim_note: {esc(claim)}) — not a redeemable promo code."
        )
    elif promo:
        notes.append(
            f"Authorized promo code on this listing: <code>{esc(promo)}</code>. "
            "Do not invent other codes — use redeem_url with this code only."
        )
    else:
        notes.append(
            "No promo code on this listing — use the authorized redeem_url / signup link only. Never invent codes."
        )

    if referral == "floated":
        notes.append(
            ""
        )

    if "account_credit" in ctype_l or (deal.get("affiliate") and "account credit" in unit_l):
        detail = esc(ctype or unit)
        notes.append(
            f"referral quirk:"
        )
    elif deal.get("affiliate") and ("credit" in ctype_l):
        notes.append(
            f"referral quirk: rewards are credits ({esc(ctype)}), not cash"
        )
    elif ctype_l in ("unverified", "tbd") or (
        deal.get("affiliate") and ("" in unit_l or "tbd" in unit_l)
    ):
        notes.append(
            ""
        )

    if deal.get("affiliate") is True and (
        "free plan" in unit_l
        or "free tier" in unit_l
        or "free signup" in unit_l
        or "trial" in unit_l
    ):
        notes.append(
            f"Free-tier / trial trap: unit notes say “{esc(unit)}” — confirm limits before relying on free usage for production agent load."
        )

    if is_free_tierish(deal) and unit:
        notes.append(
            f"Free-tier limits: {esc(unit)}. Outgrowing free usually means a paid plan — check any affiliate twin on this board before inventing coupons."
        )

    for sib in twins:
        slug = slug_for(sib["id"])
        href = f"{BASE}/deals/{slug}/"
        label = esc(sib.get("title") or sib["id"])
        if deal.get("affiliate") is True and is_free_tierish(sib):
            notes.append(
                f'Affiliate vs free twin: compare with <a href="{href}">{label}</a> before paying.'
            )
        elif is_free_tierish(deal) and sib.get("affiliate") is True:
            notes.append(
                f'Free vs paid twin: when you need volume, see affiliate listing <a href="{href}">{label}</a> (authorized redeem link only).'
            )

    raw_notes = deal.get("notes")
    if isinstance(raw_notes, str) and raw_notes.strip():
        snippet = " ".join(raw_notes.strip().split())
        if len(snippet) > 180:
            snippet = snippet[:177].rstrip() + "…"
        low = snippet.lower()
        if any(w in low for w in ("referral", "floated", "credit", "", "tracking", "slug", "referral")):
            notes.append(f"Feed notes: {esc(snippet)}")

    return _dedupe_notes(notes)


def _theme_flags(text: str) -> set[str]:
    low = text.lower()
    flags: set[str] = set()
    if any(w in low for w in ("promo code", "no promo", "invent", "redeem_url", "authorized referral", "authorized redeem")):
        flags.add("promo")
    if "floated" in low or "referral" in low:
        flags.add("referral")
    if "account credit" in low or ("credit" in low and "free" not in low.split("credit")[0][-20:]):
        if "account credit" in low or "credits" in low or "credit referral" in low or "rewards are credits" in low:
            flags.add("credit")
    if "tbd" in low or "unverified" in low:
        flags.add("tbd")
    if any(w in low for w in ("free-tier", "free tier", "trial trap", "free plan", "free signup", "free-tier limits", "free developer")):
        flags.add("free")
    if "twin" in low or "compare with" in low or "when you need volume" in low:
        flags.add("twin")
    if low.startswith("feed notes:"):
        flags.add("feed_notes")
    if "application" in low and "apply" in low:
        flags.add("apply")
    return flags


def collect_gotchas(
    deal: dict,
    curated: dict[str, list[str]],
    twin_index: dict[str, list[dict]],
) -> list[str]:
    """Curated notes first (escaped); auto-rules fill gaps only (theme-aware)."""
    curated_html = [esc(n) for n in (curated.get(deal["id"]) or [])]
    covered: set[str] = set()
    for n in curated_html:
        covered |= _theme_flags(n)
    auto = auto_gotchas(deal, twin_index.get(deal["id"]))
    extras = []
    for n in auto:
        themes = _theme_flags(n)
        # Keep cross-link HTML and feed_notes even when curated already spoke to the theme.
        if '<a href=' in n or "feed_notes" in themes:
            extras.append(n)
            covered |= themes
            continue
        if themes and themes & covered:
            continue
        extras.append(n)
        covered |= themes
    return _dedupe_notes(curated_html + extras)


def gotchas_html(notes: list[str]) -> str:
    if not notes:
        return ""
    items = "\n".join(f"      <li>{n}</li>" for n in notes)
    return f"""
    <aside class="gotchas" aria-label="Before you redeem">
      <h2>Before you redeem</h2>
      <ul>
{items}
      </ul>
    </aside>
"""


def parse_deal_updated(deal: dict) -> datetime | None:
    """Parse deal.updated_at from deals.json only. Never invent timestamps."""
    raw = deal.get("updated_at")
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def freshness_bits(deal: dict, *, now: datetime | None = None) -> tuple[str, str]:
    """Return (badge_html, date_line_html) from real updated_at only.

    Badge: New if within 7 days, Updated if within 14 days; else empty badge.
    Date line: 'Updated Mon D, YYYY' when timestamp present; else empty (omit).
    """
    ts = parse_deal_updated(deal)
    if ts is None:
        return "", ""
    if now is None:
        now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
    elif ts.tzinfo and now.tzinfo is None:
        now = now.replace(tzinfo=ts.tzinfo)
    elif now.tzinfo and ts.tzinfo is None:
        ts = ts.replace(tzinfo=now.tzinfo)
    age_days = (now - ts).total_seconds() / 86400.0
    badge = ""
    if age_days <= 7:
        badge = '<span class="badge fresh-new">New</span>'
    elif age_days <= 14:
        badge = '<span class="badge fresh-updated">Updated</span>'
    try:
        label = ts.strftime("%b %-d, %Y")
    except ValueError:
        label = ts.strftime("%b %d, %Y").replace(" 0", " ")
    date_line = f'<p class="freshness">Updated {esc(label)}</p>'
    return badge, date_line


def price_bits(deal: dict) -> str:
    price = deal.get("price_usd")
    unit = deal.get("unit") or ""
    list_p = deal.get("list_price_usd")
    parts = []
    if price is not None:
        parts.append(f"<strong>${esc(price)}</strong>")
        if list_p is not None:
            parts.append(f"<s>${esc(list_p)}</s>")
    if unit:
        parts.append(f"/ {esc(unit)}")
    return " ".join(parts)


def badges(deal: dict) -> str:
    bits = []
    fresh_badge, _ = freshness_bits(deal)
    if fresh_badge:
        bits.append(fresh_badge)
    if is_example(deal):
        bits.append('<span class="badge example">example</span>')
    if deal.get("affiliate"):
        bits.append('<span class="badge affiliate">affiliate</span>')
    elif not is_example(deal):
        bits.append('<span class="badge public">public / non-affiliate</span>')
    if deal.get("agent_only"):
        bits.append('<span class="badge agent">agent-only</span>')
    if deal.get("claim_note"):
        bits.append(f'<span class="badge">{esc(deal["claim_note"])}</span>')
    return " ".join(bits)


def tags_html(deal: dict) -> str:
    tags = deal.get("tags") or []
    return " ".join(f'<span class="tag">{esc(t)}</span>' for t in tags)


def cta_html(deal: dict) -> str:
    url = deal.get("redeem_url") or deal.get("source_url") or "#"
    if deal.get("affiliate"):
        rel = 'rel="nofollow sponsored"'
        label = "Redeem / signup"
    else:
        rel = 'rel="noopener noreferrer"'
        label = "Open offer / signup"
    extra = ""
    if deal.get("promo_code"):
        extra += f' · code <code>{esc(deal["promo_code"])}</code>'
    if deal.get("claim_note"):
        extra += f' · <em>{esc(deal["claim_note"])}</em>'
    return f'<a class="cta" {rel} href="{esc(url)}">{label}</a>{extra}'


def json_ld(deal: dict, page_url: str) -> str:
    offer: dict = {
        "@context": "https://schema.org",
        "@type": "Offer",
        "name": deal.get("title"),
        "url": page_url,
        "category": deal.get("category"),
        "seller": {"@type": "Organization", "name": deal.get("advertiser")},
    }
    if deal.get("price_usd") is not None:
        offer["price"] = deal["price_usd"]
        offer["priceCurrency"] = "USD"
    if deal.get("unit"):
        offer["description"] = deal["unit"]
    if deal.get("expires_at"):
        offer["priceValidUntil"] = str(deal["expires_at"])[:10]
    availability = "https://schema.org/InStock"
    if is_example(deal):
        availability = "https://schema.org/Discontinued"
    offer["availability"] = availability
    return json.dumps(offer, ensure_ascii=False, indent=2)


def deal_card(deal: dict, link_mode: str = "page") -> str:
    """link_mode: page -> /deals/slug/; anchor -> #id"""
    slug = slug_for(deal["id"])
    if link_mode == "page":
        href = f"{BASE}/deals/{slug}/"
    else:
        href = f"#{esc(deal['id'])}"
    aff_attr = ""
    if deal.get("affiliate") is True:
        aff_attr = ' data-affiliate="true"'
    elif deal.get("affiliate") is False:
        aff_attr = ' data-affiliate="false"'
    _, fresh_line = freshness_bits(deal)
    return f"""
    <article class="deal" id="{esc(deal['id'])}" data-category="{esc(deal.get('category'))}"{aff_attr}>
      <h2><a href="{href}">{esc(deal.get('title'))}</a> {badges(deal)}</h2>
      <p class="meta"><span class="cat">{esc(deal.get('category'))}</span> · {price_bits(deal)} · {esc(deal.get('advertiser'))}</p>
      {fresh_line}
      <p class="tags">{tags_html(deal)}</p>
      <p class="instructions">{esc(deal.get('agent_instructions') or '')}</p>
      <p class="redeem">{cta_html(deal)}</p>
    </article>
"""



def social_meta(title: str, description: str, canonical: str, og_type: str = "website") -> str:
    """Open Graph + Twitter card tags. Absolute https URLs; no invented og:image."""
    return f"""  <meta property="og:title" content="{esc(title)}" />
  <meta property="og:description" content="{esc(description)}" />
  <meta property="og:url" content="{esc(canonical)}" />
  <meta property="og:type" content="{esc(og_type)}" />
  <meta property="og:site_name" content="{esc(SITE_NAME)}" />
  <meta name="twitter:card" content="summary" />
  <meta name="twitter:title" content="{esc(title)}" />
  <meta name="twitter:description" content="{esc(description)}" />"""


def homepage_json_ld(deals: list[dict]) -> str:
    """WebSite + Organization + CollectionPage/ItemList for the deals board."""
    org_id = f"{BASE}/#organization"
    website_id = f"{BASE}/#website"
    items = []
    position = 0
    for d in sort_deals_affiliates_first(deals):
        if is_example(d):
            continue
        position += 1
        slug = slug_for(d["id"])
        items.append(
            {
                "@type": "ListItem",
                "position": position,
                "url": f"{BASE}/deals/{slug}/",
                "name": d.get("title"),
            }
        )
    graph = [
        {
            "@type": "Organization",
            "@id": org_id,
            "name": SITE_NAME,
            "url": f"{BASE}/",
            "email": "lanternworks@agentmail.to",
            "description": (
                "Affiliate-backed and public free-tier deals for AI agent work stacks "
                "(compute, search, crawl, hosting, email, unblock)."
            ),
        },
        {
            "@type": "WebSite",
            "@id": website_id,
            "name": "Agent work-stack deals",
            "url": f"{BASE}/",
            "description": (
                "Deals for AI agents: compute, scrapers/unblock, templates, search APIs, hosting. "
                "Affiliate-backed offers + machine-readable JSON feed."
            ),
            "publisher": {"@id": org_id},
            "inLanguage": "en",
        },
        {
            "@type": "CollectionPage",
            "@id": f"{BASE}/#collection",
            "name": "Agent work-stack deals",
            "url": f"{BASE}/",
            "isPartOf": {"@id": website_id},
            "about": {"@id": org_id},
            "mainEntity": {
                "@type": "ItemList",
                "name": "Lantern Works agent deals",
                "numberOfItems": len(items),
                "itemListElement": items,
            },
        },
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=2)


def page_shell(title: str, description: str, canonical: str, body: str, robots: str = "index,follow") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}" />
  <meta name="robots" content="{esc(robots)}" />
  <link rel="canonical" href="{esc(canonical)}" />
{social_meta(title, description, canonical)}
  <style>{CSS}</style>
</head>
<body>
{body}
  <footer>
    <p>Verified-on dates reflect feed <code>updated_at</code> / research fetch day. Affiliate deals use authorized links only; public/non-affiliate badges mark free tiers and vendor-published coupons (no invented codes).</p>
    <p><strong>Lantern Works</strong> · <a href="{BASE}/">All deals</a> · <a href="{BASE}/lanternworks/">About</a> · <a href="{BASE}/changelog/">Changelog</a> · Contact <a href="mailto:lanternworks@agentmail.to">lanternworks@agentmail.to</a></p>
    <p>Affiliate disclosure: we may earn a That never changes the price you pay.</p>
  </footer>
</body>
</html>
"""


def write_deal_page(deal: dict, feed_updated: str, *, curated_gotchas: dict[str, list[str]] | None = None, twin_index: dict[str, list[dict]] | None = None) -> Path:
    slug = slug_for(deal["id"])
    out_dir = ROOT / "deals" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    page_url = f"{BASE}/deals/{slug}/"
    example = is_example(deal)
    robots = "noindex,follow" if example else "index,follow"
    verified = (feed_updated or VERIFIED)[:10]
    desc = (
        f"{deal.get('title')} — {deal.get('category')} deal from {deal.get('advertiser')}. "
        f"{(deal.get('unit') or '')[:120]}"
    ).strip()
    hub_links = []
    for hub in HUBS:
        if hub["match"](deal):
            hub_links.append(f'<a href="{BASE}/categories/{hub["slug"]}/">{esc(hub["slug"])}</a>')
    hubs_nav = " · ".join(hub_links[:4]) if hub_links else f'<a href="{BASE}/categories/{esc(hub_slug(deal.get("category") or "compute"))}/">{esc(deal.get("category"))}</a>'

   ""
    if deal.get("affiliate") and deal.get("") is not None:
        pct = deal[""]
        ctype = deal.get("") or ""
       

    _, fresh_line = freshness_bits(deal)

    gnotes = collect_gotchas(deal, curated_gotchas or {}, twin_index or {})
    gbox = gotchas_html(gnotes)

    body = f"""
  <p class="crumbs"><a href="{BASE}/">Home</a> · <a href="{BASE}/lanternworks/">Lantern Works</a> · {hubs_nav}</p>
  <article class="deal" id="{esc(deal['id'])}">
    <h1>{esc(deal.get('title'))} {badges(deal)}</h1>
    <p class="meta"><span class="cat">{esc(deal.get('category'))}</span> · {price_bits(deal)} · Advertiser: {esc(deal.get('advertiser'))}</p>
    <p class="tags">{tags_html(deal)}</p>
    {
    {fresh_line}
    <p class="verified">Verified-on: {esc(verified)}</p>
    <p class="instructions">{esc(deal.get('agent_instructions') or '')}</p>
    <p class="redeem">{cta_html(deal)}</p>
    {gbox}
    {"<p><em>Sample inventory placeholder — not a live merchant offer.</em></p>" if example else ""}
  </article>
  <script type="application/ld+json">
{json_ld(deal, page_url)}
  </script>
"""
    title = f"{deal.get('title')} — Lantern Works deals"
    (out_dir / "index.html").write_text(
        page_shell(title, desc[:300], page_url, body, robots=robots), encoding="utf-8"
    )
    return out_dir / "index.html"


def write_hub(hub: dict, deals: list[dict]) -> Path:
    matched = [d for d in deals if hub["match"](d)]
    # Real offers first, then affiliates-first (shared helper), then id
    matched = sort_deals_affiliates_first(
        sorted(matched, key=lambda d: (is_example(d), d.get("id") or ""))
    )
    out_dir = ROOT / "categories" / hub["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    page_url = f"{BASE}/categories/{hub['slug']}/"
    cards = "\n".join(deal_card(d, link_mode="page") for d in matched) or "<p>No deals in this hub yet.</p>"
    body = f"""
  <p class="crumbs"><a href="{BASE}/">Home</a> · <a href="{BASE}/lanternworks/">Lantern Works</a> · Category hubs</p>
  <header>
    <h1>{esc(hub['title'])}</h1>
    <p>{esc(hub['description'])}</p>
    <p class="meta">{len(matched)} offers · lastmod {LASTMOD}</p>
  </header>
  <main>
{cards}
  </main>
"""
    (out_dir / "index.html").write_text(
        page_shell(f"{hub['title']} — Lantern Works", hub["description"], page_url, body),
        encoding="utf-8",
    )
    return out_dir / "index.html"


def write_guide(guide: dict, by_id: dict[str, dict]) -> Path:
    """Write a curated Best-for-X stack guide under guides/<slug>/."""
    missing = [p["id"] for p in guide["picks"] if p["id"] not in by_id]
    if missing:
        raise RuntimeError(f"guide {guide['slug']}: missing deals {missing}")
    out_dir = ROOT / "guides" / guide["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    page_url = f"{BASE}/guides/{guide['slug']}/"
    items = []
    for i, pick in enumerate(guide["picks"], 1):
        deal = by_id[pick["id"]]
        slug = slug_for(deal["id"])
        deal_page = f"{BASE}/deals/{slug}/"
        label = pick.get("label")
        label_html = f' <span class="badge public">{esc(label)}</span>' if label else ""
        # Redeem only via authorized URL from deals.json
        redeem = cta_html(deal)
        items.append(
            f"""    <section class="deal" id="pick-{i}">
      <h2>{i}. <a href="{deal_page}">{esc(deal.get("title"))}</a>{label_html} {badges(deal)}</h2>
      <p class="why"><strong>Why:</strong> {esc(pick["why"])}</p>
      <p class="meta"><a href="{deal_page}">Deal page</a> · {esc(deal.get("advertiser") or "")}</p>
      <p class="redeem">{redeem}</p>
    </section>
"""
        )
    picks_html = "\n".join(items)
    body = f"""
  <p class="crumbs"><a href="{BASE}/">Home</a> · <a href="{BASE}/lanternworks/">Lantern Works</a> · Stack guides</p>
  <header>
    <h1>{esc(guide["title"])}</h1>
    <p>{esc(guide["intro"])}</p>
    <p class="meta">{len(guide["picks"])} curated picks · lastmod {LASTMOD}</p>
  </header>
  <main>
{picks_html}
  </main>
  <p class="meta">More stacks: """ + " · ".join(
        f'<a href="{BASE}/guides/{g["slug"]}/">{esc(g["title"])}</a>'
        for g in GUIDES
        if g["slug"] != guide["slug"]
    ) + f""" · <a href="{BASE}/">all deals</a></p>
"""
    (out_dir / "index.html").write_text(
        page_shell(f'{guide["title"]} — Lantern Works', guide["description"], page_url, body),
        encoding="utf-8",
    )
    return out_dir / "index.html"


def guides_nav_html() -> str:
    links = " · ".join(
        f'<a href="{BASE}/guides/{g["slug"]}/">{esc(g["title"])}</a>' for g in GUIDES
    )
    return (
        f'<nav class="stack-guides" style="margin-top:.5rem;">'
        f'<strong>Stack guides:</strong> {links}</nav>'
    )



def write_sitemap(deal_slugs: list[str], hub_slugs: list[str], guide_slugs: list[str] | None = None) -> Path:
    urls = [
        (f"{BASE}/", "1.0"),
        (f"{BASE}/lanternworks/", "0.8"),
        (f"{BASE}/changelog/", "0.7"),
    ]
    for s in hub_slugs:
        urls.append((f"{BASE}/categories/{s}/", "0.7"))
    for s in (guide_slugs or []):
        urls.append((f"{BASE}/guides/{s}/", "0.75"))
    for s in deal_slugs:
        urls.append((f"{BASE}/deals/{s}/", "0.6"))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, pri in urls:
        lines.append(
            f"  <url><loc>{loc}</loc><lastmod>{LASTMOD}</lastmod>"
            f"<changefreq>weekly</changefreq><priority>{pri}</priority></url>"
        )
    lines.append("</urlset>")
    path = ROOT / "sitemap.xml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path



FEED_RAW = (
    "https://gist.githubusercontent.com/connormatthewdouglas/"
    "ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json"
)


def agent_query_howto_html() -> str:
    """Homepage section: how agents should query the public feed. Generator-owned."""
    return f"""  <section id="how-agents-query" class="howto">
    <h2 class="section-title" style="margin-top:0;">How agents should query this</h2>
    <p>Public JSON feed (no auth). Default filter posture is <strong>real-only</strong> (skip <code>example: true</code>). Default array order is <strong>affiliates first</strong> (<code>query.sort</code> / <code>query.defaults.sort</code>). Production inventory is live Lantern Works listings.</p>
    <p class="feed" style="margin:.6rem 0;">GET <a href="{FEED_RAW}">{FEED_RAW}</a></p>
    <table>
      <thead><tr><th>Filter</th><th>Meaning</th></tr></thead>
      <tbody>
        <tr><td><code>category</code></td><td>Exact category (<code>compute</code>, <code>email</code>, <code>hosting</code>, <code>search</code>, <code>unblock</code>, …)</td></tr>
        <tr><td><code>affiliate</code></td><td><code>true</code> = referral; <code>false</code> = public/non-affiliate</td></tr>
        <tr><td><code>free_tier</code> / <code>non_affiliate</code></td><td><code>affiliate == false</code> (often also <code>price_usd: 0</code>). Do <strong>not</strong> treat <code>price_usd == 0</code> alone as free-tier.</td></tr>
        <tr><td><code>updated_since</code></td><td>ISO-8601; keep deals with <code>updated_at &gt;=</code> value; drop rows missing <code>updated_at</code></td></tr>
        <tr><td><code>tag</code></td><td>Require tags (AND)</td></tr>
        <tr><td><code>agent_only</code></td><td>Only <code>agent_only == true</code></td></tr>
        <tr><td><code>max_price</code></td><td>Inclusive max on <code>price_usd</code></td></tr>
        <tr><td><code>real_only</code></td><td>Default; exclude <code>example == true</code></td></tr>
        <tr><td><code>id</code></td><td>Exact deal id</td></tr>
      </tbody>
    </table>
    <p><strong>curl + local filter</strong></p>
    <pre>curl -fsSL "{FEED_RAW}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)
print([x["id"] for x in d["deals"] if x.get("category")=="search" and x.get("affiliate")])'</pre>
    <p><strong>query_deals.py</strong> (repo CLI)</p>
    <pre>python3 query_deals.py --category search
python3 query_deals.py --affiliate
python3 query_deals.py --free-tier
python3 query_deals.py --updated-since 2026-10-23T00:00:00-04:00
python3 query_deals.py --tag crawl --max-price 20 --json</pre>
    <p class="meta">Machine-readable contract: feed <code>query</code> object · skill <code>lantern-works-deals</code> · <code>USAGE.md</code> · MCP sketch under <code>mcp/</code>.</p>
  </section>
"""


def write_index(deals: list[dict], feed_updated: str) -> Path:
    # Preserve affiliates-first within each category (matches feed default sort).
    by_cat = defaultdict(list)
    for d in sort_deals_affiliates_first(deals):
        by_cat[d.get("category") or "other"].append(d)

    hub_nav = " · ".join(
        f'<a href="{BASE}/categories/{h["slug"]}/">{esc(h["slug"])}</a>' for h in HUBS[:5]
    )
    cat_nav = " · ".join(
        f'<a href="#cat-{c}">{c}</a> · <a href="{BASE}/categories/{hub_slug(c)}/">{c} hub</a>'
        for c in CATEGORY_ORDER
        if c in by_cat
    )

    sections = []
    for cat in CATEGORY_ORDER:
        if cat not in by_cat:
            continue
        cards = "\n".join(deal_card(d, link_mode="page") for d in by_cat[cat])
        sections.append(
            f'<section id="cat-{esc(cat)}"><h2 class="section-title">Agent deals: {esc(cat)}</h2>\n{cards}\n</section>'
        )

    body_main = "\n".join(sections)
    updated = feed_updated or datetime.now().astimezone().isoformat(timespec="seconds")
    index_title = "Agent work-stack deals — compute, unblock, templates, search, hosting"
    index_desc = (
        "Deals for AI agents: compute, scrapers/unblock, templates, search APIs, hosting. "
        "Affiliate-backed offers + machine-readable JSON feed."
    )
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name='impact-site-verification' value='594aa2cb-9310-430a-8577-b47b45c91f8f'>
  <meta name="impact-site-verification" content="594aa2cb-9310-430a-8577-b47b45c91f8f" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(index_title)}</title>
  <meta name="description" content="{esc(index_desc)}" />
  <meta name="robots" content="index,follow" />
  <link rel="canonical" href="{BASE}/" />
{social_meta(index_title, index_desc, f"{BASE}/")}
  <script type="application/ld+json">
{homepage_json_ld(deals)}
  </script>
  <style>{CSS}</style>
</head>
<body>
  <header>
    <h1>Agent work-stack deals</h1>
    <p style="font-size:.9rem;"><a href="lanternworks/">About Lantern Works</a> · <a href="changelog/">Changelog</a></p>
    <p>Affiliate-backed offers plus <strong>public / non-affiliate</strong> free tiers and vendor-published coupons for AI agents (and humans directing them). Free to browse. Default order: <strong>affiliates first</strong>, then public/non-affiliate — not pure</p>
    <nav>Jump: {cat_nav}</nav>
    <nav style="margin-top:.35rem;">Hubs: {hub_nav}</nav>
    {guides_nav_html()}
    <p class="feed"><strong>Agents:</strong> GET <a href="https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json">https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json</a> · helpers in the <a href="https://gist.github.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e">gist</a> / this repo.</p>
  </header>
{agent_query_howto_html()}
  <main>{body_main}</main>
  <footer><p>Updated {esc(updated)} Affiliate deals use authorized links only; public/non-affiliate badges mark free tiers and vendor-published coupons (no invented codes).</p><p><strong>Lantern Works</strong> · <a href="lanternworks/">About</a> · <a href="changelog/">Changelog</a> · Contact <a href="mailto:lanternworks@agentmail.to">lanternworks@agentmail.to</a></p>
    <p>Affiliate disclosure: we may earn a That never changes the price you pay.</p>
  </footer>
</body>
</html>
"""
    path = ROOT / "index.html"
    path.write_text(html_doc, encoding="utf-8")
    return path


def patch_lanternworks() -> None:
    path = ROOT / "lanternworks" / "index.html"
    text = path.read_text(encoding="utf-8")
    lw_title = "Lantern Works — agent work-stack deals"
    lw_desc = (
        "Lantern Works: human-readable deals for AI agents (and humans directing them). "
        "Affiliate-backed compute, search, crawl, hosting, templates, and unblock tools."
    )
    lw_url = f"{BASE}/lanternworks/"
    social = social_meta(lw_title, lw_desc, lw_url)
    # Idempotent: wrap social tags in markers so regen replaces cleanly.
    begin, end_m = "<!-- seo-social -->", "<!-- /seo-social -->"
    block = f"{begin}\n{social}\n  {end_m}"
    if begin in text and end_m in text:
        text = re.sub(
            re.escape(begin) + r".*?" + re.escape(end_m),
            block,
            text,
            count=1,
            flags=re.S,
        )
    else:
        # Drop any prior bare OG/Twitter metas before re-inserting.
        text = re.sub(
            r'[ \t]*<meta (?:property="og:[^"]+"|name="twitter:[^"]+") content="[^"]*" />\n',
            "",
            text,
        )
        needle = f'<link rel="canonical" href="{lw_url}" />'
        if needle not in text:
            raise RuntimeError("lanternworks canonical link missing")
        text = text.replace(needle, needle + "\n  " + block, 1)

    marker = "<!-- seo-hubs -->"
    guide_links = " · ".join(
        f'<a href="{BASE}/guides/{g["slug"]}/">{esc(g["title"])}</a>' for g in GUIDES
    )
    block = (
        f'{marker}\n    <p class="meta">Browse by hub: '
        f'<a href="{BASE}/categories/scraping-unblock/">scraping-unblock</a> · '
        f'<a href="{BASE}/categories/proxies/">proxies</a> · '
        f'<a href="{BASE}/categories/serp-apis/">serp-apis</a> · '
        f'<a href="{BASE}/categories/gpu-compute/">gpu-compute</a> · '
        f'<a href="{BASE}/categories/email-apis/">email-apis</a> · '
        f'<a href="{BASE}/">all deals</a> · '
        f'<a href="{BASE}/changelog/">changelog</a></p>\n'
        f'    <p class="meta">Stack guides: {guide_links}</p>\n'
    )
    if marker in text:
        # Replace marker + following consecutive .meta paragraphs (avoids leaving duplicates).
        text = re.sub(
            r"<!-- seo-hubs -->(?:\s*<p class=\"meta\">.*?</p>\n)+",
            block,
            text,
            count=1,
            flags=re.S,
        )
    else:
        # insert after lede or after first <h1> block nav
        if '<p class="lede">' in text:
            text = text.replace(
                "</p>\n    <div",
                "</p>\n    " + block + "    <div",
                1,
            )
            if marker not in text:
                text = text.replace(
                    '<p class="lede">',
                    block + '    <p class="lede">',
                    1,
                )
        else:
            text = text.replace("</header>", "    " + block + "  </header>", 1)
    # Changelog link in top nav (idempotent).
    if 'href="../changelog/"' not in text and 'href="../">All deals</a>' in text:
        text = text.replace(
            '<a href="../">All deals</a>',
            '<a href="../">All deals</a>\n    <a href="../changelog/">Changelog</a>',
            1,
        )

    path.write_text(text, encoding="utf-8")



def md_inline_to_html(s: str) -> str:
    """Minimal markdown inline: [text](url) and **bold** and `code`."""
    s = esc(s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    # unescape href we just escaped badly — rebuild properly
    return s


def render_changelog_markdown(md: str) -> str:
    """Very small markdown→HTML for CHANGELOG.md (headings, lists, paragraphs, links)."""
    lines = md.splitlines()
    out: list[str] = []
    in_ul = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    def inline(s: str) -> str:
        # links first on raw, then escape remainder via piecewise build
        parts: list[str] = []
        pos = 0
        for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`", s):
            if m.start() > pos:
                parts.append(esc(s[pos:m.start()]))
            if m.group(1) is not None:
                parts.append(f'<a href="{esc(m.group(2))}">{esc(m.group(1))}</a>')
            elif m.group(3) is not None:
                parts.append(f"<strong>{esc(m.group(3))}</strong>")
            else:
                parts.append(f"<code>{esc(m.group(4))}</code>")
            pos = m.end()
        if pos < len(s):
            parts.append(esc(s[pos:]))
        return "".join(parts)

    for line in lines:
        if line.startswith("# "):
            close_ul()
            continue  # page title supplied by shell
        if line.startswith("## "):
            close_ul()
            out.append(f"<h2>{inline(line[3:].strip())}</h2>")
            continue
        if line.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(line[2:].strip())}</li>")
            continue
        if not line.strip():
            close_ul()
            continue
        close_ul()
        out.append(f"<p>{inline(line.strip())}</p>")
    close_ul()
    return "\n".join(out)


def write_changelog() -> Path:
    """Render CHANGELOG.md → changelog/index.html (maintainable append path)."""
    md_path = ROOT / "CHANGELOG.md"
    if not md_path.exists():
        raise RuntimeError("CHANGELOG.md missing — create it before generating")
    md = md_path.read_text(encoding="utf-8")
    out_dir = ROOT / "changelog"
    out_dir.mkdir(parents=True, exist_ok=True)
    page_url = f"{BASE}/changelog/"
    title = "Changelog — Lantern Works agent deals"
    desc = (
        "What shipped on the Lantern Works agent work-stack deals site: "
        "new affiliates, guides, feed filters, and SEO updates."
    )
    body = f"""
  <p class="crumbs"><a href="{BASE}/">Home</a> · <a href="{BASE}/lanternworks/">Lantern Works</a> · Changelog</p>
  <header>
    <h1>Changelog</h1>
    <p>Recent ships for agents and humans. Source of truth: <code>CHANGELOG.md</code> in the repo (append new entries at the top; regen with <code>scripts/generate_seo_pages.py</code>).</p>
  </header>
  <main class="changelog">
{render_changelog_markdown(md)}
  </main>
"""
    (out_dir / "index.html").write_text(
        page_shell(title, desc, page_url, body), encoding="utf-8"
    )
    return out_dir / "index.html"


def ensure_robots() -> None:
    path = ROOT / "robots.txt"
    desired = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {BASE}/sitemap.xml\n"
    )
    path.write_text(desired, encoding="utf-8")


def main() -> None:
    feed = json.loads(DEALS_PATH.read_text(encoding="utf-8"))
    deals = feed["deals"]
    feed_updated = feed.get("updated_at") or VERIFIED

    curated_gotchas = load_curated_gotchas()
    twin_index = build_twin_index(deals)

    deal_paths = []
    deal_slugs = []
    for d in deals:
        p = write_deal_page(
            d,
            feed_updated,
            curated_gotchas=curated_gotchas,
            twin_index=twin_index,
        )
        deal_paths.append(p)
        deal_slugs.append(slug_for(d["id"]))

    hub_paths = []
    hub_slugs = []
    for hub in HUBS:
        p = write_hub(hub, deals)
        hub_paths.append(p)
        hub_slugs.append(hub["slug"])

    by_id = {d["id"]: d for d in deals}
    guide_paths = []
    guide_slugs = []
    for guide in GUIDES:
        p = write_guide(guide, by_id)
        guide_paths.append(p)
        guide_slugs.append(guide["slug"])

    write_sitemap(deal_slugs, hub_slugs, guide_slugs)
    write_changelog()
    write_index(deals, feed_updated)
    patch_lanternworks()
    ensure_robots()

    print(f"deal_pages={len(deal_paths)}")
    print(f"hub_pages={len(hub_paths)}")
    print(f"guide_pages={len(guide_paths)}")
    # home + lanternworks + changelog + hubs + guides + deals
    print(f"sitemap_urls={3 + len(hub_slugs) + len(guide_slugs) + len(deal_slugs)}")
    print(f"deals={len(deals)}")


if __name__ == "__main__":
    main()
