"""T73 F2: the live price checker counts only displayed prices ($x/h) in visible text."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_gpu_sources as c  # noqa: E402

PAGE = """<html><head><style>.p{width:2.248px}</style><script>var old = "$2.248/h";</script></head><body>
<svg viewBox="0 0 24 24"><path d="M12.2486 4.1L2.248 9z"/></svg>
<img src="/img/a100-2.248.png" srcset="/img/a100-2.248@2x.png 2x" data-price="$2.248/h" alt="">
<div data-rate="2.248">1x A100 SXM4 80GB 22 120 GB 80 GB $2.270/h $1.135/h</div>
<p>Oblivus On-Demand: $ 3.50 /hr</p></body></html>"""


def test_price_only_in_image_path_data_does_not_match():
    text = c.visible_text(PAGE)
    assert "2.248" not in text
    assert not c.price_found("2.248", "1x A100 SXM4 80GB 22 120 GB 80 GB $2.248/h", text)


def test_displayed_price_matches():
    text = c.visible_text(PAGE)
    assert c.price_found("2.270", "1x A100 SXM4 80GB 22 120 GB 80 GB $2.270/h", text)
    assert c.price_found("1.135", "$2.270/h $1.135/h", text)
    assert c.price_found("3.5", "On-Demand: $3.5/hr", text)  # same amount, $ x /hr spacing


def test_bare_number_or_prefix_is_not_a_price():
    assert not c.price_found("2.27", "$2.27/h", "model 2.27 GB")
    assert not c.price_found("2.2", "$2.2/h", "$2.270/h")
    assert not c.price_found("2.270", "$2.270/h", "$2.270/month")
