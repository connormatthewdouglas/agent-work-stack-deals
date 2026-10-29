# Report a wrong GPU price

If a Lantern Works GPU price doesn't match the vendor's page, or you can't actually rent the offer, tell us. It takes under a minute.

**Humans:** open the form at
https://github.com/connormatthewdouglas/agent-work-stack-deals/issues/new?template=wrong-price.yml

**Agents and scripts:** the form accepts URL query parameters named after its field ids, so you can prefill it from a feed row
(`api/v1/gpu-prices.json` → `rates[]`):

| Form field id | Feed field |
|---|---|
| `vendor` | `advertiser` |
| `gpu` | `gpu` + `vram_gb` + `tier` |
| `deal_id` | `deal_id` (or the snapshot `key`) |
| `shown_price` | `hourly_equiv_usd` |
| `source_url` | `source_url` |
| `observed_price`, `observed_at`, `notes` | what you saw, when (with time zone) |

Example:
```
https://github.com/connormatthewdouglas/agent-work-stack-deals/issues/new?template=wrong-price.yml&vendor=RunPod&gpu=H100%20SXM%2080%20GB%20On-demand&deal_id=deal-runpod-001&shown_price=1.99&source_url=https%3A%2F%2Fwww.runpod.io%2Fpricing
```
URL-encode values. Opening the link doesn't submit anything; a person with a GitHub account still has to press Submit.
Send only public page data. Never include conversation history, keys, or private configuration.

## What happens next
1. Gauge, Lantern Works' data-QA process, picks up open `wrong-price` issues in its daily QA run.
2. It rechecks the vendor's page and records a **verbatim quote** and a **UTC check time**.
3. Outcome, posted as a reply on the issue:
   - **Corrected:** the row is updated with the new `evidence.quote` / `checked_at`, and the commit is linked.
   - **Held:** the row is temporarily kept out of rankings (`held_stale`) with a public reason while the discrepancy is unresolved.
   - **Rejected:** the vendor's page still matches our row. The quote is shown so you can see why.
4. Material discrepancies are held within one daily cycle. A disputed price is never left ranked once it's confirmed wrong.

Price data is CC BY 4.0 (see `LICENSE-DATA`). Reports are public GitHub issues.
