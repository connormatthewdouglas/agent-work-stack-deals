"""Vendors paused for Scout imports. Edit data/owner_hold.json to lift a hold.

Importers load this list before they hash a snapshot or write pricing files. Matching
rows already on main are copied through byte-for-byte: no adds, updates, deletes,
or new timestamps. A vendor matches its hold name exactly, or with a trailing
parenthetical / extra words ("Verda (formerly DataCrunch)").
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "owner_hold.json"


def hold_names(path: Path | None = None) -> list[str]:
    p = path or CONFIG
    doc = json.loads(p.read_text(encoding="utf-8"))
    names = doc.get("vendors") if isinstance(doc, dict) else doc
    if not isinstance(names, list) or not all(isinstance(x, str) and x.strip() for x in names):
        raise SystemExit(f"owner hold list must be a JSON list of vendor names ({p})")
    return [x.strip() for x in names]


def is_held(vendor: str | None, names: list[str] | None = None) -> bool:
    v = " ".join(str(vendor or "").split()).casefold()
    if not v:
        return False
    for raw in names if names is not None else hold_names():
        key = " ".join(str(raw).split()).casefold()
        if not key:
            continue
        if v == key or v.startswith(key + " ") or v.startswith(key + "("):
            return True
    return False
