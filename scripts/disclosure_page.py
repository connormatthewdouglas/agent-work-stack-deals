"""/disclosure/: affiliate commission disclosure."""
from __future__ import annotations

from pathlib import Path

PATH = "disclosure"
ROOT = Path(__file__).resolve().parents[1]


def write(g) -> str:
    base = g.BASE
    body = f"""  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › Disclosure</nav>
  <h1>Affiliate disclosure</h1>
  <p>Lantern Works may earn a commission when you buy from some vendors we link to. This never changes the prices shown or the ranking order.</p>
  <p>Rankings follow the price and freshness rules on our <a href="{base}/methodology/">Methodology</a> page (<a href="{base}/methodology/#placement">Customers buy data, never placement</a>). No vendor can pay to rank higher. Referral links are labelled.</p>
"""
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell(
        "Affiliate disclosure | Lantern Works",
        "Lantern Works may earn a commission when you buy from some vendors we link to. This never changes prices shown or ranking order.",
        f"{base}/{PATH}/",
        body,
    ), encoding="utf-8")
    return PATH
