# Lantern Works GPU Price Index — methodology v1.0

**What it is:** a daily, per-GPU reference rental price for six NVIDIA GPUs, computed only from
Lantern Works' own sourced price rows (each row has a vendor source URL, verbatim quote and check time in the feed).

## Scope
| Series | Feed `gpu` values accepted | VRAM |
|---|---|---|
| H100 | H100, H100 SXM, H100 PCIe, H100 NVLink | 80 GB |
| A100 | A100, A100 SXM, A100 PCIe, A100 NVLink | 80 GB (40 GB rows are excluded, never mixed) |
| H200 | H200, H200 SXM | 141 GB |
| L40S | L40S | 48 GB |
| RTX 4090 | RTX 4090 | 24 GB |
| RTX 5090 | RTX 5090 | 32 GB |

Form factors (SXM/PCIe/NVLink) are pooled in v1.0 for coverage; per-form-factor series are a v1.1 candidate once each has ≥3 vendors.

## Which rows count
A snapshot row is **included** only if all are true:
1. `status == "ranked"` (held/stale rows never count).
2. Tier is on-demand class (on-demand, secure or community cloud, per-hour instances, including 8-GPU instances priced per GPU).
3. Not spot/interruptible/preemptible/bid/batch/serverless-preemptible (tier text matches `spot|interruptible|preempt|bid|batch|serverless`).
4. Not reserved/committed/monthly-dedicated (`reserv|month|dedicated|commit|N mo`).
5. Marketplace/aggregator rows count only if the vendor has **≥5 listings** for that GPU, read from `offer_count` in
   `api/v1/gpu-prices.json` at the last commit on that date. Unknown count → excluded (not assumed).

## Statistic
- Per vendor, take its **lowest qualifying per-GPU-hour rate** (`hourly_usd`), so one vendor = one vote.
- Index value = **median across vendors**, USD per GPU-hour, 4 decimals.
- Also published: minimum, vendor count, `low_coverage` (fewer than 3 vendors; don't headline these).
- **Monthly basis** = median × **730 hours** (same as the feed's `hours_per_month`). It's a basis for comparison, not a quote.

## Price change vs. composition change
The headline median moves when vendors are added. Each day after the first also carries a **matched-vendor change**:
the median over vendors present on both days, plus lists of vendors added and dropped. Only matched changes may be described as
"prices moved". A newly tracked cheap provider is a coverage change, not a market price cut.

## History
- Source: `data/gpu_pricing/snapshots/YYYY-MM-DD.json` (one per day, **starting 2026-10-27**). Each output day records the
  snapshot file's SHA-256 and the feed commit used for listing counts.
- Coverage grew a lot from Oct 27 to Oct 29 (e.g. H100 went from 4 to 9 vendors), so early movement is mostly composition.
  **Don't publish trend claims before 30 days of history** (per T21), and show history length next to any chart.

## Reproduce
```
git clone https://github.com/connormatthewdouglas/agent-work-stack-deals repo
python3 repo/scripts/gpu_index.py repo out   # writes out/gpu-price-index.json (audit trail: included/excluded row keys) + .csv
```
No price is entered by hand. Every value traces to a snapshot row with its `source_url` and `verified_at`.

## License and attribution (CC BY 4.0)
Data: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ . Code: MIT.

Attribution text (use as-is):
> Source: Lantern Works GPU Price Index (https://thelanternworks.com), licensed CC BY 4.0. Median on-demand rental price per GPU-hour across tracked vendors; methodology at https://thelanternworks.com/gpu/index/methodology/.

Short form: `Data: Lantern Works GPU Price Index, CC BY 4.0`.
