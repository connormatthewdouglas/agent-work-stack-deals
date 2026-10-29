"""T5 regression: feed instructions must use neutral referral disclosure, never 'authorized affiliate link'."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHRASE = re.compile(r"authorized affiliate link", re.I)


def test_no_authorized_affiliate_wording_in_feed_or_site():
    hits = []
    for p in ROOT.rglob("*"):
        if ".git" in p.parts or "tests" in p.parts or p.suffix not in (".json", ".html", ".md", ".py", ".txt", ".xml"):
            continue
        if PHRASE.search(p.read_text(encoding="utf-8", errors="ignore")):
            hits.append(str(p.relative_to(ROOT)))
    assert not hits, f"'authorized affiliate link' wording found in: {hits[:10]}"
