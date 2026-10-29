"""T22: embeddable live price badge reads the live feed; no baked prices, no reserved rows, credit line present."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_badge_files_built():
    js = (ROOT / "embed" / "badge.js").read_text(encoding="utf-8")
    assert "/api/v1/gpu-prices.json" in js and "CC BY 4.0" in js and "Lantern Works" in js
    assert '"reserved"' not in js.split("BUCKETS=")[1].split(";")[0]
    assert "held_stale" in js and "cheapest" not in js.lower()
    assert 'src="badge.js"' in (ROOT / "embed" / "badge.html").read_text(encoding="utf-8")


def test_embed_page_no_baked_prices_or_owner_name():
    s = (ROOT / "embed" / "index.html").read_text(encoding="utf-8")
    body = s.split("<h1>", 1)[1]
    assert not re.search(r"\$\d", body)
    assert "Frosty" not in s and "Connor" not in s and not re.search(r"commission[^.]{0,40}\d+ ?%", s, re.I)
    assert "/embed/" in (ROOT / "sitemap.xml").read_text(encoding="utf-8")
