---
title: "GPU Rental Price Report: Week of Nov 2, 2026"
published: false
tags: gpu, ai, machinelearning, cloud
canonical_url: https://thelanternworks.com/
---

*Disclosure: some vendor links on Lantern Works are referral/affiliate links (currently RunPod, Thunder Compute, Vast.ai, Novita AI, Clore.ai, Ucartz and 99Stack Cloud). Lantern Works may earn a commission. Affiliate status does not affect rankings.*

This is the weekly GPU rental price report from [Lantern Works](https://thelanternworks.com/) for the week of Nov 2, 2026. Every number below comes from two public feeds, fetched live on **2026-11-02 at 09:14 ET**:

- [`gpu-prices.json`](https://thelanternworks.com/api/v1/gpu-prices.json): `feed_updated_at` **2026-11-02T12:59:30Z (2026-11-02 07:59 ET)**, 151 rates from 25 vendors
- [`gpu-price-changes.json`](https://thelanternworks.com/api/v1/gpu-price-changes.json): compares the daily snapshots dated **2026-11-01 and 2026-11-02**

All prices are **USD per GPU-hour** and cover compute only, so they leave out storage, egress, extra vCPU/RAM and taxes. "Cheapest" means cheapest among the providers we track. Check the vendor's own page before you spend money. Price data is licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (attribution: Lantern Works).

## What moved (2026-11-01 to 2026-11-02)

**2 down, 27 up, 2 new, 1 removed.**

| GPU | Vendor | Tier | Old | New | Change |
|---|---|---|---|---|---|
| A100 SXM 80GB | Vast.ai | Marketplace on-demand (verified; median per GPU) | $1.2156 | $1.117 | **-8.1%** |
| RTX 5090 32GB | Spheron | Marketplace/aggregator listing (page: "Live rates across 5+ providers"; on-demand) | $1.56 | $1.62 | **+3.8%** |
| RTX 4090 24GB | Vast.ai | Marketplace on-demand (verified; median per GPU) | $0.4544 | $0.4908 | **+8.0%** |
| A40 48GB | Vast.ai | Marketplace on-demand (verified) | $0.5344 | $0.6147 | **+15.0%** |
| B300 288GB | Verda (formerly DataCrunch) | On-demand instance (1x GPU) | $11.35 | $11.46 | +1.0% |
| GB300 288GB | Verda (formerly DataCrunch) | On-demand instance (1x GPU) | $13.05 | $13.18 | +1.0% |
| B200 180GB | Verda (formerly DataCrunch) | On-demand instance (1x GPU) | $8.869 | $8.958 | +1.0% |
| H200 SXM 141GB | Verda (formerly DataCrunch) | On-demand instance (1x GPU) | $6.25 | $6.313 | +1.0% |
| H100 SXM 80GB | Verda (formerly DataCrunch) | On-demand instance (1x GPU) | $4.793 | $4.841 | +1.0% |

Verda moved all 24 of its tracked rates up by 0.8% to 1.0% (on-demand and spot, from V100 to GB300); the table shows its top-end on-demand rows. Vast.ai's RTX PRO 6000 Server median barely changed ($1.7344 to $1.7337). Marketplace rows (Vast.ai, Spheron) are medians of host offers, so they swing more than list prices.

**New listings:** Vast.ai RTX PRO 6000 Max-Q 96GB at $2.1087 (Marketplace on-demand (verified)), Vast.ai V100 32GB at $0.1603 (Marketplace on-demand (verified)). **Removed:** Vast.ai RTX PRO 6000 Workstation 96GB (was $2.0385).

## Same GPU, 100 hours: what the spread costs

For an H100 SXM 80GB on-demand, single GPU and non-interruptible, 100 hours costs **$299.00** at Civo, compared with a **$399.00** median and **$484.10** at Verda (formerly DataCrunch). Across the 9 tracked rates that meet those rules, that is up to **$185.10** of difference in compute alone.

## Cheapest on-demand per GPU (non-interruptible)

Covers all 37 GPU variants with an on-demand rate in the feed, newest and largest first. "N-GPU minimum" means the vendor only sells that instance with N GPUs; the price is still per GPU.

| GPU | $/GPU-hr | Vendor | Tier | Page |
|---|---|---|---|---|
| B300 288GB | $8.99 | RunPod | On-demand (Secure Cloud) |  |
| GB300 288GB | $13.18 | Verda (formerly DataCrunch) | On-demand instance (1x GPU) |  |
| B200 180GB | $6.69 | Lambda | On-demand instance (8x GPU) | [B200](https://thelanternworks.com/gpu/b200-rental-price/) |
| H200 SXM 141GB | $3.99 | Hyperstack | On-demand | [H200](https://thelanternworks.com/gpu/h200-rental-price/) |
| H200 141GB | $4.47 | DigitalOcean GPU Droplets | On-demand | [H200](https://thelanternworks.com/gpu/h200-rental-price/) |
| H100 PCIe 80GB | $2.50 | Hyperstack | On-demand | [H100](https://thelanternworks.com/gpu/h100-rental-price/) |
| H100 NVLink 80GB | $2.60 | Hyperstack | On-demand | [H100](https://thelanternworks.com/gpu/h100-rental-price/) |
| H100 80GB (form not stated) | $2.8767 | 99Stack Cloud | On-demand | [H100](https://thelanternworks.com/gpu/h100-rental-price/) |
| H100 SXM 80GB | $2.99 | Civo | On-demand | [H100](https://thelanternworks.com/gpu/h100-rental-price/) |
| H100 NVL 94GB | $3.19 | RunPod | On-demand (Secure Cloud) |  |
| GH200 96GB | $2.29 | Lambda | On-demand instance (1x GPU) |  |
| MI300X 192GB | $2.39 | RunPod | On-demand (Secure Cloud) |  |
| A100 SXM 80GB | $1.05 | CloudRift | On-demand | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| A100 80GB | $1.09 | Thunder Compute | On-demand | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| A100 PCIe 80GB | $1.35 | Hyperstack | On-demand | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| A100 NVLink 80GB | $1.40 | Hyperstack | On-demand | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| A100 40GB | $0.89 | Jarvislabs | On-demand | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| A100 SXM 40GB | $1.625 | Verda (formerly DataCrunch) | On-demand instance (1x GPU) | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| A100 PCIe 40GB | $1.99 | Lambda | On-demand instance (1x GPU) | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| L40S 48GB | $0.63 | CloudRift | On-demand | [L40S](https://thelanternworks.com/gpu/l40s-rental-price/) |
| L40 48GB | $0.79 | Thunder Compute | On-demand |  |
| L4 24GB | $0.59 | RunPod | On-demand (Secure Cloud) |  |
| A40 48GB | $0.59 | RunPod | On-demand (Secure Cloud) |  |
| RTX PRO 6000 Server 96GB | $2.49 | RunPod | On-demand (Secure Cloud) |  |
| RTX PRO 6000 Workstation 96GB | $2.59 | RunPod | On-demand (Secure Cloud) |  |
| RTX PRO 6000 96GB | $2.671 | Verda (formerly DataCrunch) | On-demand instance (1x GPU) |  |
| RTX 6000 Ada 48GB | $0.99 | RunPod | On-demand (Secure Cloud) |  |
| RTX A6000 48GB | $0.35 | Thunder Compute | On-demand | [RTX A6000](https://thelanternworks.com/gpu/rtx-a6000-rental-price/) |
| RTX 5090 32GB | $0.65 | CloudRift | On-demand | [RTX 5090](https://thelanternworks.com/gpu/rtx-5090-rental-price/) |
| RTX 4090 24GB | $0.42 | Nova Cloud / RunC.AI (tie) | On-demand | [RTX 4090](https://thelanternworks.com/gpu/rtx-4090-rental-price/) |
| RTX 3090 24GB | $0.50 | RunPod | On-demand (Secure Cloud) |  |
| RTX A5000 24GB | $0.27 | RunPod | On-demand (Secure Cloud) |  |
| RTX A4000 16GB | $0.25 | RunPod | On-demand (Secure Cloud) |  |
| Quadro RTX 6000 24GB | $0.69 | Lambda | On-demand instance (1x GPU) |  |
| A10 24GB | $1.29 | Lambda | On-demand instance (1x GPU) |  |
| T4 16GB | $0.45 | E2E Networks | On-demand |  |
| V100 16GB | $0.238 | Verda (formerly DataCrunch) | On-demand instance (1x GPU) |  |

Lambda's B200 rate is for an 8-GPU instance; its single-GPU B200 instance is $6.99.

## Cheapest spot / interruptible per GPU

These instances can be preempted by the vendor, so they sit in their own table. Don't compare them directly with the on-demand rates above.

| GPU | $/GPU-hr | Vendor | Tier | Page |
|---|---|---|---|---|
| B300 288GB | $5.73 | Verda (formerly DataCrunch) | Spot instance (1x GPU) |  |
| GB300 288GB | $6.59 | Verda (formerly DataCrunch) | Spot instance (1x GPU) |  |
| B200 180GB | $4.479 | Verda (formerly DataCrunch) | Spot instance (1x GPU) | [B200](https://thelanternworks.com/gpu/b200-rental-price/) |
| H200 SXM 141GB | $3.157 | Verda (formerly DataCrunch) | Spot instance (1x GPU) | [H200](https://thelanternworks.com/gpu/h200-rental-price/) |
| H100 PCIe 80GB | $2.00 | Hyperstack | Spot VM | [H100](https://thelanternworks.com/gpu/h100-rental-price/) |
| H100 SXM 80GB | $2.421 | Verda (formerly DataCrunch) | Spot instance (1x GPU) | [H100](https://thelanternworks.com/gpu/h100-rental-price/) |
| A100 PCIe 80GB | $1.08 | Hyperstack | Spot VM | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| A100 SXM 80GB | $1.135 | Verda (formerly DataCrunch) | Spot instance (1x GPU) | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| A100 SXM 40GB | $0.8125 | Verda (formerly DataCrunch) | Spot instance (1x GPU) | [A100](https://thelanternworks.com/gpu/a100-rental-price/) |
| L40S 48GB | $0.96 | Verda (formerly DataCrunch) | Spot instance (1x GPU) | [L40S](https://thelanternworks.com/gpu/l40s-rental-price/) |
| RTX PRO 6000 96GB | $1.336 | Verda (formerly DataCrunch) | Spot instance (1x GPU) |  |
| RTX 6000 Ada 48GB | $0.7565 | Verda (formerly DataCrunch) | Spot instance (1x GPU) |  |
| RTX A6000 48GB | $0.418 | Verda (formerly DataCrunch) | Spot instance (1x GPU) | [RTX A6000](https://thelanternworks.com/gpu/rtx-a6000-rental-price/) |
| RTX 4090 24GB | $0.16 | SaladCloud | Lowest (Batch) priority, interruptible | [RTX 4090](https://thelanternworks.com/gpu/rtx-4090-rental-price/) |
| V100 16GB | $0.119 | Verda (formerly DataCrunch) | Spot instance (1x GPU) |  |

## Cheapest community cloud per GPU

RunPod's Community Cloud runs on third-party hosts. The feed marks it as not interruptible, but it is a different service level from on-demand, so it gets its own table too.

| GPU | $/GPU-hr | Vendor | Tier |
|---|---|---|---|
| B300 288GB | $6.94 | RunPod | On-demand (Community Cloud) |
| B200 180GB | $5.98 | RunPod | On-demand (Community Cloud) |
| H200 141GB | $3.59 | RunPod | On-demand (Community Cloud) |
| H100 PCIe 80GB | $1.99 | RunPod | On-demand (Community Cloud) |
| H100 SXM 80GB | $2.69 | RunPod | On-demand (Community Cloud) |
| H100 NVL 94GB | $2.59 | RunPod | On-demand (Community Cloud) |
| A100 PCIe 80GB | $1.19 | RunPod | On-demand (Community Cloud) |
| A100 SXM 80GB | $1.39 | RunPod | On-demand (Community Cloud) |
| L40S 48GB | $0.79 | RunPod | On-demand (Community Cloud) |
| RTX PRO 6000 Max-Q 96GB | $1.64 | RunPod | On-demand (Community Cloud) |
| RTX PRO 6000 Server 96GB | $1.69 | RunPod | On-demand (Community Cloud) |
| RTX PRO 6000 Workstation 96GB | $1.69 | RunPod | On-demand (Community Cloud) |
| RTX 6000 Ada 48GB | $0.74 | RunPod | On-demand (Community Cloud) |
| RTX A6000 48GB | $0.33 | RunPod | On-demand (Community Cloud) |
| RTX 5090 32GB | $0.69 | RunPod | On-demand (Community Cloud) |
| RTX 4090 24GB | $0.34 | RunPod | On-demand (Community Cloud) |
| RTX 3090 24GB | $0.22 | RunPod | On-demand (Community Cloud) |
| RTX A4000 16GB | $0.17 | RunPod | On-demand (Community Cloud) |
| V100 PCIe 16GB | $0.19 | RunPod | On-demand (Community Cloud) |
| V100 SXM2 16GB | $0.23 | RunPod | On-demand (Community Cloud) |

**Not ranked above:** marketplace medians (Vast.ai, Clore.ai, Spheron), serverless per-second rates (Modal, Koyeb), reservations and commitments (Hyperstack, CloudRift) and monthly dedicated servers (Ucartz) are separate tiers. **Held out of every table and of "What moved" (`held_stale`):** Beam, Clore.ai, CloudRift, Runcrate, SimplePod and TensorDock. For Clore.ai and CloudRift only the flagged rows are held (thin Clore.ai markets, and CloudRift commitment rates no longer on its pricing page); their other live rows stay in the feed.

## Compare vendors

- [RunPod vs Verda](https://thelanternworks.com/compare/runpod-vs-verda-gpu-prices/)
- [Lambda vs RunPod](https://thelanternworks.com/compare/lambda-vs-runpod-gpu-prices/)
- [CoreWeave vs Nebius](https://thelanternworks.com/compare/coreweave-vs-nebius-gpu-prices/)
- [Daily price changes](https://thelanternworks.com/gpu/changes/)

## Get this data yourself

- Live comparison: https://thelanternworks.com/
- Feeds: https://thelanternworks.com/api/v1/gpu-prices.json and https://thelanternworks.com/api/v1/gpu-price-changes.json (CC BY 4.0)
- Methodology: https://thelanternworks.com/methodology/
- MCP server: `lantern-works-deals-mcp` on PyPI. Its `get_price_changes` and `compare_gpu_prices` tools return these feeds to your agent.
- Spot a wrong price? https://thelanternworks.com/report-price/
