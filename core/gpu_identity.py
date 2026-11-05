"""T61: sourced GPU identity and memory (core/assets/gpu_identity.json, from Scout's T61 pass).

Nominal memory is the spec-sheet figure with its source_url and quote. Usable (vendor-allocatable) memory is a
separate field; where no source states it, it is 'unknown' and a usable-memory filter reports the row as unknown.
It never silently falls back to nominal memory. Unknown values are never filled in."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ASSET = Path(__file__).resolve().parent / "assets" / "gpu_identity.json"
_GB = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*GB\b(?!.*\bor\b)(?!.*/)", re.I)


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(ASSET.read_text(encoding="utf-8"))


def _gb(spec: dict | None) -> float | None:
    """A single stated GB figure, else None ('40GB or 80GB', '80GB (SXM) / 94GB (NVL)' and 'unknown' stay None)."""
    v = (spec or {}).get("value")
    if not isinstance(v, str) or (spec or {}).get("unit_as_stated") != "GB":
        return None
    m = _GB.match(v)
    return float(m.group(1)) if m else None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def identity(model: str) -> dict | None:
    """Exact (case-insensitive) model match only: 'L40' never resolves to 'L40S', 'A10' never to 'A100',
    'H100 NVL' (94 GB) never to 'H100 NVLink' (80 GB). AMD MI325X/MI350X/MI355X carry their AMD identity."""
    d = _data()
    key = _norm(model)
    amd = next((v for k, v in (d.get("amd_identity_specs") or {}).items() if _norm(k) == key), None)
    m = next((x for x in d.get("models") or [] if _norm(x["model"]) == key), None)
    if not m and not amd:
        return None
    name = m["model"] if m else next(k for k in d["amd_identity_specs"] if _norm(k) == key)
    nom = (m or {}).get("nominal_memory")
    if nom is None and amd:
        nom = {"value": amd["memory_size"], "unit_as_stated": "GB", "source_url": amd["source_url"],
               "quote": next((q for q in amd.get("quotes") or [] if "Memory Size" in q), None)}
    use = (m or {}).get("usable_memory") or {"value": "unknown", "source_url": None, "quote": None,
                                             "note": "No vendor-stated allocatable/usable figure found"}
    out = {"model": name, "nominal_memory": {**nom, "gb": _gb(nom)},
           "usable_memory": {**use, "gb": _gb(use) if use.get("source_url") else None},
           "memory_basis_note": "nominal_memory is the spec-sheet figure; usable_memory is what a vendor allocates. "
                                "They are different fields and unknown stays unknown."}
    if (m or {}).get("note"):
        out["note"] = m["note"]
    if amd:
        out["amd_identity"] = amd
    return out


def filter_usable(rows: list[dict], min_gb: float, model_key: str = "gpu") -> dict:
    """Rows whose sourced USABLE memory is >= min_gb. Rows with unknown usable memory go to `unknown`, never matched
    on nominal memory or on a row's vram_gb."""
    ok, below, unknown = [], [], []
    for r in rows:
        ident = identity(r.get(model_key) or "")
        gb = (ident or {}).get("usable_memory", {}).get("gb")
        (unknown if gb is None else ok if gb >= min_gb else below).append(r)
    note = None
    if unknown:
        note = (f"{len(unknown)} row(s) have unknown usable memory (no source states the vendor-allocatable figure); "
                "they are not matched on nominal memory. Use min_vram for nominal capacity.")
    return {"matched": ok, "below": below, "unknown": unknown, "note": note}
