"""Vendors paused for Scout imports. Edit data/owner_hold.json to lift a hold.

Importers load this list before they hash a snapshot or write pricing files. Matching
rows already on main are copied through byte-for-byte: no adds, updates, deletes,
or new timestamps. A vendor matches its hold name exactly, or with a trailing
parenthetical / extra words ("Verda (formerly DataCrunch)").
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "owner_hold.json"
# Tests that run an importer in a subprocess point it at a fixed hold list with LW_OWNER_HOLD.
if os.environ.get("LW_OWNER_HOLD"):
    CONFIG = Path(os.environ["LW_OWNER_HOLD"])


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
    if names is None:
        try:
            names = hold_names()
        except FileNotFoundError:
            return False  # a hosted bundle that does not ship the list ranks the feed it was given
    for raw in names:
        key = " ".join(str(raw).split()).casefold()
        if not key:
            continue
        if v == key or v.startswith(key + " ") or v.startswith(key + "("):
            return True
    return False
