"""T40: prefilled GitHub 'wrong price' issue link per result. Public row fields only: never the user's query,
workload, conversation or config. A link (not a write tool) keeps a human in the loop."""
from __future__ import annotations

from urllib.parse import urlencode

ISSUE = "https://github.com/connormatthewdouglas/agent-work-stack-deals/issues/new"
FORM_IDS = ("problem", "vendor", "gpu", "deal_id", "shown_price", "observed_price", "source_url", "page_url", "observed_at", "notes")


def report_issue_url(r: dict, tool: str = "compare_gpu_prices") -> str:
    vendor = r.get("advertiser") or r.get("vendor") or ""
    price = r.get("hourly_usd", r.get("hourly_equiv_usd", r.get("price_usd")))
    gpu = " ".join(str(x) for x in (r.get("gpu"), f"{r['vram_gb']} GB" if r.get("vram_gb") else "", r.get("tier")) if x)
    q = {"template": "wrong-price.yml", "title": f"[wrong price] {vendor} {r.get('gpu') or ''}".strip(),
         "vendor": vendor, "gpu": gpu, "deal_id": r.get("deal_id") or "",
         "shown_price": "" if price is None else f"{price:g}/hr" if isinstance(price, (int, float)) else str(price),
         "source_url": r.get("source_url") or "", "page_url": f"mcp:{tool}"}
    return f"{ISSUE}?{urlencode({k: v for k, v in q.items() if v})}"
