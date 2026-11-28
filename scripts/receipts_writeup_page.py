"""P29: Receipts write-up page. Every tally is computed from the Receipts index at build time."""
from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import receipts_page

SLUG = "receipts/write-up"
# Display order and public labels for the recorded verdict keys. Counts are never stored here.
VERDICT_LABELS = (
    ("works", "Works"),
    ("works_with_caveats", "Works with caveats"),
    ("broken", "Broken"),
    ("deferred", "Deferred"),
)
REF = "receipts-writeup"


def _tests(source: bytes) -> list[dict]:
    return receipts_page.build(source)["tests"]


def format_iso_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%-d %B %Y")


def tested_dates(tests: list[dict]) -> list[str]:
    missing = [r["id"] for r in tests if not r.get("tested_at")]
    if missing:
        raise ValueError(f"Receipts records missing tested_at: {missing[:8]}")
    for r in tests:
        datetime.strptime(r["tested_at"], "%Y-%m-%d")
    return sorted({r["tested_at"] for r in tests})


def format_date_list(dates: list[str]) -> str:
    """Honest list of the actual tested_at days, not a filled-in range."""
    if not dates:
        raise ValueError("No tested_at dates in Receipts data")
    nice = [format_iso_date(d) for d in dates]
    if len(nice) == 1:
        return nice[0]
    if len(nice) == 2:
        return f"{nice[0]} and {nice[1]}"
    return ", ".join(nice[:-1]) + f", and {nice[-1]}"


def content_day(tests: list[dict]) -> str:
    """Sitemap lastmod: newest tested_at in the records, not a clock or git date."""
    dates = tested_dates(tests)
    return dates[-1]


def content_day_from_root(root: Path) -> str | None:
    path = root / "data" / "receipts-index.json"
    try:
        tests = _tests(path.read_bytes())
    except (OSError, ValueError, KeyError):
        return None
    if not tests:
        return None
    return content_day(tests)


def discover_case_pages(root: Path) -> list[dict]:
    """Public case pages already on disk (proof pack, plus any later case dirs)."""
    found: list[dict] = []
    seen: set[str] = set()
    rec = root / "receipts"
    for spec in receipts_page.PROOF_CASES:
        slug = spec["slug"]
        if (rec / slug / "index.html").is_file():
            found.append({"id": spec["id"], "slug": slug, "title_verdict": spec.get("title_verdict")})
            seen.add(slug)
    if rec.is_dir():
        for p in sorted(rec.iterdir()):
            if not p.is_dir() or p.name in seen or p.name == "write-up":
                continue
            if (p / "index.html").is_file() and re.match(r"^\d{3}-", p.name):
                found.append({"id": p.name[:3], "slug": p.name, "title_verdict": None})
    return found


def figures(tests: list[dict], case_pages: list[dict]) -> dict:
    counts = Counter(r["verdict"] for r in tests)
    known = {k for k, _ in VERDICT_LABELS}
    unknown = sorted(k for k in counts if k not in known)
    dates = tested_dates(tests)
    by_date = Counter(r["tested_at"] for r in tests)
    by_category = Counter(r["category"] for r in tests)
    by_registry = Counter(r["registry"] for r in tests)
    by_id = {r["id"]: r for r in tests}
    cases = []
    for c in case_pages:
        row = by_id.get(c["id"], {})
        cases.append({**c, "server": row.get("server"), "verdict": row.get("verdict")})
    broken = [r for r in tests if r["verdict"] == "broken"]
    house = next((r for r in tests if r["category"] == "house"), None)
    return {
        "total": len(tests),
        "counts": dict(counts),
        "unknown_verdicts": unknown,
        "dates": dates,
        "date_list": format_date_list(dates),
        "content_day": content_day(tests),
        "by_date": dict(by_date),
        "by_category": dict(by_category),
        "by_registry": dict(by_registry),
        "broken": broken,
        "cases": cases,
        "house": house,
    }


def _date_counts_sentence(fig: dict) -> str:
    parts = [f"{fig['by_date'][d]} on {format_iso_date(d)}" for d in fig["dates"]]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def render_body(g, fig: dict, doc: dict) -> str:
    e = html.escape
    base = g.BASE
    sep = "\u203a"
    pub = doc["publication"]
    counts = fig["counts"]
    # Tally rows follow VERDICT_LABELS, then any unexpected recorded keys.
    rows = list(VERDICT_LABELS) + [(k, k) for k in fig["unknown_verdicts"]]
    tally_rows = "".join(
        f"<tr><td>{e(label)}</td><td><code>{e(key)}</code></td><td>{counts.get(key, 0)}</td></tr>"
        for key, label in rows
    )
    cat = fig["by_category"]
    cat_bits = []
    for key, label in (("house", "house product"), ("reference", "reference"), ("community", "community")):
        if key in cat:
            cat_bits.append(f"{cat[key]} {label}")
    for key in sorted(k for k in cat if k not in {"house", "reference", "community"}):
        cat_bits.append(f"{cat[key]} {key}")
    cat_sentence = ", ".join(cat_bits[:-1]) + f", and {cat_bits[-1]}" if len(cat_bits) > 1 else (cat_bits[0] if cat_bits else "none")
    reg = fig["by_registry"]
    reg_parts = [f"{n} <code>{e(name)}</code>" for name, n in sorted(reg.items(), key=lambda kv: (-kv[1], kv[0]))]
    if len(reg_parts) == 1:
        reg_html = reg_parts[0]
    elif len(reg_parts) == 2:
        reg_html = f"{reg_parts[0]} and {reg_parts[1]}"
    else:
        reg_html = ", ".join(reg_parts[:-1]) + f", and {reg_parts[-1]}"

    case_links = []
    for c in fig["cases"]:
        label = c.get("server") or c["slug"]
        extra = f" ({c['title_verdict']})" if c.get("title_verdict") else ""
        case_links.append(
            f'<li><a href="{base}/receipts/{e(c["slug"])}/">#{e(c["id"])} {e(label)}</a>{e(extra)}</li>'
        )
    cases_html = (
        "<ul>" + "".join(case_links) + "</ul>"
        if case_links
        else "<p>No public case pages are published in this edition.</p>"
    )

    broken_html = []
    case_by_id = {c["id"]: c for c in fig["cases"]}
    for row in fig["broken"]:
        rid = row["id"]
        caveats = "".join(f"<li>{e(receipts_page.scrub_personal(c))}</li>" for c in (row.get("caveats") or []))
        caveats_block = f"<ul>{caveats}</ul>" if caveats else ""
        links = [f'<a href="{base}/receipts/#test-{e(rid)}">Index entry #{e(rid)}</a>']
        if rid in case_by_id:
            slug = case_by_id[rid]["slug"]
            links.append(f'<a href="{base}/receipts/{e(slug)}/">Case page</a>')
        broken_html.append(
            f'<article class="receipt" id="broken-{e(rid)}">\n'
            f"<h3>#{e(rid)} {e(receipts_page.scrub_personal(row['server']))}</h3>\n"
            f"<p><code>{e(row['package'])}</code> v{e(str(row['version']))} · tested {e(row['tested_at'])}</p>\n"
            f"<p>{e(receipts_page.scrub_personal(row['headline']))}</p>\n"
            f"<p><strong>Task:</strong> {e(receipts_page.scrub_personal(row['canonical_task']))}</p>\n"
            f"{caveats_block}"
            f"<p>{' · '.join(links)}</p>\n"
            f"</article>"
        )
    if not broken_html:
        broken_section = "<p>No records in this edition have the recorded verdict <code>broken</code>.</p>"
    else:
        broken_section = "\n".join(broken_html)

    house = fig["house"]
    if house:
        house_html = (
            f"<p>Record #{e(house['id'])} is the Lantern Works house product, "
            f"<code>{e(house['package'])}</code> version {e(str(house['version']))}, "
            f"tested {e(house['tested_at'])}. It is not an independent endorsement of today's release. "
            f'See the <a href="{base}/receipts/#test-{e(house["id"])}">index entry</a>.</p>'
        )
    else:
        house_html = ""

    date_counts = _date_counts_sentence(fig)
    total = fig["total"]
    n_broken = counts.get("broken", 0)
    n_cases = len(fig["cases"])

    body = (
        '<style>.receipt{border:1px solid #d1d5db;border-radius:10px;padding:1rem;margin:1rem 0;overflow-wrap:anywhere}'
        ".receipt h3{margin-top:0;font-size:1.15rem}.receipt code{white-space:normal}"
        ".receipt-policy{border-left:4px solid #f59e0b;padding-left:1rem;margin:1.25rem 0}"
        "table.tally{border-collapse:collapse;margin:1rem 0}"
        "table.tally th,table.tally td{border:1px solid #d1d5db;padding:.4rem .7rem;text-align:left}"
        "table.tally td:last-child{text-align:right}</style>\n"
        f'<nav class="crumbs"><a href="{base}/">Lantern Works</a> {sep} '
        f'<a href="{base}/receipts/">Receipts</a> {sep} Write-up</nav>\n'
        "<h1>Receipts write-up: what we tested, the tally, and what broke</h1>\n"
        f"<p>Lantern Works tested {total} MCP servers by installing each one, giving it a specific "
        "task, and checking the output against an independent ground truth. This page's counts, "
        "date list, and broken-case list are computed from the Receipts index when the site is "
        f"built, not typed in by hand. The records themselves are dated {e(fig['date_list'])} "
        f"({date_counts}; {total} in all). There is no filled-in day between those "
        "<code>tested_at</code> values.</p>\n"
        f'<p>The full record list is the <a href="{base}/receipts/">Receipts index</a>. '
        f'Machine-readable records: <a href="{base}/api/v1/receipts.json?ref={REF}">/api/v1/receipts.json</a>.</p>\n'
        "<h2>What we tested</h2>\n"
        f"<p>This edition has {total} records: {e(cat_sentence)}. "
        f"Install sources in the index are {reg_html}. Each record names the version tested, "
        "the canonical task, the ground truth it was graded against, and a headline finding.</p>\n"
        f"{house_html}"
        "<h2>The tally</h2>\n"
        "<p>Counts below are the number of records for each recorded <code>verdict</code> value "
        "in the Receipts index. The index page uses slightly different display wording for the "
        "same keys: “Worked” for <code>works</code>, “Worked with caveats” for "
        "<code>works_with_caveats</code>, “Failed tested task” for <code>broken</code>, and "
        "“Deferred — needs credentials” for <code>deferred</code>.</p>\n"
        '<div class="tscroll"><table class="tally">\n'
        "<thead><tr><th>Verdict</th><th>Recorded value</th><th>Count</th></tr></thead>\n"
        f"<tbody>{tally_rows}"
        f"<tr><th scope=\"row\">Total</th><td></td><td>{total}</td></tr>"
        "</tbody></table></div>\n"
        f"<p>Deferred means the promised task was not tested, not that the server is broken. "
        "Credential-gated tests used decoy credentials, so successful authenticated workflows "
        "were not tested.</p>\n"
        "<h2>What broke</h2>\n"
        f"<p>{n_broken} of {total} records have the recorded verdict <code>broken</code> "
        "(failed the dated, scoped task). Findings are the authored headlines and caveats from "
        "the index; they are not security certifications or current compatibility guarantees.</p>\n"
        f"{broken_section}\n"
        "<h2>Method</h2>\n"
        "<p>These are Pax-authored summaries of specific versions and tasks, published by "
        f"Lantern Works. The <code>tested_at</code> dates in this edition are {e(fig['date_list'])}. "
        "Evidence in the public index is authored summaries only: write-up and transcript "
        "filenames in the index JSON refer to project records that are not included with those "
        f"summaries. {n_cases} representative third-party "
        f'{"case has" if n_cases == 1 else "cases have"} a public proof-pack page '
        f'(excerpts and machine-readable evidence) under <a href="{base}/receipts/">/receipts/</a>.</p>\n'
        f"<aside class=\"receipt-policy\" aria-label=\"Verdict policy\"><h2>Verdict firewall</h2>"
        f"<p>{e(pub['verdict_policy'])}</p></aside>\n"
        "<h2>Receipts index and case pages</h2>\n"
        f'<p><a href="{base}/receipts/">All {total} dated summaries</a></p>\n'
        f"{cases_html}"
        f'<p>Need GPU prices in your own agent? <a href="{base}/quickstart/?ref={REF}">Try a free, cited comparison</a>. '
        f'Price methodology is documented separately at <a href="{base}/methodology/">/methodology/</a>.</p>\n'
    )
    return body


def write(g) -> list[str]:
    source = (g.ROOT / "data" / "receipts-index.json").read_bytes()
    doc = receipts_page.build(source)
    fig = figures(doc["tests"], discover_case_pages(g.ROOT))
    if sum(fig["counts"].values()) != fig["total"]:
        raise ValueError("Receipts write-up tally does not sum to the record count")
    title = "Receipts write-up: what we tested, the tally, and what broke"
    desc = (
        f"Lantern Works Receipts write-up: {fig['total']} MCP servers tested "
        f"({fig['date_list']}), with verdict counts and the cases that failed their dated task, "
        "computed from the Receipts index at build time."
    )
    url = f"{g.BASE}/{SLUG}/"
    body = render_body(g, fig, doc)
    path = g.ROOT / SLUG / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(g.page_shell(title, desc, url, body), encoding="utf-8")
    return [SLUG]
