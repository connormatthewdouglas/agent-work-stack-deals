"""AWS Price List Bulk API helper for the daily GPU price refresh.

Public, unauthenticated offer files on pricing.us-east-1.amazonaws.com (no robots.txt
on that host). The daily collector streams the regional CSV and keeps only Linux,
shared-tenancy, on-demand, CapacityStatus=Used, unit=Hrs rows, then matches each
tracked instance type. Fetch or parse failure returns no price; the refresh loop
leaves verified_at/checked_at unchanged.
"""
from __future__ import annotations

import csv
import io
import re
import urllib.error
import urllib.request
from collections.abc import Iterable

OFFER_HOST = "pricing.us-east-1.amazonaws.com"
OFFER_PATH = "/offers/v1.0/aws/AmazonEC2/"
COLLECTOR = "aws_price_list"
DEFAULT_TIMEOUT_S = 180

# Tracked offer: Linux, shared tenancy, on-demand, currently used capacity, hourly.
FILTER = {
    "TermType": "OnDemand",
    "Operating System": "Linux",
    "Tenancy": "Shared",
    "CapacityStatus": "Used",
    "Unit": "Hrs",
}

# "On-demand EC2 instance g5.xlarge (1x A10G, ...)"
_INSTANCE_RE = re.compile(r"\bEC2 instance\s+([a-z0-9]+(?:\.[a-z0-9-]+)?)", re.I)


def is_offer_url(url: str | None) -> bool:
    u = url or ""
    return OFFER_HOST in u and OFFER_PATH in u and u.split("?", 1)[0].endswith(".csv")


def is_doc(doc: dict) -> bool:
    if (doc.get("collector") or "") == COLLECTOR:
        return True
    vendor = doc.get("vendor") or ""
    if "Amazon" not in vendor:
        return False
    if is_offer_url(doc.get("source_url")):
        return True
    return any(is_offer_url((r or {}).get("source_url")) for r in (doc.get("records") or []))


def instance_type_of(record: dict) -> str | None:
    if record.get("instance_type"):
        return str(record["instance_type"]).strip() or None
    m = _INSTANCE_RE.search(record.get("tier") or "")
    return m.group(1) if m else None


def _cell(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def row_matches_filter(row: dict) -> bool:
    return all(_cell(row, k) == v for k, v in FILTER.items())


def parse_preamble_and_table(body: str) -> tuple[dict[str, str], list[dict]]:
    """Split an AWS offer CSV into {Publication Date, Version, ...} and data rows."""
    if not body or not str(body).strip():
        raise ValueError("empty Price List body")
    lines = str(body).splitlines()
    meta: dict[str, str] = {}
    header_i = None
    for i, line in enumerate(lines):
        low = line.lower()
        compact = low.replace(" ", "")
        if "sku" in low and "instance type" in low and "priceperunit" in compact:
            header_i = i
            break
        # preamble pairs: "Publication Date","2026-11-10T17:38:52Z"
        try:
            cells = next(csv.reader([line]))
        except csv.Error:
            continue
        if len(cells) >= 2 and cells[0] and cells[1]:
            meta[cells[0].strip()] = cells[1].strip()
    if header_i is None:
        raise ValueError("Price List CSV has no header")
    table = io.StringIO("\n".join(lines[header_i:]) + "\n")
    rows = list(csv.DictReader(table))
    return meta, rows


def format_quote(meta: dict[str, str], row: dict, instance_type: str) -> str:
    version = meta.get("Version") or "unknown"
    rate = _cell(row, "RateCode")
    price = _cell(row, "PricePerUnit")
    try:
        shown = f"${float(price):g}"
    except ValueError:
        shown = f"${price}"
    pub = meta.get("Publication Date") or ""
    # Keep offer Version, Publication Date and RateCode in the quote: evidence may only
    # carry source_url/quote/checked_at (plus interruption/request keys). No extra keys.
    q = (
        f"AWS Price List us-east-1 v{version} pub {pub}: RateCode {rate}; "
        f"{instance_type} Linux Shared Used OnDemand "
        f'"PricePerUnit": "{price}" USD/hr ({shown})'
    )
    return q


def parse_record(record: dict, body: str) -> tuple[str | None, str | None, str, dict | None]:
    """Return (price_str, quote, message, meta) for one tracked record.

    meta has offer_version, publication_date, rate_code when a row matches.
    On any parse failure, price and meta are None (caller must not restamp).
    """
    try:
        meta, rows = parse_preamble_and_table(body)
    except ValueError as e:
        return None, None, str(e), None
    inst = instance_type_of(record)
    if not inst:
        return None, None, "no instance_type on record", None
    hits = [row for row in rows if row_matches_filter(row) and _cell(row, "Instance Type") == inst]
    if not hits:
        return None, None, f"no OnDemand Linux Shared Used Hrs row for {inst}", None
    if len(hits) > 1:
        prices = {_cell(r, "PricePerUnit") for r in hits}
        if len(prices) > 1:
            return None, None, f"multiple disagreeing prices for {inst}: {sorted(prices)}", None
    row = hits[0]
    price = _cell(row, "PricePerUnit")
    try:
        val = float(price)
    except ValueError:
        return None, None, f"non-numeric PricePerUnit {price!r}", None
    if val <= 0:
        return None, None, f"non-positive PricePerUnit {price!r}", None
    quote = format_quote(meta, row, inst)
    from core.gpu import MAX_QUOTE
    if len(quote) > MAX_QUOTE:
        return None, None, f"evidence quote longer than {MAX_QUOTE} chars", None
    info = {
        "offer_version": meta.get("Version") or "",
        "publication_date": meta.get("Publication Date") or "",
        "rate_code": _cell(row, "RateCode"),
    }
    if not info["offer_version"] or not info["publication_date"] or not info["rate_code"]:
        return None, None, "missing offer Version, Publication Date, or RateCode", None
    return price, quote, "parsed", info


def filter_csv_lines(lines: Iterable[str]) -> str:
    """Keep preamble, header, and FILTER-matching data rows. Used when streaming the live file."""
    preamble: list[str] = []
    header: str | None = None
    header_fields: list[str] | None = None
    kept: list[str] = []
    for raw in lines:
        line = raw if raw.endswith("\n") else raw + "\n"
        text = line.rstrip("\n")
        if header is None:
            low = text.lower()
            if "sku" in low and "instance type" in low and "priceperunit" in low.replace(" ", ""):
                header = text
                header_fields = next(csv.reader([text]))
                continue
            preamble.append(text)
            if len(preamble) > 30:
                raise ValueError("Price List CSV has no header")
            continue
        row = dict(zip(header_fields, next(csv.reader([text]))))
        if row_matches_filter(row):
            kept.append(text)
    if header is None:
        raise ValueError("Price List CSV has no header")
    return "\n".join([*preamble, header, *kept]) + "\n"


def fetch_filtered_csv(url: str, *, ua: str, timeout: float = DEFAULT_TIMEOUT_S) -> tuple[int | None, str]:
    """Stream a Price List CSV and return (status, filtered body). No network in tests (not used there)."""
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "text/csv,application/octet-stream,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = io.TextIOWrapper(resp, encoding="utf-8", errors="replace", newline="")
            try:
                body = filter_csv_lines(raw)
            except ValueError as e:
                return status, f"parse error: {e}"
            return status, body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, f"{type(e).__name__}"
