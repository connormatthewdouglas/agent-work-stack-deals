---
name: scraping-api-selection
description: Choose a scraping, crawl or SERP API for a task by comparing tracked offers and free tiers from the Lantern Works deals feed.
---
# Scraping API selection
1. Clarify volume (pages/month), JS rendering, anti-bot needs, budget.
2. Query `search_deals` (MCP) with category `crawl`, `search` or `unblock`, or GET https://thelanternworks.com/api/v1/deals.json and filter by `category`.
3. For a monthly cost estimate call `optimize_stack` with `scrape_pages`, `scrape_pages_js`, `proxy_gb` or `search_queries` (plans with `manual_signup_only: true` need a human to sign up; pass `exclude_manual_signup` to drop them). Otherwise `compare_deals` on 2–5 candidates; prefer `free_tier`/`verified_discount` (a `listed_discount` is not confirmed) that cover the volume. `price_usd: null` = unknown, not free.
4. Present tradeoffs, then respect target-site ToS and robots.txt. No paid signup without user approval.
