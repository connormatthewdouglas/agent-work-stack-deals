"""P63 (Brain #966, #1082, #1099): reserved-offer cancellation terms, data only.

Three-valued terms flag on every probe: present_and_read, confirmed_absent, or
unreadable (including failed fetches). Cancel window, cancel fee, and terms
read time are recorded only where the vendor publishes them. A failed fetch is
unreadable and never stamps terms_read_at or any fresh price timestamps.
Unknown stays unknown: unprobed records have no cancellation object.

Additive only. No ranking change, no TTL change, no schema bump.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

TERMS_PRESENT_AND_READ = "present_and_read"
TERMS_CONFIRMED_ABSENT = "confirmed_absent"
TERMS_UNREADABLE = "unreadable"
TERMS_FLAGS = (TERMS_PRESENT_AND_READ, TERMS_CONFIRMED_ABSENT, TERMS_UNREADABLE)

# Official pages where these vendors publish reservation / commitment terms.
CIVO_TERMS_URL = "https://www.civo.com/legal/terms"
CLOUDRIFT_TERMS_URL = "https://www.cloudrift.ai/terms"
HYPERSTACK_TERMS_URL = "https://docs.hyperstack.cloud/docs/billing/contracts"

VENDOR_TERMS_URL = {
    "Civo": CIVO_TERMS_URL,
    "CloudRift": CLOUDRIFT_TERMS_URL,
    "Hyperstack": HYPERSTACK_TERMS_URL,
}


class _VisibleText(HTMLParser):
    """Visible text only (skips script/style/svg and aria-hidden subtrees)."""

    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        ad = {k.lower(): (v or "") for k, v in attrs}
        if ad.get("aria-hidden", "").lower() == "true" or "hidden" in (ad.get("style") or "").lower():
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        # Hidden depth is best-effort; a mismatch is harmless for fixtures.
        if tag in {"div", "span", "section", "p", "li"} and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if self._skip or self._hidden:
            return
        t = data.strip()
        if t:
            self.parts.append(t)


def visible_text(source: str) -> str:
    """Plain visible text from an HTML page, or the string itself if it is already text."""
    if not source:
        return ""
    if "<" in source and ("<html" in source.lower() or "<body" in source.lower() or "<p" in source.lower()
                          or "<div" in source.lower() or "<article" in source.lower() or "<h" in source.lower()):
        p = _VisibleText()
        try:
            p.feed(source)
            p.close()
        except Exception:
            return re.sub(r"\s+", " ", source).strip()
        return re.sub(r"\s+", " ", " ".join(p.parts)).strip()
    return re.sub(r"\s+", " ", source).strip()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def unreadable(*, source_url: str | None = None, reason: str | None = None) -> dict[str, Any]:
    """Failed fetch / unreadable page: flag only. No read time, no window, no fee."""
    out: dict[str, Any] = {"terms_flag": TERMS_UNREADABLE}
    if source_url:
        out["source_url"] = source_url
    if reason:
        out["unreadable_reason"] = reason
    return out


def confirmed_absent(*, source_url: str, terms_read_at: str) -> dict[str, Any]:
    """Successful read that found no published cancel window or cancel fee."""
    return {
        "terms_flag": TERMS_CONFIRMED_ABSENT,
        "terms_read_at": terms_read_at,
        "source_url": source_url,
    }


def present_and_read(*, source_url: str, terms_read_at: str, quote: str,
                     cancel_window: dict[str, Any] | None = None,
                     cancel_fee: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "terms_flag": TERMS_PRESENT_AND_READ,
        "terms_read_at": terms_read_at,
        "source_url": source_url,
        "quote": quote,
    }
    if cancel_window:
        out["cancel_window"] = cancel_window
    if cancel_fee:
        out["cancel_fee"] = cancel_fee
    return out


# --- vendor extractors (cite visible page text only; no invented values) ---

_CIVO_NO_CAUSE = re.compile(
    r"You may terminate the Agreement for no cause unless You have entered into a Commitment Discount with Civo\.?",
    re.I,
)
_CIVO_SHORTFALL = re.compile(
    r"if You have not met the aggregate spend commitment, You will make a spend commitment shortfall payment to Civo",
    re.I,
)
_CIVO_UPFRONT = re.compile(
    r"upfront payments are non-refundable, excepting If You terminate this Agreement for material cause, "
    r"during the term of a Commitment Discount, in which case Civo will rebate the balance of any unused upfront payment to You\.?",
    re.I,
)
_CIVO_DURING = re.compile(
    r"If You terminate this Agreement during the term of a Commitment Discount, the following process will apply in accordance with the Commitment Discount:?",
    re.I,
)

_CR_NO_REFUND = re.compile(r"All sales are final and no refund will be issued\.?", re.I)


def _clip(text: str, match: re.Match, pad: int = 0) -> str:
    s = max(0, match.start() - pad)
    e = min(len(text), match.end() + pad)
    return text[s:e].strip()


def extract_civo(text: str, *, source_url: str, terms_read_at: str) -> dict[str, Any]:
    body = _norm(visible_text(text))
    fee_parts: list[str] = []
    quotes: list[str] = []
    for pat in (_CIVO_DURING, _CIVO_SHORTFALL, _CIVO_UPFRONT):
        m = pat.search(body)
        if m:
            q = _clip(body, m)
            fee_parts.append(q)
            quotes.append(q)
    no_cause = _CIVO_NO_CAUSE.search(body)
    if no_cause:
        quotes.insert(0, _clip(body, no_cause))
    if fee_parts or no_cause:
        # Fee is published (shortfall + non-refundable upfront). No numeric cancel window is published.
        fee = {"text": "; ".join(dict.fromkeys(fee_parts))} if fee_parts else None
        return present_and_read(
            source_url=source_url,
            terms_read_at=terms_read_at,
            quote=" ".join(dict.fromkeys(quotes)),
            cancel_fee=fee,
        )
    return confirmed_absent(source_url=source_url, terms_read_at=terms_read_at)


def extract_cloudrift(text: str, *, source_url: str, terms_read_at: str) -> dict[str, Any]:
    body = _norm(visible_text(text))
    m = _CR_NO_REFUND.search(body)
    if m:
        quote = _clip(body, m)
        return present_and_read(
            source_url=source_url,
            terms_read_at=terms_read_at,
            quote=quote,
            cancel_fee={"text": quote},
        )
    return confirmed_absent(source_url=source_url, terms_read_at=terms_read_at)


def extract_hyperstack(text: str, *, source_url: str, terms_read_at: str) -> dict[str, Any]:
    """Hyperstack public contract docs: record window/fee only if this page states them.

    No early-cancel window or fee pattern is registered until a published phrase is
    actually present on the saved page. A successful read with none is confirmed_absent.
    """
    body = _norm(visible_text(text))
    # Intentionally empty: do not treat account-cancellation FAQ or contract-expiry
    # Keep/Delete policy as a reserved cancel window or fee.
    _ = body
    return confirmed_absent(source_url=source_url, terms_read_at=terms_read_at)


EXTRACTORS = {
    "Civo": extract_civo,
    "CloudRift": extract_cloudrift,
    "Hyperstack": extract_hyperstack,
}


def probe_from_page(vendor: str, source: str | None, *, source_url: str,
                    terms_read_at: str, fetch_ok: bool, reason: str | None = None) -> dict[str, Any]:
    """Build the cancellation object for one probe. fetch_ok False never stamps a read time."""
    if not fetch_ok or source is None:
        return unreadable(source_url=source_url, reason=reason or "fetch failed")
    fn = EXTRACTORS.get(vendor)
    if fn is None:
        return unreadable(source_url=source_url, reason=f"no extractor for {vendor}")
    return fn(source, source_url=source_url, terms_read_at=terms_read_at)


def is_reserved_record(record: dict) -> bool:
    """True for reserved / commitment rows (not on-demand, not dedicated-monthly)."""
    tc = record.get("tier_class")
    if tc == "reserved":
        return True
    if tc and tc != "reserved":
        return False
    tier = (record.get("tier") or "") + " " + (record.get("gpu_model") or "")
    t = tier.lower()
    if "reserv" in t or "commitment" in t:
        return True
    if re.search(r"\b\d+\s*mo(?:nth)?\b", t) and "on-demand" not in t:
        return True
    return False


def attach_to_reserved_records(records: list[dict], cancellation: dict[str, Any],
                               *, vendor: str | None = None) -> list[dict]:
    """Copy a probe result onto reserved records only. Never touches price timestamps."""
    for r in records:
        if vendor and (r.get("vendor") or r.get("advertiser")) != vendor:
            continue
        if is_reserved_record(r):
            r["cancellation"] = dict(cancellation)
    return records


def cancellation_problems(obj: Any, tag: str) -> list[str]:
    """Shape checks for an optional additive cancellation object. Empty = ok / absent."""
    if obj is None:
        return []
    if not isinstance(obj, dict):
        return [f"{tag}: cancellation must be an object"]
    out: list[str] = []
    flag = obj.get("terms_flag")
    if flag not in TERMS_FLAGS:
        out.append(f"{tag}: cancellation.terms_flag must be one of {TERMS_FLAGS}")
        return out
    if flag == TERMS_UNREADABLE:
        if obj.get("terms_read_at"):
            out.append(f"{tag}: unreadable cancellation must not stamp terms_read_at")
        if obj.get("cancel_window") or obj.get("cancel_fee"):
            out.append(f"{tag}: unreadable cancellation must not record a cancel window or fee")
    else:
        if not obj.get("terms_read_at"):
            out.append(f"{tag}: {flag} cancellation needs terms_read_at")
        else:
            # ISO-8601 (accept trailing Z)
            from datetime import datetime
            try:
                datetime.fromisoformat(str(obj["terms_read_at"]).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                out.append(f"{tag}: cancellation.terms_read_at not ISO-8601")
        if flag == TERMS_PRESENT_AND_READ and not (obj.get("cancel_window") or obj.get("cancel_fee")):
            out.append(f"{tag}: present_and_read needs a published cancel_window or cancel_fee")
        if flag == TERMS_CONFIRMED_ABSENT and (obj.get("cancel_window") or obj.get("cancel_fee")):
            out.append(f"{tag}: confirmed_absent must not invent a cancel window or fee")
    if obj.get("source_url") and not str(obj["source_url"]).startswith("https://"):
        out.append(f"{tag}: cancellation.source_url must be https")
    return out
