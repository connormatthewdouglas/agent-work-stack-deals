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


def test_nonGPU_block_parses_cited_from_price_and_drops_unsourced_rows():
    import json, re
    from pathlib import Path
    t = (Path(__file__).resolve().parents[1] / "compare/cheapest-residential-proxies/index.html").read_text()
    items = json.loads(re.search(r'id="lw-price-block">(.*?)</script>', t).group(1).replace("<\\/", "</"))["items"]
    nine = [i for i in items if i["vendor"] == "9Proxy"][0]
    assert nine["price_usd"] == 0.018 and nine["unit"] == "per IP"
    assert {"price_usd": 0.68, "unit": "per GB"} in nine["price_options"]
    assert all(i["source_url"] and i["checked_at"] for i in items)
    assert not any(i["vendor"] == "DataImpulse" for i in items)


def test_compare_index_lists_gpu_pages_first_and_llms_links_it():
    t = (ROOT / "compare/index.html").read_text()
    llms = (ROOT / "llms.txt").read_text()
    assert "https://thelanternworks.com/compare/)" in llms and "## GPU comparison pages" in llms
    gpu_h2, tool_h2 = t.index("GPU price comparisons"), t.index("Tool and API comparisons")
    for f in glob.glob(str(ROOT / "compare/*/index.html")):
        s = Path(f).read_text()
        if 'http-equiv="refresh"' in s:
            continue
        slug = Path(f).parent.name
        pos = t.index(f"/compare/{slug}/")
        if "compare_gpu_prices" in s.split('id="lw-price-block">', 1)[1].split("</script>", 1)[0]:
            assert gpu_h2 < pos < tool_h2, slug
        else:
            assert pos > tool_h2, slug
