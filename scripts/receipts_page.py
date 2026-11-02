"""Publish the approved Pax summaries without inventing missing public evidence."""
from __future__ import annotations

import hashlib
import html
import json
from collections import Counter

SOURCE_SHA256 = "ebcd0b1b2524585dd343efcd7c4eeb0b560f71e4950dcb88bea069e6736be517"
LABELS = {"works": "Worked", "works_with_caveats": "Worked with caveats", "broken": "Failed tested task",
          "deferred": "Deferred — needs credentials", "testing": "Testing"}
FIREWALL = "Money may buy testing or re-testing, never a changed verdict. Paid listings are re-tested under the same criteria; payment never changes a result or its placement."
LIMITS = "These are Pax-authored summaries of specific versions and tasks, dated October 29–31, 2026. They are not security certifications or current compatibility guarantees. Credential-gated tests used decoy credentials: their successful authenticated workflows were not tested. Deferred means untested for the promised task, not broken."
EVIDENCE = "Only the summaries are public in this edition. Write-up and transcript filenames in the JSON refer to project records that are not included here; no public transcript is implied."


def build(source: bytes) -> dict:
    doc = json.loads(source)
    rows = doc["tests"]
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)) or any(r["verdict"] not in LABELS for r in rows):
        raise ValueError("Invalid Receipts ids or verdicts")
    house = [r for r in rows if r["category"] == "house"]
    if len(house) != 1 or house[0]["id"] != "000":
        raise ValueError("Receipts must identify the house product")
    return {"schema_version": "lantern-works-receipts/1", "schema": doc["schema"],
            "publication": {"author": "Pax", "source_sha256": hashlib.sha256(source).hexdigest(),
                            "evidence_level": "authored_summaries_only", "limitations": LIMITS,
                            "evidence_availability": EVIDENCE, "verdict_policy": FIREWALL,
                            "house_disclosure": "Record 000 is Lantern Works, our own product, tested at version 0.3.8; it is not an independent endorsement of today's release."},
            "counts": dict(sorted(Counter(r["verdict"] for r in rows).items())), "tests": rows}


def write(g) -> str:
    source = (g.ROOT / "data" / "receipts-index.json").read_bytes()
    doc = build(source)
    e = html.escape
    counts = " · ".join(f"{n} {LABELS[v].lower()}" for v, n in doc["counts"].items())
    cards = []
    for row in doc["tests"]:
        caveats = "".join(f"<li>{e(c)}</li>" for c in row["caveats"])
        house = '<p><strong>House product: made by Lantern Works. This is not an independent endorsement.</strong></p>' if row["category"] == "house" else ""
        cards.append(f'''<article class="receipt" id="test-{e(row['id'])}">
<h2>#{e(row['id'])} {e(row['server'])}</h2>
<p><strong>{e(LABELS[row['verdict']])}</strong> · <code>{e(row['package'])}</code> v{e(row['version'])} · tested {e(row['tested_at'])} by {e(row['tester'])}</p>
{house}<p>{e(row['headline'])}</p>
<p><strong>Task:</strong> {e(row['canonical_task'])}</p>
<p><strong>Graded against:</strong> {e(row['ground_truth'])}</p>
<ul>{caveats}</ul></article>''')
    body = f'''<style>.receipt{{border:1px solid #d1d5db;border-radius:10px;padding:1rem;margin:1rem 0;overflow-wrap:anywhere}}.receipt h2{{margin-top:0;font-size:1.15rem}}.receipt code{{white-space:normal}}.receipt-policy{{border-left:4px solid #f59e0b;padding-left:1rem}}</style>
<nav class="crumbs"><a href="{g.BASE}/">Lantern Works</a> › Receipts</nav>
<h1>Receipts: MCP server test summaries</h1>
<p>Pax's reports of installing MCP servers, giving them a specific task and checking the output. {len(doc['tests'])} records: {e(counts)}.</p>
<aside class="receipt-policy" aria-label="Verdict policy"><h2>Verdict firewall</h2><p>{e(FIREWALL)}</p>
<p>{e(doc['publication']['house_disclosure'])}</p></aside>
<h2>What this edition can establish</h2><p>{e(LIMITS)}</p><p>{e(EVIDENCE)}</p>
<p><a href="{g.BASE}/api/v1/receipts.json">Download all records as JSON</a>. Verdict values preserve the original reports; “failed tested task” is the original <code>broken</code> label, scoped to the dated task.</p>
<p>Need GPU prices in your own agent? <a href="{g.BASE}/quickstart/?ref=receipts">Try a free, cited comparison</a>. Price methodology is documented separately at <a href="{g.BASE}/methodology/">/methodology/</a>.</p>
{''.join(cards)}'''
    api = g.ROOT / "api" / "v1" / "receipts.json"
    api.parent.mkdir(parents=True, exist_ok=True)
    api.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path = g.ROOT / "receipts" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(g.page_shell("Receipts — dated MCP server test summaries", f"{len(doc['tests'])} dated MCP server test summaries by Pax, with task-specific findings, limitations, house-product disclosure and a verdict firewall.", f"{g.BASE}/receipts/", body), encoding="utf-8")
    return "receipts"
