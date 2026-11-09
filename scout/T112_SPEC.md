# T112 Scout-side inputs (staged, schema 3.2 unchanged)
Data: t112_availability_rate_7d.json (builder: t112_build.py; read-only on Scout snapshot history in $SCOUT_DIR/out, which is scout/out in this repo; the work box used /workspace/lantern-scout/out).
Per (vendor, gpu_model, vram_gb, tier): checks_7d, known_checks_7d, in_stock_checks_7d, availability_rate_7d = in_stock/known
(unknown checks EXCLUDED, never counted as out of stock), known_share_7d, first/last_check_at, last_known_at, sufficient_sample (known>=12).
Per-row freshness inputs already in the enriched feed: availability_checked_at, availability_expires_at, plus T113 availability_reason(+_detail).
Mart must build: join on enrich key -> publish availability_rate_7d and expected_cost = rate / max(availability_rate_7d, floor) BESIDE the raw rate
in gpu-prices.json + MCP brief; label "estimate"; null when sufficient_sample is false or rate is null (unknown stays unknown); pick floor (suggest 0.05).
Caveats: rate is share of Scout checks (every 4h + multi refresh), not time-weighted; RunPod rows report the cheapest in-stock DC (rate ~1.0 by construction);
Vast marketplace rows are nearly always 1.0. Scout can run t112_build.py each cycle and push it to scout-data once Mart GOs.
