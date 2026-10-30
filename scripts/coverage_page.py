"""/coverage/ and /api/v1/coverage.json: which GPU models Lantern Works has sourced rows for, by vendor.
Built from the generated /api/v1/gpu-prices.json at build time. A cell is 'in stock' only when a current
availability claim says in_stock true (not past availability_expires_at at build time), 'priced' when a
sourced rate exists without such a claim, and absent ('not listed') otherwise. Target models with no rows
are listed as 'not yet tracked', never with a price. No commission or payout fields are copied."""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.gpu import FAMILIES, family_of  # noqa: E402

PATH = "coverage"
SCHEMA = "lantern-works-coverage/1"
# Bjorn's target list (2026-10-30). Slugs must exist in core.gpu.FAMILIES.
TARGETS = ("h100", "h200", "b200", "gh200", "a100", "mi300x", "mi250", "l40s", "l40", "l4", "a10", "a10g", "a40",
           "rtx-a6000", "rtx-6000-ada", "t4", "v100", "rtx-3090", "rtx-4090", "rtx-5090", "rtx-a5000",
           "b300", "rtx-pro-6000", "rtx-a4000", "h200-nvl", "h100-nvl", "gb300", "quadro-rtx-6000")
SURVEY = Path(__file__).resolve().parents[1] / "data" / "gpu_coverage" / "survey.json"


def _ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _in_stock(r, now):
    a = r.get("availability") or {}
    if a.get("in_stock") is not True:
        return False
    exp = _ts(a.get("availability_expires_at"))
    return exp is None or exp > now


def build(doc: dict, now: datetime | None = None, survey: dict | None = None) -> dict:
    # Reference time is the feed's own timestamp so rebuilds are deterministic; static feeds already drop
    # claims within 25 min of expiry, and consumers must still enforce availability_expires_at.
    now = now or _ts(doc.get("feed_updated_at")) or datetime.now(timezone.utc)
    models: dict[str, dict] = {}
    for r in doc.get("rates") or []:
        slug = family_of(r["gpu"])
        key = slug or "other:" + r["gpu"]
        m = models.setdefault(key, {"model": FAMILIES[slug] if slug else r["gpu"], "family": slug,
                                    "status": "tracked", "variants": set(), "vendors": {}})
        m["variants"].add(r["gpu"] + (f" {r['vram_gb']}GB" if r.get("vram_gb") else ""))
        v = m["vendors"].setdefault(r["advertiser"], {"status": "priced", "rows": 0, "checked_at": None})
        v["rows"] += 1
        ck = r.get("checked_at") or r.get("verified_at")
        if ck and (v["checked_at"] is None or ck > v["checked_at"]):
            v["checked_at"] = ck
        if _in_stock(r, now):
            v["status"] = "in stock"
            a = r["availability"]
            if a.get("checked_at") and (v.get("stock_checked_at") or "") < a["checked_at"]:
                v["stock_checked_at"] = a["checked_at"]
    for slug in TARGETS:
        if slug not in models:
            models[slug] = {"model": FAMILIES[slug], "family": slug, "status": "not yet tracked",
                            "variants": set(), "vendors": {}}
    # Separate layer: what each vendor's public catalogue lists (Scout survey). Never merged into 'vendors'.
    for name, lists in ((survey or {}).get("lists") or {}).items():
        slug = family_of(name)
        key = slug or "other:" + name
        m = models.setdefault(key, {"model": FAMILIES[slug] if slug else name, "family": slug,
                                    "status": "not yet tracked", "variants": set(), "vendors": {}})
        m.setdefault("vendor_lists", {}).update(lists)
    out = []
    for m in models.values():
        m["variants"] = sorted(m["variants"])
        m["vendors"] = dict(sorted(m["vendors"].items(), key=lambda kv: kv[0].lower()))
        m["vendor_lists"] = dict(sorted((m.get("vendor_lists") or {}).items(), key=lambda kv: kv[0].lower()))
        m["vendor_count"] = len(m["vendors"])
        m["in_stock_vendor_count"] = sum(1 for v in m["vendors"].values() if v["status"] == "in stock")
        out.append(m)
    out.sort(key=lambda m: (m["status"] != "tracked", -m["vendor_count"], m["model"]))
    vendors = sorted({v for m in out for v in m["vendors"]}, key=str.lower)
    tracked = [m for m in out if m["status"] == "tracked"]
    return {"schema": SCHEMA, "license": "CC BY 4.0", "source": "/api/v1/gpu-prices.json",
            "feed_updated_at": doc.get("feed_updated_at"), "as_of": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cell_values": {"in stock": "sourced rate and a current in-stock claim at build time",
                            "priced": "sourced rate; no current in-stock claim (unknown is not sold out)",
                            "not listed": "vendor absent from the model's vendors map",
                            "vendor_lists (separate)": "vendor's public catalogue names the model (survey); not a price, not a stock claim; 'listed, no sourced price' = catalogue shows it without a price we could source"},
            "counts": {"models_tracked": len(tracked),
                       "targets_tracked": sum(1 for s in TARGETS if models[s]["status"] == "tracked"),
                       "targets_total": len(TARGETS),
                       "targets_not_yet_tracked": [models[s]["model"] for s in TARGETS if models[s]["status"] != "tracked"],
                       "vendors": len(vendors), "cells_priced_or_in_stock": sum(m["vendor_count"] for m in out),
                       "cells_in_stock": sum(m["in_stock_vendor_count"] for m in out),
                       "survey_cells_listed": sum(len(m["vendor_lists"]) for m in out),
                       "survey_models_listed_not_priced": sorted(m["model"] for m in out if m["vendor_lists"] and m["status"] != "tracked")},
            "survey": {k: (survey or {}).get(k) for k in ("surveyed_at", "method", "sources", "not_surveyed")} if survey else None,
            "vendors": vendors, "models": out}


def _page(cov: dict, base: str) -> str:
    e = html.escape
    vs = cov["vendors"]
    head = "".join(f'<th scope="col">{e(v)}</th>' for v in vs)
    rows = []
    for m in cov["models"]:
        if m["status"] != "tracked":
            continue
        cells = []
        for v in vs:
            c = m["vendors"].get(v)
            if not c:
                cells.append('<td class="nl">·</td>')
            else:
                cls = "is" if c["status"] == "in stock" else "pr"
                cells.append(f'<td class="{cls}" title="{e(c["status"])}; checked {e(str(c["checked_at"] or "")[:16])}">'
                             f'{"in stock" if cls == "is" else "priced"}</td>')
        link = (f'<a href="{base}/gpu/{m["family"]}-rental-price/">{e(m["model"])}</a>'
                if m["family"] and (Path(_ROOT) / "gpu" / f'{m["family"]}-rental-price' / "index.html").exists() else e(m["model"]))
        rows.append(f'<tr><th scope="row">{link}<br><span class="meta">{e(", ".join(m["variants"]))}</span></th>{"".join(cells)}</tr>')
    c = cov["counts"]
    nyt = ", ".join(e(x) for x in c["targets_not_yet_tracked"]) or "none"
    return f"""  <nav class="crumbs"><a href="{base}/">Lantern Works</a> › GPU coverage</nav>
  <h1>GPU coverage: which models and vendors we track</h1>
  <p>Every GPU model below has at least one rate sourced from the vendor's own page. Built from the live <a href="{base}/api/v1/gpu-prices.json">GPU price feed</a> (feed updated {e(str(cov["feed_updated_at"] or ""))}; stock as of {e(cov["as_of"])}). Machine-readable: <a href="{base}/api/v1/coverage.json">/api/v1/coverage.json</a>.</p>
  <p><strong>{c["models_tracked"]}</strong> GPU models across <strong>{c["vendors"]}</strong> vendors; {c["targets_tracked"]} of {c["targets_total"]} target models tracked. <strong>in stock</strong> = a current in-stock claim at build time; <strong>priced</strong> = sourced rate with no current stock claim (unknown, not sold out); <strong>·</strong> = not listed. Stock claims expire; check <code>availability_expires_at</code> in the feed.</p>
  <p>Not yet tracked (no sourced rows yet, so no price shown): {nyt}. See <a href="#vendor-lists">what vendors list</a> for models a vendor offers that are not priced here yet.</p>
  <div style="overflow-x:auto"><table class="cov"><thead><tr><th scope="col">GPU</th>{head}</tr></thead><tbody>
{chr(10).join(rows)}
  </tbody></table></div>
{_survey_html(cov)}
  <style>.cov{{border-collapse:collapse;font-size:.8rem}}.cov th,.cov td{{border:1px solid #ddd;padding:.25rem .35rem;white-space:nowrap}}.cov thead th{{writing-mode:vertical-rl;transform:rotate(180deg);font-weight:600}}.cov td.is{{background:#dcfce7}}.cov td.pr{{background:#eef2ff}}.sv thead th{{writing-mode:horizontal-tb;transform:none}}.cov td.ls{{background:#fef9c3}}.cov td.np{{background:#ffedd5}}.cov td.nl{{color:#bbb;text-align:center}}</style>"""


_ROOT = "."


def _survey_html(cov: dict) -> str:
    sv = cov.get("survey")
    if not sv:
        return ""
    e = html.escape
    vs = sorted({v for m in cov["models"] for v in m["vendor_lists"]}, key=str.lower)
    rows = []
    for m in cov["models"]:
        if not m["vendor_lists"]:
            continue
        cells = "".join(f'<td class="{"ls" if m["vendor_lists"].get(v) == "listed" else ("np" if v in m["vendor_lists"] else "nl")}">'
                        f'{e(m["vendor_lists"].get(v) or "·")}</td>' for v in vs)
        tag = "" if m["status"] == "tracked" else ' <span class="meta">(not yet priced in our feed)</span>'
        rows.append(f'<tr><th scope="row">{e(m["model"])}{tag}</th>{cells}</tr>')
    srcs = " · ".join(f'<a href="{e(u)}" rel="nofollow noopener">{e(v)}</a>' for v, u in (sv.get("sources") or {}).items())
    return f"""  <h2 id="vendor-lists">What vendors list (catalogue survey, separate from prices)</h2>
  <p>This table is <strong>not</strong> our price feed. It records which models each vendor's public catalogue names, read on {e(str(sv.get("surveyed_at") or ""))} from {srcs}. A listing is not a sourced price and not a stock claim; "listed, no sourced price" means the vendor shows the model but we could not source a price for it. Not surveyed: {e(", ".join(sv.get("not_surveyed") or []))}.</p>
  <div style="overflow-x:auto"><table class="cov sv"><thead><tr><th scope="col">GPU</th>{"".join(f'<th scope="col">{e(v)}</th>' for v in vs)}</tr></thead><tbody>
{chr(10).join(rows)}
  </tbody></table></div>"""


def write(g) -> str:
    global _ROOT
    _ROOT = str(g.ROOT)
    doc = json.loads((Path(g.ROOT) / "api" / "v1" / "gpu-prices.json").read_text(encoding="utf-8"))
    survey = json.loads(SURVEY.read_text(encoding="utf-8")) if SURVEY.exists() else None
    cov = build(doc, survey=survey)
    api = Path(g.ROOT) / "api" / "v1" / "coverage.json"
    api.write_text(json.dumps(cov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    out = Path(g.ROOT) / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell("GPU coverage by model and vendor | Lantern Works",
                                "Which GPU models (H100, H200, B200, A100, L40S, L4, MI300X and more) Lantern Works tracks, by vendor: priced, in stock or not listed.",
                                f"{g.BASE}/{PATH}/", _page(cov, g.BASE)), encoding="utf-8")
    return PATH + "/"
