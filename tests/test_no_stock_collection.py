"""rel055 (Scout): Jarvislabs and Thunder Compute stock is labelled 'unmeasurable (no stock collection)' on /gpu/;
their cited prices stay."""
import json, re
from pathlib import Path
from core.gpu import unmeasurable_reason, NO_STOCK_COLLECTION_LABEL
ROOT = Path(__file__).resolve().parents[1]


def test_reason():
    assert unmeasurable_reason("Jarvislabs") == NO_STOCK_COLLECTION_LABEL == "unmeasurable (no stock collection)"
    assert unmeasurable_reason("Thunder Compute") == NO_STOCK_COLLECTION_LABEL
    assert unmeasurable_reason("Hyperstack") == "account required"


def test_pages_label_rows_and_keep_prices():
    html = (ROOT / "gpu" / "price-comparison" / "index.html").read_text()
    rows = [r for r in re.findall(r"<tr[ >].*?</tr>", html, re.S) if re.search(r">(Jarvislabs|Thunder Compute)</a>", r)]
    assert rows
    for r in rows:
        if NO_STOCK_COLLECTION_LABEL not in r:
            continue
        assert "$" in r  # cited price still shown
    assert sum(NO_STOCK_COLLECTION_LABEL in r for r in rows) >= 1
    feed = json.loads((ROOT / "api" / "v1" / "gpu-prices.json").read_text())
    rates = [r for r in feed["rates"] if r.get("advertiser") in ("Jarvislabs", "Thunder Compute")]
    assert rates and all(r.get("price_usd") is not None for r in rates)
    cov = (ROOT / "gpu" / "index.html").read_text()
    assert NO_STOCK_COLLECTION_LABEL in cov
