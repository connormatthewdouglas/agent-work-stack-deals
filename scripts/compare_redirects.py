"""Reversed /compare/ URLs (e.g. /compare/runpod-vs-lambda-gpu-prices/) -> the existing page. Each stub is noindex,
has a canonical to the real page and a meta refresh, and is kept out of the sitemap. Derived from the compare/ pages
that exist, so new two-vendor comparisons get a reversed stub automatically."""
from __future__ import annotations

import html
import re
from pathlib import Path

MARK = "<!-- compare-redirect-stub -->"


def write_all(g) -> list[str]:
    root = Path(g.ROOT) / "compare"
    for d in root.iterdir():  # drop old stubs first, so removed pages don't leave redirects behind
        f = d / "index.html"
        if f.is_file() and MARK in f.read_text(encoding="utf-8"):
            f.unlink()
            d.rmdir()
    made = []
    for d in sorted(root.iterdir()):
        m = re.fullmatch(r"([a-z0-9-]+?)-vs-([a-z0-9-]+?)-gpu-prices", d.name)
        if not (m and (d / "index.html").is_file()) or "-vs-" in m.group(1) or "-vs-" in m.group(2):
            continue
        rev = root / f"{m.group(2)}-vs-{m.group(1)}-gpu-prices"
        if rev.exists():
            continue
        target = f"{g.BASE}/compare/{d.name}/"
        page = g.page_shell(f"Redirecting to {d.name.replace('-', ' ')}", "This comparison lives at another URL.", target,
                            f'  <p>This comparison is at <a href="{html.escape(target)}">{html.escape(target)}</a>.</p>\n',
                            robots="noindex,follow")
        page = page.replace("<head>", f'<head>\n  {MARK}\n  <meta http-equiv="refresh" content="0; url={html.escape(target)}" />', 1)
        rev.mkdir()
        (rev / "index.html").write_text(page, encoding="utf-8")
        made.append(rev.name)
    return made  # not sitemap paths


# Retired duplicate deal records -> the record that carries the vendor's prices (audit E3). noindex, not in sitemap.
RETIRED_DEALS = {"cloreai-001": "clore-ai"}


def write_retired_deals(g) -> list[str]:
    made = []
    for old, new in RETIRED_DEALS.items():
        d = Path(g.ROOT) / "deals" / old
        target = f"{g.BASE}/deals/{new}/"
        page = g.page_shell("This deal moved", "This deal record was merged into another page.", target,
                            f'  <p>This deal is now at <a href="{html.escape(target)}">{html.escape(target)}</a>.</p>\n',
                            robots="noindex,follow")
        page = page.replace("<head>", f'<head>\n  {MARK}\n  <meta http-equiv="refresh" content="0; url={html.escape(target)}" />', 1)
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(page, encoding="utf-8")
        made.append(old)
    return made
