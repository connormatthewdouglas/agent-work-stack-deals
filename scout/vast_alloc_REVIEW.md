# Vast per-allocation wider-gpu rows

QA approved this change. It is live on the work box and is a behavior change on top of the path-only collector move.

`wider_gpu.vast` keeps one row per `(model, VRAM, num_gpus)`. A 1-GPU offer and an 8-GPU offer are not averaged together. The published `price_usd_hr` is still the median per-GPU `dph_total / num_gpus` inside that allocation. Each row sets `gpu_count` and `min_gpus` to that allocation size, and the tier is `Marketplace on-demand (verified) (Nx GPU)`. The hold is unchanged and still per row: fewer than `MIN_MARKET_OFFERS` distinct `machine_id` blanks the price.

`run_cycle.sh` raises the wider-step default timeout from 180s to 300s (`WGPU_TIMEOUT`). Nothing else in that script changed on the box.

The move still points `SCOUT_DIR` at the script directory. That is the only difference between the box `run_cycle.sh` (sha256 `53fb83b33f16c358f8e5c1d3047f446c34ae3fe27ac239cc903d7bb9a593011e`) and `scout/run_cycle.sh`.
