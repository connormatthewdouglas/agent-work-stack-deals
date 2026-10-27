---
name: free-agent-infra
description: Assemble a $0 starter stack for an AI agent (hosting, search, crawl, email, compute credits) from free tiers in the Lantern Works deals feed.
---
# Free agent infra
1. GET https://thelanternworks.com/api/v1/deals.json; keep `offer_type == "free_tier"` and `example != true`.
2. Pick one per needed category (hosting, search, crawl, email, compute); list limits from each record.
3. Optionally call `optimize_stack` (MCP) with your monthly quantities to check whether free tiers cover them. Add `free_credits` from https://thelanternworks.com/api/v1/gpu-prices.json if GPU is needed.
4. Output a table: category, vendor, free limit, verified_at, link. Flag limits that the user's expected usage would exceed.
