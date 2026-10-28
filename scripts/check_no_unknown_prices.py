#!/usr/bin/env python3
"""Fail if any rendered page or API output shows a price as unknown / n/a / null / blank.

Pages: every generated *.html (except changelog/, which quotes history). Visible text only (scripts, styles
and tags stripped); flags "Price: unknown", table cells or labels that are just unknown / n/a / null / none / tbd /
— / blank in a price column, and price words next to "unknown". API: /api/v1/*.json offers or rates whose price
field is a string like "unknown"/"n/a"/"" (null is allowed in JSON and documented as "no single verified price";
pages must render a label for it, which the page scan enforces).
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = ("changelog/", "node_modules/", "collector/", "lanternworks/", "mcp_server/", "plugins/", "examples/", ".git/")
BAD = r"(?:unknown|n/?a|null|none|tbd|undefined|nan|—|–|-|\?)"
PATTERNS = [
    re.compile(rf"\bprices?(?:\s*:\s*|\s+(?:is|are)\s+){BAD}(?![\w-])", re.I),
    re.compile(rf"\b{BAD}\s+price", re.I) if False else re.compile(r"\bunknown\s+price", re.I),
    re.compile(r"(?:marked|shown as|show|stay|says?|set to|are)\s+[“\"']?unknown", re.I),
    re.compile(r"\$\s*(?:null|none|nan|undefined)\b", re.I),
]
CELL = re.compile(r"<td[^>]*>\s*(?:<(?:em|strong|small)>\s*)*(unknown|n/?a|null|none|tbd|nan|undefined|—|–|-)?\s*(?:</(?:em|strong|small)>\s*)*</td>", re.I)
PRICE_KEYS = ("price_usd", "hourly_usd", "hourly_equiv_usd", "monthly_usd", "price", "list_price_usd")


def page_problems(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    out = []
    for m in CELL.finditer(body):
        if m.group(1) is not None or True:
            # Empty cells are only a problem in price columns; find the header of this column.
            pass
    for tbl in re.finditer(r"(?is)<table\b.*?</table>", body):
        t = tbl.group(0)
        heads = [re.sub(r"<[^>]+>", "", h).strip().lower() for h in re.findall(r"(?is)<th[^>]*>(.*?)</th>", t.split("</thead>")[0])] if "<thead" in t else []
        pcols = [i for i, h in enumerate(heads) if re.search(r"price|cost|/ ?month|per hour|hourly|est\.", h)]
        for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", t.split("</thead>")[-1]):
            cells = re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row)
            for i in pcols:
                if i < len(cells):
                    txt = html.unescape(re.sub(r"<[^>]+>", "", cells[i])).strip()
                    if re.fullmatch(BAD + r"?", txt, re.I) or re.match(r"(?i)unknown\b", txt):
                        out.append(f"{path.relative_to(ROOT)}: empty/unknown price cell {txt!r}")
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = " ".join(text.split())
    for p in PATTERNS:
        for m in p.finditer(text):
            out.append(f"{path.relative_to(ROOT)}: {m.group(0)!r}")
    return out


def api_problems() -> list[str]:
    out = []

    def walk(x, where):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in PRICE_KEYS and isinstance(v, str) and (not v.strip() or re.fullmatch(BAD, v.strip(), re.I)):
                    out.append(f"{where}.{k} = {v!r}")
                walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{where}[{i}]")
    for f in sorted((ROOT / "api" / "v1").rglob("*.json")) + [ROOT / "deals.json"]:
        walk(json.loads(f.read_text(encoding="utf-8")), str(f.relative_to(ROOT)))
    return out


def all_problems() -> list[str]:
    probs = []
    for f in sorted(ROOT.rglob("*.html")):
        rel = str(f.relative_to(ROOT))
        if rel.startswith(SKIP):
            continue
        probs += page_problems(f)
    return probs + api_problems()


if __name__ == "__main__":
    ps = all_problems()
    for p in ps:
        print("UNKNOWN PRICE:", p)
    print(f"RESULT: {len(ps)} unknown/blank price(s)")
    sys.exit(1 if ps else 0)
