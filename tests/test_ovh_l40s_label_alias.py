"""OVH L40S quote: same SKU and prices, page corrected HBM2 -> GDDR6."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_gpu_prices as R  # noqa: E402

OLD = "l40s-90 90 GB 15 1x L40S ( 48 GB HBM2) 400 GB NVMe 8 Gbit/s 8 Gbit/s max. $1.8 $1,296"
NEW_PAGE = (
    "Name Memory vCore GPU Storage Public network Private network "
    "l40s-90 90 GB 15 1x L40S ( 48 GB GDDR6) 400 GB NVMe 8 Gbit/s 8 Gbit/s max. $1.8 $1,296 "
    "l40s-180 180 GB 30 2x L40S ( 48 GB GDDR6) 400 GB NVMe 16 Gbit/s 16 Gbit/s max. $3.6 $2,592"
)
REC = {
    "vendor": "OVHcloud (US)",
    "gpu": "L40S",
    "tier": 'Public Cloud GPU instance, hourly ("Price ( excl. taxes / hour)")',
    "price_usd": 1.8,
    "hourly_usd": 1.8,
    "source_url": "https://us.ovhcloud.com/public-cloud/prices/",
    "evidence": {"quote": OLD, "source_url": "https://us.ovhcloud.com/public-cloud/prices/"},
}


def test_ovh_l40s_hbm2_to_gddr6_alias_parses_same_price():
    # Without the alias the old HBM2 context is not on the page.
    bare = {**REC, "source_url": "https://example.com/not-ovh", "evidence": {**REC["evidence"]}}
    price, quote, msg = R.parse_listed(bare, NEW_PAGE)
    assert price is None and "not found" in msg
    price, quote, msg = R.parse_listed(REC, NEW_PAGE)
    assert price == "1.8" and msg == "parsed"
    assert "GDDR6" in quote and "l40s-90" in quote
