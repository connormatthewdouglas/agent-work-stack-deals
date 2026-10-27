#!/usr/bin/env python3
"""Fail if generated site output or docs link to an internal page/file that does not exist.

Scans every generated *.html (href/src) plus README/SKILL/USAGE markdown and the MCP README
for links to the site (root-relative or https://thelanternworks.com/...) and resolves each
against the repo checkout that GitHub Pages serves. Exit 1 on any missing target.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parent.parent
HOST = "thelanternworks.com"
SKIP_DIRS = {".git", "node_modules", "dist", "scripts", "tests", "mcp_server", "core", "__pycache__",
             "lantern_works_deals_mcp.egg-info", "examples", "plugins", "skills", "data"}
DOCS = ["README.md", "SKILL.md", "USAGE.md", "mcp_server/README.md", "skills/*/SKILL.md", "skills/*/*/SKILL.md"]
ATTR = re.compile(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)
MD_URL = re.compile(r'https?://(?:www\.)?thelanternworks\.com(/[^\s)"\'`<>\]]*)?')


def resolve(path: str) -> bool:
    path = unquote(path).split("#")[0].split("?")[0]
    rel = path.lstrip("/")
    if rel == "":
        return (ROOT / "index.html").exists()
    p = ROOT / rel
    if path.endswith("/"):
        return (p / "index.html").exists()
    # Jekyll renders a .md with front matter to .html (e.g. /skills/<name>/SKILL.html)
    md = p.with_suffix(".md")
    jekyll = p.suffix == ".html" and md.is_file() and md.read_text(encoding="utf-8").startswith("---")
    return p.is_file() or (p / "index.html").exists() or p.with_suffix(".html").is_file() or jekyll


def internal_path(url: str, page_rel: str) -> str | None:
    if url.startswith(("#", "mailto:", "tel:", "javascript:", "data:")) or "{" in url or "$" in url:
        return None
    sp = urlsplit(url)
    if sp.scheme in ("http", "https"):
        if sp.netloc.lower().removeprefix("www.") != HOST:
            return None
        return sp.path or "/"
    if sp.scheme or sp.netloc:
        return None
    if url.startswith("/"):
        return sp.path
    base = "/" + page_rel.rsplit("/", 1)[0] + "/" if "/" in page_rel else "/"
    return base + sp.path


def html_files():
    for p in ROOT.rglob("*.html"):
        if not SKIP_DIRS.intersection(p.relative_to(ROOT).parts):
            yield p


def check() -> list[str]:
    bad = []
    for f in html_files():
        rel = f.relative_to(ROOT).as_posix()
        for url in ATTR.findall(f.read_text(encoding="utf-8", errors="replace")):
            path = internal_path(url.strip(), rel)
            if path is not None and not resolve(path):
                bad.append(f"{rel}: {url}")
    for pat in DOCS:
        for f in ROOT.glob(pat):
            for m in MD_URL.finditer(f.read_text(encoding="utf-8")):
                path = (m.group(1) or "/").rstrip(".,;:")
                if not resolve(path):
                    bad.append(f"{f.relative_to(ROOT).as_posix()}: {m.group(0)}")
    return sorted(set(bad))


def main() -> int:
    bad = check()
    for b in bad:
        print("BROKEN", b)
    print(f"internal_links: {len(bad)} broken")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
