"""Parse Civo public GPU product pages for statusText stock and commitment prices.

Civo's /ai/<gpu>-gpu pages embed a Next.js flight payload whose pricingTable
cells carry a statusText field ("In stock" / "Out of stock") and commitment6/12/24/36
hourly prices. The general /pricing page lists the same commitment ladder in
visible text but has no statusText. Unknown stays unknown: only those two
statusText values (whitespace- and case-normalized) map to in_stock true/false.

Schema 3.2 additive: this module only reads public HTML. It does not bump the
snapshot schema version.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Product pages that publish statusText for the 1-GPU sizes we already track.
CIVO_PRODUCT_PAGES = {
    "H100 SXM": "https://www.civo.com/ai/h100-gpu",
    "A100": "https://www.civo.com/ai/a100-gpu",
}

# 6/12/24-month terms named in the bug report. 36-month is also on the same
# public table; it is parsed but not required of callers.
COMMITMENT_MONTHS = (6, 12, 24, 36)

_STATUS_IN = "in stock"
_STATUS_OUT = "out of stock"
_MONEY_RE = re.compile(r"\$+\s*([\d,]+(?:\.\d+)?)")
_VRAM_RE = re.compile(r"(\d+)\s*GB", re.I)
_ONE_X_RE = re.compile(r"(?:^|[\s])1\s*x\s", re.I)
_CHUNK_RE = re.compile(r"self\.__next_f\.push\(\[(\d+),(\".*?\")\]\)", re.S)


def parse_status_text(status_text: Any) -> bool | None:
    """Map a firm public statusText to in_stock; anything else stays unknown."""
    if not isinstance(status_text, str):
        return None
    norm = " ".join(status_text.split()).casefold()
    if norm == _STATUS_IN:
        return True
    if norm == _STATUS_OUT:
        return False
    return None


def parse_money(value: Any) -> float | None:
    """Parse Civo's '$$2.99' / '$2,182.70' price strings. Missing or N/A -> None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    if re.search(r"\bN/?A\b", value, re.I):
        return None
    m = _MONEY_RE.search(value)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _walk(obj: Any, acc: list) -> None:
    if isinstance(obj, dict):
        if obj.get("blockType") == "pricingTable" or (
            isinstance(obj.get("rows"), list) and obj.get("headerRow") is not None
        ):
            acc.append(obj)
        for v in obj.values():
            _walk(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, acc)


def extract_pricing_tables(source: Any) -> list[dict]:
    """Return pricingTable objects from a parsed object, JSON string, or page HTML."""
    tables: list[dict] = []
    if isinstance(source, (dict, list)):
        _walk(source, tables)
        return tables
    if not isinstance(source, str):
        return tables
    text = source
    # Already-parsed JSON (fixture files) or a flight chunk body.
    stripped = text.strip()
    if stripped[:1] in "{[":
        try:
            _walk(json.loads(stripped), tables)
            if tables:
                return tables
        except json.JSONDecodeError:
            pass
    for m in _CHUNK_RE.finditer(text):
        try:
            payload = json.loads(m.group(2))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, str):
            continue
        body = re.sub(r"^\d+:", "", payload, count=1)
        try:
            _walk(json.loads(body), tables)
        except json.JSONDecodeError:
            continue
    return tables


def _infer_model(primary: str | None, secondary: str | None) -> tuple[str, int | None] | None:
    """Map a 1-GPU Civo row to the feed's gpu name and VRAM. Multi-GPU rows are skipped."""
    primary = primary or ""
    secondary = secondary or ""
    if not _ONE_X_RE.search(secondary) and not _ONE_X_RE.search(primary):
        return None
    blob = f"{primary} {secondary}"
    vram = None
    vm = _VRAM_RE.search(secondary) or _VRAM_RE.search(primary)
    if vm:
        vram = int(vm.group(1))
    if re.search(r"\bH100\b", blob, re.I):
        gpu = "H100 SXM" if re.search(r"\bSXM\b", blob, re.I) else "H100"
        return gpu, vram
    if re.search(r"\bA100\b", blob, re.I):
        return "A100", vram
    return None


def _cell_commitments(cell: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for months in COMMITMENT_MONTHS:
        raw = cell.get(f"commitment{months}")
        if not isinstance(raw, dict):
            continue
        hourly = parse_money(raw.get("hourlyPrice"))
        monthly = parse_money(raw.get("monthlyPrice"))
        if hourly is None and monthly is None:
            continue
        out[months] = {"hourly_usd": hourly, "monthly_usd": monthly}
    return out


def _row_from_cells(cells: list) -> dict | None:
    if not isinstance(cells, list):
        return None
    primary = secondary = status_text = None
    ondemand_hourly = ondemand_monthly = None
    commitments: dict[int, dict] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        variant = cell.get("variant")
        if variant == "text":
            primary = cell.get("primaryText") or primary
            secondary = cell.get("secondaryText") or secondary
        elif variant == "status":
            status_text = cell.get("statusText")
            if ondemand_hourly is None:
                ondemand_hourly = parse_money(cell.get("hourlyPrice") or cell.get("primaryText"))
            if ondemand_monthly is None:
                ondemand_monthly = parse_money(cell.get("monthlyPrice"))
        elif variant == "price":
            ondemand_hourly = parse_money(cell.get("hourlyPrice")) or ondemand_hourly
            ondemand_monthly = parse_money(cell.get("monthlyPrice")) or ondemand_monthly
        elif variant == "commitment":
            commitments.update(_cell_commitments(cell))
    inferred = _infer_model(primary, secondary)
    if inferred is None and not status_text and not commitments:
        return None
    gpu, vram = inferred if inferred else (None, None)
    return {
        "primary_text": primary,
        "secondary_text": secondary,
        "gpu": gpu,
        "vram_gb": vram,
        "status_text": status_text,
        "in_stock": parse_status_text(status_text),
        "ondemand_hourly_usd": ondemand_hourly,
        "ondemand_monthly_usd": ondemand_monthly,
        "commitments": commitments,
    }


def parse_civo_product_page(source: Any) -> list[dict]:
    """Parse one Civo product page (HTML, pricingTable JSON, or object) into row dicts.

    Only 1-GPU rows that map to a known feed model (H100 / H100 SXM / A100) are
    returned. in_stock is True/False only for firm 'In stock'/'Out of stock'
    statusText; otherwise None.
    """
    rows: list[dict] = []
    seen: set[tuple] = set()
    for table in extract_pricing_tables(source):
        for raw in table.get("rows") or []:
            if not isinstance(raw, dict):
                continue
            parsed = _row_from_cells(raw.get("cells") or [])
            if not parsed or not parsed.get("gpu"):
                continue
            key = (parsed["gpu"], parsed["vram_gb"], parsed["primary_text"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(parsed)
    return rows


def availability_rows(parsed: list[dict], source_url: str, collected_at: str,
                      tiers: tuple[str, ...] = ("On-demand",
                                                "6-month commitment",
                                                "12-month commitment",
                                                "24-month commitment")) -> list[dict]:
    """Scout-shaped availability rows for enrich/import join (vendor, gpu, vram, tier).

    Commitment tiers share the same public statusText as the 1-GPU on-demand row.
    Price fields are left unset so a stock join is never blocked by a price gate.
    """
    out = []
    for p in parsed:
        if p.get("gpu") is None:
            continue
        for tier in tiers:
            out.append({
                "vendor": "Civo",
                "gpu_model": p["gpu"],
                "vram_gb": p["vram_gb"],
                "tier": tier,
                "region": "all",
                "in_stock": p["in_stock"],
                "offer_count": None,
                "stock_level": None,
                "price_usd_hr": None,
                "price_basis": None,
                "source_url": source_url,
                "collected_at": collected_at,
                "price_refresh": "daily",
                "availability_refresh": "4h",
                "vram_note": None,
                "availability_note": (
                    None if p["in_stock"] is None else
                    f"statusText on the vendor product page: {p['status_text']!r}"
                ),
                "source": "public vendor web page",
                "observation": None if p["status_text"] is None else f"statusText={p['status_text']!r}",
            })
    return out
