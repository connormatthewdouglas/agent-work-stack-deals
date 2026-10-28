"""CI gate: no rendered page or API output may show a price as unknown / n/a / null / blank."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cnup", ROOT / "scripts" / "check_no_unknown_prices.py")
cnup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cnup)


def test_site_and_api_have_no_unknown_prices():
    probs = cnup.all_problems()
    assert not probs, "\n".join(probs[:40])


def test_detector_catches_bad_renders(tmp_path):
    f = cnup.ROOT / "_tmp_unknown_probe.html"
    try:
        f.write_text('<p class="meta">Price: unknown</p><table><thead><tr><th>Vendor</th><th>Price</th></tr></thead>'
                     '<tbody><tr><td>A</td><td>n/a</td></tr><tr><td>B</td><td></td></tr><tr><td>C</td><td>$1.99/hr</td></tr></tbody></table>')
        probs = cnup.page_problems(f)
    finally:
        f.unlink()
    assert len(probs) == 3, probs


def test_null_deal_prices_carry_label():
    import json
    d = json.loads((ROOT / "deals.json").read_text())
    missing = [x["id"] for x in d["deals"] if x.get("price_usd") is None and not (x.get("price_label") or "").strip()]
    assert not missing, missing


def test_compare_coverage_note_is_generated():
    src = (ROOT / "scripts" / "compare_pages.py").read_text()
    assert "4 of 7" not in src
    html = (ROOT / "compare" / "cheap-gpu-rental" / "index.html").read_text()
    assert "4 of 7" not in html
