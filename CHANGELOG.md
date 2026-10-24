# Site changelog

Reverse-chronological ships for [Agent work-stack deals](https://connormatthewdouglas.github.io/agent-work-stack-deals/) (Lantern Works). Append new entries at the top. The generator renders this file to [`changelog/`](https://connormatthewdouglas.github.io/agent-work-stack-deals/changelog/).

## 2026-10-24 — Botpress live affiliate; Vapi terms

- Added **Botpress** AI agent builder (`deal-botpress-001`, 30% of referred spend for 12 months excl. AI usage, via PartnerStack) — live affiliate #50; listed on the ai-agents hub.
- Updated **Vapi** notes with affiliate-portal terms (15% per paid referral; duration and cookie not stated).

## 2026-10-24 — Vapi live affiliate

- Added **Vapi** voice AI agents API (`deal-vapi-001`, 15% per paid referral, duration unconfirmed, via Tolt aff lanternworks) — live affiliate #49; listed on the ai-agents hub.

## 2026-10-24 — Quickchat AI live affiliate

- Added **Quickchat AI** no-code AI agent / chatbot builder (`deal-quickchat-001`, 20% recurring per paid referral for 12 months, via Tolt ref lanternworks) — live affiliate #48; listed on the ai-agents hub.

## 2026-10-23 — AI agents hub + Chipp and Chatbase live affiliates

- New **AI agent platform deals** hub at [`categories/ai-agents/`](https://connormatthewdouglas.github.io/agent-work-stack-deals/categories/ai-agents/) for agent builders, chatbot platforms, and general AI agents; **Runable** moved there from templates.
- Added **Chipp** no-code AI agent builder (`deal-chipp-001`, 20% per sale for 12 months, via Dub link key lanternworks) — live affiliate #46; listed on the ai-agents hub.
- Added **Chatbase** AI support agent / chatbot platform (`deal-chatbase-001`, up to 30% per sale for 12 months, via Dub link key lanternworks) — live affiliate #47; listed on the ai-agents hub.

## 2026-10-23 — Runable live affiliate

- Added **Runable** general-purpose AI agent platform (`deal-runable-001`, 25% per sale for 12 months, 30-day hold, via Dub link key lantern-works) — live affiliate #45; listed on the templates hub.

## 2026-10-23 — Undetectable.io live affiliate

- Added **Undetectable.io** antidetect browser with MCP/AI hooks for scraping/unblock (`deal-undetectable-001`, 10% lifetime referral share, in-house code SATFK) — live affiliate #44; listed on the unblock hubs.

## 2026-10-23 — MoreLogin live affiliate

- Added **MoreLogin** antidetect browser profiles for scraping/unblock (`deal-morelogin-001`, 15% of all paid orders ×24 months, no cap, top-ups excluded, in-house code lanternworks) — live affiliate #43; listed on the unblock hubs.

## 2026-10-23 — Incogniton live affiliate

- Added **Incogniton** antidetect browser profiles for scraping/unblock (`deal-incogniton-001`, 20% recurring, no cap, in-house affiliate ID 1937724) — live affiliate #42; listed on the unblock hubs.

## 2026-10-23 — AdsPower live affiliate

- Added **AdsPower** antidetect browser profiles for scraping/unblock (`deal-adspower-001`, 10% of subscription monthly ×24 months, up to 30%, in-house PartnerShare code lanternworks) — live affiliate #41; listed on the unblock hubs.

## 2026-10-23 — EmailListVerify live affiliate

- Added **EmailListVerify** email list verification API (`deal-emaillistverify-001`, 15% lifetime recurring, Reditus slug lanternworks) — live affiliate #40; listed on the email-apis hub.

## 2026-10-23 — GoLogin live affiliate

- Added **GoLogin** antidetect browser profiles for scraping/unblock (`deal-gologin-001`, 10% of all payments, in-house code lanternworks-ILQNHHI) — live affiliate #39; listed on the unblock and scraping/unblock hubs.

## 2026-10-23 — Nstbrowser live affiliate

- Added **Nstbrowser** antidetect browser for scraping/unblock (`deal-nstbrowser-001`, 15% first subscription + 10% renewals ×24 months, in-house slug lanternworks) — live affiliate #38; listed on the unblock and scraping/unblock hubs.

## 2026-10-23 — Seobility live affiliate

- Added **Seobility** SEO audit & rank tracking (`deal-seobility-001`, 30% lifetime recurring, PostAffiliatePro a_aid g96mhxtosqni0) — live affiliate #37; new **seo** category + `categories/seo/` hub. Homepage now also renders the proxies section.

## 2026-10-23 — Shifter live affiliate

- Added **Shifter** residential proxies & scraping (`deal-shifter-001`, 20% recurring, code zyDM) — live affiliate #36; listed on proxies and scraping/unblock hubs.

## 2026-10-23 — Comparison / gotcha notes on deal pages

- Every `deals/*/index.html` page now has a **Before you redeem** box.
- Durable curated notes live in [`data/deal_gotchas.json`](../data/deal_gotchas.json); `scripts/generate_seo_pages.py` merges them with auto-rules from feed fields (`promo_code`, `payout_status`, `commission_type`, `unit`, `claim_note`, `notes`) and affiliate↔free twin cross-links.
- High-value quirks covered: CleanProxies credit payout, ScraperAPI trial/free trap, Postmark & Firecrawl twins, Snov/ClearBounce floated, RunPod credits, Lightning Proxies commission TBD.

## 2026-10-23 — Freshness badges + affiliates-first ranking

- Deal pages and listing cards show **Updated** dates from feed `updated_at` when present (no invented dates); **New** / **Updated** badges for recent timestamps (~7–14 days).
- Default feed / homepage / hub order: **affiliates first**, then public/non-affiliate (`query.sort` / `query.defaults.sort`).
- This changelog page added to the sitemap and linked from home + Lantern Works.

## 2026-10-23 — Agent-queryable feed filters

- Documented machine-readable filters on the feed `query` object and homepage [#how-agents-query](https://connormatthewdouglas.github.io/agent-work-stack-deals/#how-agents-query).
- CLI / skill / MCP sketch: `category`, `affiliate`, `free_tier` / `non_affiliate`, `updated_since`, tags, `agent_only`, `max_price`, real-only default.

## 2026-10-23 — Best-for-X stack guides

- [Best agent scrape & unblock stack](https://connormatthewdouglas.github.io/agent-work-stack-deals/guides/agent-scrape-unblock/)
- [Cheap GPU week for agents](https://connormatthewdouglas.github.io/agent-work-stack-deals/guides/cheap-gpu-week/)
- [Best agent email & outreach stack](https://connormatthewdouglas.github.io/agent-work-stack-deals/guides/agent-email-outreach/)

## 2026-10-23 — ClearBounce affiliate

- Live deal: [ClearBounce — email verification API](https://connormatthewdouglas.github.io/agent-work-stack-deals/deals/clearbounce-001/)

## 2026-10-23 — SEO polish (OG / Twitter / JSON-LD)

- Open Graph + Twitter cards on generated pages; homepage Organization / WebSite / CollectionPage JSON-LD.

## 2026-10-23 — Snov.io affiliate

- Live deal: [Snov.io — email finder, verifier & outreach](https://connormatthewdouglas.github.io/agent-work-stack-deals/deals/snovio-001/)
- First email-category affiliate on the main board.

## 2026-10-23 — IPFoxy affiliate

- Live deal: [IPFoxy](https://connormatthewdouglas.github.io/agent-work-stack-deals/deals/ipfoxy-001/)

## 2026-10-23 — GloryCloud affiliate

- Live deal: [GloryCloud (GoProxy)](https://connormatthewdouglas.github.io/agent-work-stack-deals/deals/glorycloud-001/)
