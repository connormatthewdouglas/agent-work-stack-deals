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


def test_client_rendered_quote_fails_after_7_days(monkeypatch):
    """Gauge T73 F1-F6 #7: the 9Proxy script-string exception is warning-only for at most 7 days."""
    from datetime import datetime, timezone
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("cgs7", "scripts/check_gpu_sources.py")
    m = importlib.util.module_from_spec(spec); sys.modules["cgs7"] = m; spec.loader.exec_module(m)
    doc = {"checked_at": "2026-10-27T02:54:00-04:00"}
    assert m.quote_age_days(doc, datetime(2026, 11, 2, 12, tzinfo=timezone.utc)) < 7
    assert m.quote_age_days(doc, datetime(2026, 11, 3, 12, tzinfo=timezone.utc)) > m.MAX_UNRENDERED_AGE_DAYS
    rendered = m.visible_text("<p>Enterprise Package 10000 GB $0.68 /GB $3.00/GB</p>")
    assert m.price_found("0.68", "Starting from $0.68/GB", rendered)
    assert not m.price_found("0.68", "Starting from $0.68/GB", m.visible_text('<script>"Starting from $0.68/GB"</script>'))


def test_spheron_no_capacity_variant_is_a_warning_pattern():
    import importlib.util, re, sys
    spec = importlib.util.spec_from_file_location("cgs8", "scripts/check_gpu_sources.py")
    m = importlib.util.module_from_spec(spec); sys.modules["cgs8"] = m; spec.loader.exec_module(m)
    pat = m.CAPACITY_VARIANT["Spheron"].format(gpu=re.escape("RTX 5090"))
    assert re.search(pat, "On Spheron the NVIDIA RTX 5090 has no capacity right now. $0.89/hr per GPU is the last rate")
    assert not re.search(pat, "On Spheron the NVIDIA RTX 5090 is $1.62/hr per GPU, billed per minute")
    assert not re.search(pat, "On Spheron the NVIDIA L40S has no capacity right now")


# --- Stale vs missing/changed gate split (Bjorn 2026-11-17 sturdiness pass) ---
# The live-check used to FLAG stale rows together with really missing prices
# (scheduled run 43956407376 mixed 3 stale Cirrascale/Clore rows with 12 Verda
# "price not found" flags). Age-only is a warning; missing or changed still fail.

from datetime import datetime, timezone  # noqa: E402

_NOW = datetime(2026, 11, 16, 21, 5, 5, tzinfo=timezone.utc)
_STALE_AT = "2026-11-09T04:33:11+00:00"  # same stamp as Cirrascale on run 43956407376 (184.5 h old at _NOW)
_FRESH_AT = "2026-11-16T12:00:00+00:00"
_URL = "https://example.test/pricing"
_PRESENT = "<html><body><p>1x H100 80GB $2.00/h</p></body></html>"
_CHANGED = "<html><body><p>1x H100 80GB $2.50/h</p></body></html>"
_MISSING = "<html><body><p>1x H100 80GB currently unavailable</p></body></html>"


def _src_doc(verified_at, *, held=False):
    rec = {
        "gpu": "H100",
        "tier": "On-demand",
        "quote": "1x H100 80GB $2.00/h",
        "source_url": _URL,
        "verified_at": verified_at,
        "checked_at": verified_at,
        "hourly_usd": 2.00,
    }
    if held:
        rec["stale"] = {"reason": "held for test", "auto": True}
    return {
        "vendor": "TestVendor",
        "source_url": _URL,
        "checked_at": verified_at,
        "records": [rec],
    }


def _eval(doc, html, now=_NOW):
    # check_schema=False: fixtures are classification-only, not full vendor files.
    return c.evaluate_sources([doc], [], offline=False, pages={_URL: (200, html)}, now=now, check_schema=False)


def test_stale_row_warns_and_does_not_fail():
    """A row past the 7-day threshold whose quoted price is still on the page is a warning, not a failure."""
    doc = _src_doc(_STALE_AT)
    before = doc["records"][0]["verified_at"]
    flags, warnings, checked = _eval(doc, _PRESENT)
    assert flags == []
    assert checked == 1
    assert len(warnings) == 1
    w = warnings[0]
    assert w.startswith("stale (price still on the page): TestVendor H100 (On-demand):")
    assert "last verified_at 2026-11-09T04:33:11+00:00" in w
    assert "184.5 h old" in w
    assert "passed 168 h / 7 day threshold" in w
    # Never refresh a timestamp to make a row look fresh.
    assert doc["records"][0]["verified_at"] == before == _STALE_AT


def test_missing_price_fails():
    """A quoted price that is really absent from the page stays a FAIL, even when the row is fresh."""
    flags, warnings, checked = _eval(_src_doc(_FRESH_AT), _MISSING)
    assert checked == 1
    assert any(f.startswith("price not found on page (re-check by hand): TestVendor H100 (On-demand)")
               and "missing ['2.00']" in f for f in flags)
    assert not any(w.startswith("stale ") or w.startswith("stale(") for w in warnings)


def test_changed_price_fails():
    """A page that now shows a different amount is the same FAIL as a missing price (quoted token not found)."""
    flags, warnings, checked = _eval(_src_doc(_FRESH_AT), _CHANGED)
    assert checked == 1
    assert any(f.startswith("price not found on page (re-check by hand): TestVendor H100 (On-demand)")
               and "missing ['2.00']" in f and "$2.00/h" in f for f in flags)
    assert not any("2.50" in f and "missing" not in f for f in flags)
    assert not any(w.startswith("stale ") or w.startswith("stale(") for w in warnings)


def test_stale_row_whose_price_is_also_missing_fails():
    """Stale age does not demote a missing price to a warning; the row still fails."""
    doc = _src_doc(_STALE_AT)
    before = doc["records"][0]["verified_at"]
    flags, warnings, checked = _eval(doc, _MISSING)
    assert checked == 1
    assert any(f.startswith("price not found on page (re-check by hand): TestVendor H100 (On-demand)")
               and "missing ['2.00']" in f for f in flags)
    assert not any(w.startswith("stale ") or w.startswith("stale(") for w in warnings)
    assert doc["records"][0]["verified_at"] == before == _STALE_AT

