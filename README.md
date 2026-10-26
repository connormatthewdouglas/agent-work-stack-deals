# Lantern Works — agent deals directory

**Lantern Works** publishes a curated directory of affiliate and public offers for AI agents (and humans directing them): compute, unblock/scrapers, templates, search, hosting, and related work-stack tools.

- **Browse:** [GitHub Pages](https://thelanternworks.com/)
- **About Lantern Works:** [lanternworks/](https://thelanternworks.com/lanternworks/)
- **Agent feed (JSON):** [raw deals.json on gist](https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json)
- **Query CLI:** `python3 query_deals.py --category unblock --max-price 20` (see [USAGE.md](USAGE.md) for the full filter contract)

Listings are live affiliate links (authorized Lantern Works referrals) or verified public/non-affiliate free tiers and vendor-published coupons. Agents `GET` the JSON feed with no auth and filter locally by `category`, `affiliate` / `free_tier`, `updated_since`, `agent_only`, `max_price`, `tags`, or `id` (default real-only). Contract: feed `query` object.

Contact: [lanternworks@agentmail.to](mailto:lanternworks@agentmail.to)
