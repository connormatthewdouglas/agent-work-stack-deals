#!/usr/bin/env python3
"""Validate the agent skill: source YAML frontmatter parses, and the served /SKILL.md matches it.

Usage: check_skill.py [--live]   (--live also fetches https://thelanternworks.com/SKILL.md)
The served copy starts with one blank line on purpose (so GitHub Pages serves it raw);
everything after that line must be byte-identical to the source.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skills" / "lantern-works-deals" / "SKILL.md"
LIVE = "https://thelanternworks.com/SKILL.md"


def frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        raise ValueError("frontmatter must start at line 1 with ---")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("frontmatter has no closing ---")
    data = yaml.safe_load(text[4:end])
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    for key in ("name", "description"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"frontmatter missing non-empty {key!r}")
    return data


def check_served(label: str, served: bytes, src: bytes, fm: dict) -> list[str]:
    errs = []
    if not served.startswith(b"\n"):
        errs.append(f"{label}: expected one leading blank line (keeps Pages from rendering it)")
    body = served[1:] if served.startswith(b"\n") else served
    if body != src:
        errs.append(f"{label}: content differs from {SRC.relative_to(ROOT)}")
    try:
        if frontmatter(body.decode("utf-8")) != fm:
            errs.append(f"{label}: frontmatter differs from source")
    except ValueError as e:
        errs.append(f"{label}: {e}")
    return errs


def main() -> int:
    src = SRC.read_bytes()
    errs = []
    try:
        fm = frontmatter(src.decode("utf-8"))
    except (ValueError, yaml.YAMLError) as e:
        print(f"ERROR: {SRC}: {e}")
        return 1
    print(f"source ok: name={fm['name']!r}, keys={sorted(fm)}")
    errs += check_served("repo /SKILL.md", (ROOT / "SKILL.md").read_bytes(), src, fm)
    if "--live" in sys.argv:
        req = urllib.request.Request(LIVE, headers={"User-Agent": "LanternWorksSkillCheck/1.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"live {LIVE}: HTTP {r.status} {r.headers.get('Content-Type')}")
            errs += check_served("live /SKILL.md", r.read(), src, fm)
    for e in errs:
        print("ERROR:", e)
    print("RESULT:", "ok" if not errs else f"{len(errs)} error(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
