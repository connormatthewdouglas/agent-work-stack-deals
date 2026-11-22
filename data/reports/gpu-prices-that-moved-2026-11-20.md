---
title: "GPU prices that moved: week to 2026-11-20"
date: 2026-11-20
---

# GPU prices that moved: week to 2026-11-20

Every week we compare a snapshot of our GPU price feed with the one from seven days earlier and list the biggest moves. This is the first edition, comparing the **2026-11-20** snapshot with the **2026-11-13** snapshot. Prices are USD per GPU-hour. Figures below were recomputed from the live public feeds; the current feed's `feed_updated_at` was **2026-11-22T03:09:50Z**. The prices in the tables are the last ranked hourly price on or before each snapshot date, so later re-checks of the same rate do not change the comparison.

**Scope:** tracked providers only, not the whole market. "Cheapest" anywhere on this site means cheapest among the providers we track. Spot/interruptible and on-demand prices are never mixed: each row says which it is. Vendors whose data is currently held as stale in this live feed are excluded, as are reserved, community, marketplace and monthly-billed rows.

![Chart of the five biggest tracked price moves](moved-chart.svg)

## The five biggest moves

| Vendor | GPU (1x) | Type | Prior (2026-11-13) | Now (2026-11-20) | Change | Row verified | Source |
|---|---|---|---|---|---|---|---|
| Verda (formerly DataCrunch) | B300 | on-demand | $12.2900 | $13.0500 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | B300 | spot/interruptible | $6.1450 | $6.5250 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | GB300 | on-demand | $14.1300 | $15.0100 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | GB300 | spot/interruptible | $7.0670 | $7.5040 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | RTX PRO 6000 | on-demand | $2.8080 | $2.9810 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |

## What we saw

- Of the eligible hourly rows, **24** changed price over the week, and all of them were Verda (formerly DataCrunch) rows, every one an increase. Other tracked vendors' eligible hourly rows did not change in this window.
- Verda (formerly DataCrunch)'s spot rows moved by the same percentage as their matching on-demand rows, so the increases look like a lineup-wide change. We have no vendor explanation for it, and we are not guessing at one.
- Several rows tie at 6.2%; ties are ordered alphabetically by vendor and GPU, then by VRAM and type. The full list of moves is in [moves.json](moves.json) and in the table below.

## All 24 moves

VRAM is shown where two rows would otherwise share a GPU name.

| Vendor | GPU (1x) | Type | Prior (2026-11-13) | Now (2026-11-20) | Change | Row verified | Source |
|---|---|---|---|---|---|---|---|
| Verda (formerly DataCrunch) | B300 268GB | on-demand | $12.2900 | $13.0500 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | B300 268GB | spot/interruptible | $6.1450 | $6.5250 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | GB300 288GB | on-demand | $14.1300 | $15.0100 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | GB300 288GB | spot/interruptible | $7.0670 | $7.5040 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | RTX PRO 6000 96GB | on-demand | $2.8080 | $2.9810 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | RTX PRO 6000 96GB | spot/interruptible | $1.4040 | $1.4910 | +6.2% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | H100 SXM 80GB | on-demand | $5.1890 | $5.5080 | +6.1% | 2026-11-20 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | H100 SXM 80GB | spot/interruptible | $2.5950 | $2.7540 | +6.1% | 2026-11-20 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | H200 SXM 141GB | on-demand | $6.6350 | $7.0430 | +6.1% | 2026-11-20 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | H200 SXM 141GB | spot/interruptible | $3.3180 | $3.5220 | +6.1% | 2026-11-20 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | RTX A6000 48GB | on-demand | $0.8790 | $0.9330 | +6.1% | 2026-11-20 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | RTX A6000 48GB | spot/interruptible | $0.4395 | $0.4665 | +6.1% | 2026-11-20 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | RTX 6000 Ada 48GB | on-demand | $1.5900 | $1.6710 | +5.1% | 2026-11-19 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | RTX 6000 Ada 48GB | spot/interruptible | $0.7950 | $0.8355 | +5.1% | 2026-11-19 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | V100 16GB | on-demand | $0.2440 | $0.2560 | +4.9% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | V100 16GB | spot/interruptible | $0.1220 | $0.1280 | +4.9% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | L40S 48GB | on-demand | $1.9980 | $2.0790 | +4.1% | 2026-11-18 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | L40S 48GB | spot/interruptible | $0.9990 | $1.0400 | +4.1% | 2026-11-18 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | A100 SXM 80GB | on-demand | $2.3740 | $2.4700 | +4.0% | 2026-11-20 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | A100 SXM 80GB | spot/interruptible | $1.1870 | $1.2350 | +4.0% | 2026-11-20 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | B200 180GB | on-demand | $9.4140 | $9.7470 | +3.5% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | B200 180GB | spot/interruptible | $4.7070 | $4.8740 | +3.5% | 2026-11-20 | [vendor page](https://api.datacrunch.io/v1/instance-types) |
| Verda (formerly DataCrunch) | A100 SXM 40GB | on-demand | $1.6910 | $1.7330 | +2.5% | 2026-11-17 | [vendor page](https://verda.com/pricing) |
| Verda (formerly DataCrunch) | A100 SXM 40GB | spot/interruptible | $0.8455 | $0.8665 | +2.5% | 2026-11-17 | [vendor page](https://verda.com/pricing) |

## Method

Prices come from the daily Lantern Works history feed (change-point series, hourly-equivalent USD per GPU). For each series we take the last price on or before each snapshot date, keep series ranked at both dates, and compute percent change as (new - old) / old. Each row's "verified" date is when that snapshot price was last confirmed on the vendor's page or API; prices can change after that, so check the vendor page before buying.

## Disclosure

Some vendors in our feed have referral links, and Lantern Works may earn a commission if you sign up through them. Referral status never affects ranking or which moves are listed. None of the five rows above carries a referral link.

Data: [Lantern Works GPU price history](https://thelanternworks.com/api/v1/gpu-prices/history.json) and [current feed](https://thelanternworks.com/api/v1/gpu-prices.json), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: Lantern Works (https://thelanternworks.com). Spot and on-demand figures are provider-listed rates, not guarantees of availability. Found a wrong price? [Report it](https://thelanternworks.com/report-price/).
