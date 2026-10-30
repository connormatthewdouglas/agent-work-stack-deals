# 0.3.33 vs 0.3.32 (note for QA)

Package: `lantern-works-deals-mcp` 0.3.33 (PyPI, MCP Registry), hosted worker redeployed 2026-10-30.

Behaviour change (one):
- Stock claims stored on a price record (the vendor page stock count captured with the price, e.g. Oblivus) are now expired at build time once they are 8 h old, like Scout claims. In 0.3.32 they expired only at MCP call time, so a static page or JSON feed could keep showing an old in-stock claim (seen: Oblivus A100 PCIe checked 00:20Z, still in stock at 12:09Z). Code: `core/gpu_availability.availability_for` wraps the record path in `stale_guard`.

No change: tool names, inputs, outputs, ranking rules, the 8 h limit (`AVAIL_MAX_AGE_H`), `availability_expires_at`, page wording.

Tests and pipeline (not in the package):
- Staleness tests take their reference time from the feed instead of a fixed snapshot time or the wall clock (the cause of failed scheduled run 41028121450).
- Workflows commit the GPU index in a second commit, so it pins the commit that changed the feed.
- The scout-data branch starts the import on every snapshot push; the hourly cron stays as a backstop.
