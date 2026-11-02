"""Re-verify stack_pricing quotes on the vendor's visible page; bump checked_at only when every quoted price is shown.

For each data/stack_pricing/*.json: fetch source_url, read the visible text (same reader as the GPU refresh and the
live source check). Client-rendered pages (check_gpu_sources.CLIENT_RENDERED) are rendered in headless Chrome when the
server HTML lacks a price. A quote passes when each of its $ prices appears as a displayed price ('$' + the same
amount, plus the same '/unit' when the quote has one). All offers pass -> checked_at = fetch time. Any miss -> FLAG,
nothing in the file changes: quotes and prices are never rewritten here (a person re-sources them)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import check_gpu_sources as cgs  # noqa: E402

DIR = ROOT / "data" / "stack_pricing"
_UNIT = re.compile(r"\$\s?([\d,]*\.?\d+)\s*/\s*([A-Za-z]+)")


def match(quote: str, text: str) -> tuple[bool, list[str]]:
    """(all prices shown, visible snippets that matched)."""
    units = {float(a.replace(",", "")): u for a, u in _UNIT.findall(quote)}
    snips = []
    if not cgs.price_tokens(quote):  # no $ amount (e.g. 'Basic: 12000 emails, Free'): 'Free' must be shown
        m = re.search(r"\bfree\b", text, re.I) if re.search(r"\bfree\b", quote, re.I) else None
        return bool(m), [" ".join(text[max(0, m.start() - 60):m.end() + 20].split())] if m else []
    for tok in cgs.price_tokens(quote):
        v = float(tok.replace(",", ""))
        if v in units:
            rx = re.compile(r"\$\s?" + r"0*" + re.escape(tok.lstrip("0") or "0").replace(r"\.", r"\.") + r"0*(?![\d])\s*/\s*" + re.escape(units[v]) + r"\b", re.I)
            m = rx.search(text)
            if not m:
                return False, snips
        else:
            if not cgs.price_found(tok, quote, text):
                return False, snips
            m = re.search(r"\$\s?" + re.escape(tok) + r"(?![\d.])", text)
        if m:
            snips.append(" ".join(text[max(0, m.start() - 60):m.end() + 20].split()))
    return True, snips


def refresh(docs: list[tuple[Path, dict]], fetch=cgs.fetch, render=cgs.rendered_text, now=None) -> tuple[list[str], list[str]]:
    ok, flags = [], []
    for path, doc in docs:
        u = doc["source_url"]
        st, body = fetch(u)
        if st != 200:
            flags.append(f"{doc['vendor']}: unreachable ({st or body}); checked_at kept {doc['checked_at']}")
            continue
        texts = [("server HTML", cgs.visible_text(body))]
        res = [(o, *match(o["quote"], texts[0][1])) for o in doc["offers"]]
        if not all(r[1] for r in res) and doc["vendor"] in cgs.CLIENT_RENDERED:
            rt = render(u)  # check_gpu_sources.rendered_text retries; '' = render failed
            if not rt:  # Gauge T73 fix7 #2: a render error is a failure, never a fallback
                flags.append(f"{doc['vendor']}: headless render failed (empty DOM or client-side error page) at {u}; "
                             f"checked_at kept {doc['checked_at']}, quote not rewritten")
                continue
            texts = [("headless render", rt)]
            res = [(o, *match(o["quote"], rt)) for o in doc["offers"]]
        miss = [o for o, good, _ in res if not good]
        if miss:
            flags += [f"{doc['vendor']}: quoted price not shown on the visible page ({texts[0][0]}): {o['plan']} quote {o['quote']!r} "
                      f"at {u}; checked_at kept {doc['checked_at']}, quote not rewritten" for o in miss]
            continue
        stamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
        doc["checked_at"] = stamp
        # evidence for the bump: where the prices were read and the visible text that matched (additive)
        doc["last_verification"] = {"checked_at": stamp, "basis": texts[0][0], "source_url": u,
                                    "matched_text": [s for _, _, sn in res for s in sn][:len(res)]}
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        ok += [f"{doc['vendor']}: {o['plan']} verified ({texts[0][0]}) -> checked_at {stamp}; matched: {' | '.join(s)}" for o, _, s in res]
    return ok, flags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report")
    a = ap.parse_args()
    docs = [(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(DIR.glob("*.json"))]
    ok, flags = refresh(docs)
    lines = ["## Stack quote re-verification", *[f"- {x}" for x in ok], *[f"- FLAG: {x}" for x in flags]]
    print("\n".join(lines))
    if a.report:
        Path(a.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0  # flags are reported, not fatal: the 7-day stale check in check_gpu_sources still fails an unverified quote


if __name__ == "__main__":
    sys.exit(main())
