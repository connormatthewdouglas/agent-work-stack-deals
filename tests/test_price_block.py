import glob, json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def _block(f):
    m = re.search(r'<script type="application/json" id="lw-price-block">(.*?)</script>', Path(f).read_text(), re.S)
    return json.loads(m.group(1)) if m else None

def test_every_gpu_rental_page_has_price_block():
    fs = glob.glob(str(ROOT / "gpu/*-rental-price/index.html"))
    assert fs
    for f in fs:
        b = _block(f)
        assert b and b["items"], f
        prices = [i["usd_per_hr"] for i in b["items"]]
        assert prices == sorted(prices), f
        for i in b["items"]:
            assert {"model", "vendor", "usd_per_hr", "checked_at"} <= set(i)

def test_live_compare_pages_have_price_block_and_llms_lists_them():
    llms = (ROOT / "llms.txt").read_text()
    assert "compare_gpu_prices" in llms and "brief" in llms and "/stats.json" in llms
    for f in glob.glob(str(ROOT / "compare/*/index.html")):
        if "http-equiv=\"refresh\"" in Path(f).read_text():
            continue
        assert _block(f), f
        assert "/" + str(Path(f).parent.relative_to(ROOT)) + "/" in llms
