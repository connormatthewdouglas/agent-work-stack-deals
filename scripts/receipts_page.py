"""Publish the approved Pax summaries without inventing missing public evidence.

T125: also publish Pax's Receipts proof pack v1 as stable third-party case
pages under /receipts/<id>-<slug>/, with machine-readable evidence JSON.
The 62-record index SHA stays pinned; proof-pack content lives in separate
data files so regenerate does not invent or rewrite findings.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path

SOURCE_SHA256 = "ebcd0b1b2524585dd343efcd7c4eeb0b560f71e4950dcb88bea069e6736be517"
PROOF_PACK_MD = "receipts-proof-pack-v1.md"
PROOF_PACK_JSON = "receipts-proof-pack-v1.json"
# Durable public slugs for the three T125 cases (third-party servers only).
PROOF_CASES = (
    {"id": "002", "slug": "002-mcp-server-time", "title_verdict": "Works"},
    {"id": "056", "slug": "056-server-redis", "title_verdict": "Works With Caveats"},
    {"id": "009", "slug": "009-open-meteo-mcp", "title_verdict": "Broken"},
)
LABELS = {"works": "Worked", "works_with_caveats": "Worked with caveats", "broken": "Failed tested task",
          "deferred": "Deferred — needs credentials", "testing": "Testing"}
FIREWALL = "Money may buy testing or re-testing, never a changed verdict. Paid listings are re-tested under the same criteria; payment never changes a result or its placement."
LIMITS = "These are Pax-authored summaries of specific versions and tasks, dated October 29–31, 2026. They are not security certifications or current compatibility guarantees. Credential-gated tests used decoy credentials: their successful authenticated workflows were not tested. Deferred means untested for the promised task, not broken."
EVIDENCE = (
    "Sixty-two records publish authored summaries only. Write-up and transcript "
    "filenames in the index JSON refer to project records that are not included "
    "with those summaries. Three representative third-party cases also have a "
    "public proof-pack page (excerpts + machine-readable evidence) under "
    "/receipts/; see Proof pack v1 below."
)
REF_PROOF = "receipts-proofpack"
THIRD_PARTY = (
    "Third-party MCP server. Not the Lantern Works house product "
    "(Receipts #000 stays labeled house on the index)."
)


# Public pages: keep findings verbatim, but never publish Frosty/Connor personal names.
# The GitHub owner path is a personal handle; render a Lantern Works attribution instead.
_PERSONAL_REPO = "github.com/connormatthewdouglas/agent-work-stack-deals"
_PUBLIC_REPO = "the Lantern Works GitHub repository"
_PERSONAL_REPO_SHORT = "connormatthewdouglas/agent-work-stack-deals"


def scrub_personal(text: str) -> str:
    text = text.replace(_PERSONAL_REPO, _PUBLIC_REPO)
    text = text.replace(_PERSONAL_REPO_SHORT, "the Lantern Works GitHub repository")
    for name in ("Connor Douglas", "Connor", "Frosty Condor", "Frosty"):
        # Only scrub standalone personal display names; do not touch 'Pax'.
        text = text.replace(name, "Lantern Works")
    return text



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


def load_proof_pack(root: Path) -> tuple[str, dict]:
    md = (root / "data" / PROOF_PACK_MD).read_text(encoding="utf-8")
    pack = json.loads((root / "data" / PROOF_PACK_JSON).read_text(encoding="utf-8"))
    if pack.get("pack") != "receipts-proof-pack-v1":
        raise ValueError("Unexpected proof pack id")
    by_id = {c["record_id"]: c for c in pack["cases"]}
    for spec in PROOF_CASES:
        if spec["id"] not in by_id:
            raise ValueError(f"Proof pack missing case {spec['id']}")
        if by_id[spec["id"]].get("verdict") in (None, ""):
            raise ValueError(f"Proof pack case {spec['id']} has no verdict")
    return md, pack


def split_proof_cases(md: str) -> dict[str, tuple[str, str]]:
    """Map record id -> (heading text after '## Case N — ', body markdown)."""
    parts = re.split(r"(?m)^## Case \d+ — ", md)
    if len(parts) < 4:
        raise ValueError("Proof pack md missing the three Case sections")
    out: dict[str, tuple[str, str]] = {}
    for block in parts[1:]:
        block = re.split(r"(?m)^---\s*$", block, maxsplit=1)[0].strip()
        first, _, rest = block.partition("\n")
        heading = first.strip()
        m = re.search(r"#(\d{3})\b", heading)
        if not m:
            raise ValueError(f"Case heading missing record id: {heading!r}")
        out[m.group(1)] = (heading, rest.strip())
    for spec in PROOF_CASES:
        if spec["id"] not in out:
            raise ValueError(f"Could not parse case {spec['id']} from proof pack md")
    return out


def _inline(text: str) -> str:
    """Escape then restore a minimal set of markdown inline markers."""
    e = html.escape(text)
    e = re.sub(r"`([^`]+)`", r"<code>\1</code>", e)
    e = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", e)
    return e


def md_fragment_to_html(md: str) -> str:
    """Render a proof-pack case body. Preserves wording; light structure only."""
    out: list[str] = []
    lines = md.splitlines()
    i = 0

    def is_cont(s: str) -> bool:
        return bool(s) and s[0] in " \t" and not s.lstrip().startswith(("```", "- ", "## "))

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # closing fence
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(buf))}</code></pre>")
            continue
        if line.startswith("- "):
            items: list[str] = []
            while i < len(lines) and lines[i].startswith("- "):
                parts = [lines[i][2:].strip()]
                i += 1
                while i < len(lines) and is_cont(lines[i]):
                    parts.append(lines[i].strip())
                    i += 1
                while i < len(lines) and not lines[i].strip():
                    if i + 1 < len(lines) and is_cont(lines[i + 1]):
                        i += 1
                        continue
                    break
                items.append(f"<li>{_inline(' '.join(parts))}</li>")
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        if not line.strip():
            i += 1
            continue
        buf = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("```") and not lines[i].startswith("- ") and not lines[i].startswith("## "):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(buf))}</p>")
    return "\n".join(out)


def proof_intro_html(md: str) -> str:
    """Render the pack intro (before the first Case) as HTML paragraphs."""
    intro = re.split(r"(?m)^## Case \d+ — ", md, maxsplit=1)[0]
    intro = re.sub(r"(?m)^# .*\n?", "", intro, count=1).strip()
    intro = re.sub(r"(?m)^---\s*$", "", intro).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", intro) if p.strip()]
    return "\n".join(f"<p>{_inline(scrub_personal(re.sub(r'\s+', ' ', p)))}</p>" for p in paras)

def write_proof_case(g, spec: dict, heading: str, body_md: str, case_json: dict) -> str:
    e = html.escape
    slug = spec["slug"]
    rid = spec["id"]
    url = f"{g.BASE}/receipts/{slug}/"
    evidence_url = f"{g.BASE}/receipts/{slug}/evidence.json"
    package = case_json.get("package", "")
    title = f"Receipts #{rid}: {package} — {spec['title_verdict']}"
    desc = (
        f"Pax proof-pack case #{rid} ({spec['title_verdict']}): {package} "
        f"v{case_json.get('version', '')}, tested {case_json.get('tested_at', '')}. "
        f"Third-party MCP server; not the Lantern Works house product."
    )
    sep = "\u203a"
    body = (
        '<style>.proof-case{overflow-wrap:anywhere}.proof-case pre{overflow:auto;background:#f3f4f6;padding:1rem;border-radius:8px}'
        '.proof-case code{white-space:normal}.proof-meta{border-left:4px solid #6366f1;padding-left:1rem;margin:1rem 0}'
        '.third-party{border-left:4px solid #9ca3af;padding-left:1rem}</style>\n'
        f'<nav class="crumbs"><a href="{g.BASE}/">Lantern Works</a> {sep} '
        f'<a href="{g.BASE}/receipts/">Receipts</a> {sep} #{e(rid)}</nav>\n'
        '<article class="proof-case">\n'
        f'<h1>Receipts #{e(rid)} — {e(heading)}</h1>\n'
        f'<aside class="third-party" aria-label="Third-party disclosure"><p><strong>{e(THIRD_PARTY)}</strong></p></aside>\n'
        '<aside class="proof-meta" aria-label="Case metadata">\n'
        f'<p><strong>Package:</strong> <code>{e(package)}</code> v{e(str(case_json.get("version", "")))} ({e(str(case_json.get("registry", "")))})</p>\n'
        f'<p><strong>Verdict:</strong> {e(spec["title_verdict"])} · <strong>Tested:</strong> {e(str(case_json.get("tested_at", "")))} · <strong>Assembled by:</strong> Pax</p>\n'
        f'<p><strong>Machine-readable evidence:</strong> <a href="{evidence_url}"><code>evidence.json</code></a> · pack <a href="{g.BASE}/receipts/proof-pack-v1.json"><code>proof-pack-v1.json</code></a></p>\n'
        '</aside>\n'
        f'{md_fragment_to_html(body_md)}\n'
        '<p>Corrections and retest requests: open an issue on the Lantern Works repo naming the record id. Paid re-tests are accepted under the Receipts firewall: money can buy being measured sooner, never a changed verdict.</p>\n'
        f'<p>Need GPU prices in your own agent? <a href="{g.BASE}/quickstart/?ref={REF_PROOF}">Try a free, cited comparison</a>. Back to the <a href="{g.BASE}/receipts/">Receipts index</a>.</p>\n'
        '</article>'
    )
    out_dir = g.ROOT / "receipts" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(
        g.page_shell(title, desc[:300], url, body), encoding="utf-8"
    )
    evidence = dict(case_json)
    evidence["stable_url"] = url
    evidence["evidence_json_url"] = evidence_url
    evidence["third_party"] = True
    evidence["house"] = False
    evidence["referral_tag"] = REF_PROOF
    (out_dir / "evidence.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return f"receipts/{slug}"


def write_proof_pack(g) -> list[str]:
    md, pack = load_proof_pack(g.ROOT)
    cases_md = split_proof_cases(md)
    by_id = {c["record_id"]: c for c in pack["cases"]}
    paths: list[str] = []
    for spec in PROOF_CASES:
        heading, body = cases_md[spec["id"]]
        paths.append(write_proof_case(g, spec, heading, body, by_id[spec["id"]]))
    published = dict(pack)
    if isinstance(published.get("policy"), str):
        published["policy"] = scrub_personal(published["policy"])
    published["public_pages"] = {
        spec["id"]: {
            "html": f"{g.BASE}/receipts/{spec['slug']}/",
            "evidence_json": f"{g.BASE}/receipts/{spec['slug']}/evidence.json",
        }
        for spec in PROOF_CASES
    }
    published["referral_tag"] = REF_PROOF
    pack_path = g.ROOT / "receipts" / "proof-pack-v1.json"
    pack_path.write_text(json.dumps(published, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    api = g.ROOT / "api" / "v1" / "receipts-proof-pack.json"
    api.parent.mkdir(parents=True, exist_ok=True)
    api.write_text(pack_path.read_text(encoding="utf-8"), encoding="utf-8")
    return paths


def proof_pack_index_section(g) -> str:
    e = html.escape
    md, pack = load_proof_pack(g.ROOT)
    links = []
    by_id = {c["record_id"]: c for c in pack["cases"]}
    for spec in PROOF_CASES:
        c = by_id[spec["id"]]
        links.append(
            f'<li><a href="{g.BASE}/receipts/{spec["slug"]}/">#{e(spec["id"])} '
            f'<code>{e(c["package"])}</code> — {e(spec["title_verdict"])}</a> '
            f'(<a href="{g.BASE}/receipts/{spec["slug"]}/evidence.json">evidence.json</a>)</li>'
        )
    return (
        '<section id="proof-pack-v1" class="proof-pack">\n'
        '<h2>Proof pack v1</h2>\n'
        f'{proof_intro_html(md)}\n'
        '<p>These three cases are <strong>third-party</strong> servers. The house label stays on Receipts #000 (Lantern Works) on this index.</p>\n'
        f'<ul>{"".join(links)}</ul>\n'
        f'<p>Machine-readable pack: <a href="{g.BASE}/receipts/proof-pack-v1.json"><code>/receipts/proof-pack-v1.json</code></a>\n'
        f'(same bytes mirrored at <a href="{g.BASE}/api/v1/receipts-proof-pack.json"><code>/api/v1/receipts-proof-pack.json</code></a>).\n'
        f'Receipts-intent referrals from the case pages use <code>ref={e(REF_PROOF)}</code>.</p>\n'
        '</section>'
    )


def brand_receipts_pages(g) -> None:
    """Inject favicon/og brand block into receipts pages only (avoid full-site churn)."""
    b, e = "<!-- brand -->", "<!-- /brand -->"
    block = f"  {b}\n{g.HEAD_BRAND}{g.OG_IMAGE}  {e}\n"
    paths = [g.ROOT / "receipts" / "index.html"]
    for spec in PROOF_CASES:
        paths.append(g.ROOT / "receipts" / spec["slug"] / "index.html")
    for path in paths:
        if not path.is_file():
            continue
        t = path.read_text(encoding="utf-8")
        if "</head>" not in t:
            continue
        t2 = re.sub(r"[ \t]*" + re.escape(b) + r".*?" + re.escape(e) + r"\n", "", t, flags=re.S)
        t2 = t2.replace("</head>", block + "</head>", 1)
        if t2 != t:
            path.write_text(t2, encoding="utf-8")


def write(g) -> list[str]:
    source = (g.ROOT / "data" / "receipts-index.json").read_bytes()
    doc = build(source)
    e = html.escape
    counts = " · ".join(f"{n} {LABELS[v].lower()}" for v, n in doc["counts"].items())
    proof_by_id = {spec["id"]: spec for spec in PROOF_CASES}
    cards = []
    for row in doc["tests"]:
        caveats = "".join(f"<li>{e(c)}</li>" for c in row["caveats"])
        house = ('<p><strong>House product: made by Lantern Works. This is not an independent endorsement.</strong></p>'
                 if row["category"] == "house" else "")
        proof_link = ""
        if row["id"] in proof_by_id:
            spec = proof_by_id[row["id"]]
            proof_link = (
                f'<p><a href="{g.BASE}/receipts/{spec["slug"]}/">Proof pack v1 case page</a> '
                f'(third-party) · <a href="{g.BASE}/receipts/{spec["slug"]}/evidence.json">evidence.json</a></p>'
            )
        cards.append(
            f'<article class="receipt" id="test-{e(row['id'])}">\n'
            f'<h2>#{e(row['id'])} {e(row['server'])}</h2>\n'
            f'<p><strong>{e(LABELS[row['verdict']])}</strong> · <code>{e(row['package'])}</code> v{e(row['version'])} · tested {e(row['tested_at'])} by {e(row['tester'])}</p>\n'
            f'{house}<p>{e(row['headline'])}</p>\n'
            f'<p><strong>Task:</strong> {e(row['canonical_task'])}</p>\n'
            f'<p><strong>Graded against:</strong> {e(row['ground_truth'])}</p>\n'
            f'<ul>{caveats}</ul>{proof_link}</article>'
        )
    sep = "\u203a"
    body = (
        '<style>.receipt{border:1px solid #d1d5db;border-radius:10px;padding:1rem;margin:1rem 0;overflow-wrap:anywhere}'
        '.receipt h2{margin-top:0;font-size:1.15rem}.receipt code{white-space:normal}'
        '.receipt-policy{border-left:4px solid #f59e0b;padding-left:1rem}'
        '.proof-pack{border:1px solid #c7d2fe;border-radius:10px;padding:1rem;margin:1.5rem 0;background:#eef2ff}</style>\n'
        f'<nav class="crumbs"><a href="{g.BASE}/">Lantern Works</a> {sep} Receipts</nav>\n'
        '<h1>Receipts: MCP server test summaries</h1>\n'
        f'<p>Pax\'s reports of installing MCP servers, giving them a specific task and checking the output. {len(doc['tests'])} records: {e(counts)}.</p>\n'
        f'<aside class="receipt-policy" aria-label="Verdict policy"><h2>Verdict firewall</h2><p>{e(FIREWALL)}</p>\n'
        f'<p>{e(doc['publication']['house_disclosure'])}</p></aside>\n'
        f'<h2>What this edition can establish</h2><p>{e(LIMITS)}</p><p>{e(EVIDENCE)}</p>\n'
        f'{proof_pack_index_section(g)}\n'
        f'<p><a href="{g.BASE}/api/v1/receipts.json">Download all records as JSON</a>. Verdict values preserve the original reports; “failed tested task” is the original <code>broken</code> label, scoped to the dated task.</p>\n'
        f'<p>Need GPU prices in your own agent? <a href="{g.BASE}/quickstart/?ref=receipts">Try a free, cited comparison</a>. Price methodology is documented separately at <a href="{g.BASE}/methodology/">/methodology/</a>.</p>\n'
        f'{"".join(cards)}'
    )
    api = g.ROOT / "api" / "v1" / "receipts.json"
    api.parent.mkdir(parents=True, exist_ok=True)
    api.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path = g.ROOT / "receipts" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(g.page_shell("Receipts — dated MCP server test summaries", f"{len(doc['tests'])} dated MCP server test summaries by Pax, with task-specific findings, limitations, house-product disclosure and a verdict firewall.", f"{g.BASE}/receipts/", body), encoding="utf-8")
    proof_paths = write_proof_pack(g)
    brand_receipts_pages(g)
    return ["receipts", *proof_paths]

