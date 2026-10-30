"""Region labels -> {label, zone, country, group} (0.3.50, re30 a). Scout publishes provider labels as-is
('US-MD-1 (United States)', 'us-east-1', 'MON1 (CANADA, MONTREAL)', 'FIN-02'); the original label is always kept.

Query rules: a country code ('US') or group ('EU', 'APAC', 'NA') matches every zone in it; anything else is a zone
query, matched exactly on the zone code, case-insensitive, ignoring a '(...)' suffix ('us-ne-1' == 'US-NE-1 (United States)')."""
from __future__ import annotations

import re

COUNTRY_NAMES = {"UNITED STATES": "US", "USA": "US", "CANADA": "CA", "INDIA": "IN", "JAPAN": "JP", "FINLAND": "FI",
                 "ICELAND": "IS", "NORWAY": "NO", "SWEDEN": "SE", "GERMANY": "DE", "FRANCE": "FR", "NETHERLANDS": "NL",
                 "UNITED KINGDOM": "GB", "UK": "GB", "CZECHIA": "CZ", "CZECH REPUBLIC": "CZ", "ROMANIA": "RO", "SINGAPORE": "SG",
                 "AUSTRALIA": "AU", "SOUTH KOREA": "KR", "KOREA": "KR", "TAIWAN": "TW", "SPAIN": "ES", "POLAND": "PL",
                 "ISRAEL": "IL", "BRAZIL": "BR", "ITALY": "IT", "SWITZERLAND": "CH", "IRELAND": "IE", "BELGIUM": "BE"}
GROUPS = {"EU": {"FI", "IS", "NO", "SE", "DE", "FR", "NL", "GB", "CZ", "RO", "ES", "PL", "IT", "CH", "IE", "BE"},
          "NA": {"US", "CA"}, "APAC": {"IN", "JP", "SG", "AU", "KR", "TW"}}
# zone-code prefixes used by tracked providers (RunPod 'US-GA-2', AWS-style 'us-east-1', Verda 'FIN-02', Oblivus 'MON1')
PREFIX = [(r"^US[-_]", "US"), (r"^CA[-_]", "CA"), (r"^AP[-_]([A-Z]{2})[-_]", None), (r"^EUR?[-_]([A-Z]{2})[-_]", None),
          (r"^FIN", "FI"), (r"^ICE", "IS"), (r"^MON\d", "CA"), (r"^TXS\d", "US"), (r"^OSL\d", "NO"),
          (r"^ASIA[-_]SOUTH", "IN"), (r"^ASIA[-_]NORTHEAST", "JP"), (r"^ASIA[-_]SOUTHEAST", "SG"), (r"^NORTHAMERICA", "US")]


def _zone(label: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", str(label or "")).strip().upper().replace("_", "-")


def normalize(label) -> dict:
    lab = str(label or "").strip()
    zone = _zone(lab)
    country = None
    m = re.search(r"\(([^)]*)\)", lab)
    if m:
        for part in (p.strip().upper() for p in m.group(1).split(",")):
            if part in COUNTRY_NAMES:
                country = COUNTRY_NAMES[part]
                break
    if not country:
        for pat, cc in PREFIX:
            mm = re.match(pat, zone)
            if mm:
                country = cc or mm.group(1)
                break
    if not country and re.fullmatch(r"[A-Z]{2}", zone):  # a bare country code label ('US')
        country = zone
    group = zone if zone in GROUPS and not country else None
    group = group or next((g for g, cs in GROUPS.items() if country in cs), None)
    return {"label": lab, "zone": zone, "country": country, "group": group}


def is_area(q: str) -> bool:
    q = str(q or "").strip().upper()
    return q in GROUPS or bool(re.fullmatch(r"[A-Z]{2}", q))


def query(q) -> str:
    """Canonical query: an area code ('US', 'EU') or a zone code without suffix ('US-NE-1')."""
    return _zone(q)


def matches(q, label) -> bool:
    q = query(q)
    n = normalize(label)
    if is_area(q):
        return n["country"] == q or n["group"] == q
    return n["zone"] == q


def any_match(q, labels) -> bool:
    return any(matches(q, x) for x in labels or [])
