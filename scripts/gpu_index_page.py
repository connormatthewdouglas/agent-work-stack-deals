"""/gpu/index/ and /gpu/index/methodology/ (T21): the Lantern Works GPU Price Index, rendered from
api/v1/gpu-price-index.json (computed by scripts/gpu_index.py from the committed daily snapshots) and
docs/GPU-INDEX-METHODOLOGY.md. No number is typed here."""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

import gpu_index

PATH = "gpu/index"
MPATH = "gpu/index/methodology"
CHART_MIN_DAYS, TREND_MIN_DAYS = 14, 30


def _md(md: str) -> str:
    """Small Markdown renderer for the methodology file (headings, tables, lists, quotes, code, paragraphs)."""
    esc = html.escape
    def inline(s):
        s = esc(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        return re.sub(r"(https://[^\s<)]+[^\s<).,])", r'<a href="\1" rel="noopener">\1</a>', s)
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + esc("\n".join(lines[i + 1:j])) + "</pre>"); i = j + 1; continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                if not all(re.fullmatch(r"-+", c) for c in cells):
                    rows.append(cells)
                i += 1
            out.append('<div class="tscroll"><table class="howto"><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in rows[0])
                       + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
                       + "</tbody></table></div>"); continue
        m = re.match(r"(#{1,3}) (.*)", ln)
        if m:
            n = len(m.group(1)) + 1
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>"); i += 1; continue
        if re.match(r"\s*(-|\d+\.) ", ln):
            tag = "ol" if re.match(r"\s*\d+\.", ln) else "ul"
            items = []
            while i < len(lines) and re.match(r"\s*(-|\d+\.) ", lines[i]):
                items.append(re.sub(r"\s*(-|\d+\.) ", "", lines[i], count=1)); i += 1
                while i < len(lines) and lines[i].startswith("   ") and lines[i].strip():
                    items[-1] += " " + lines[i].strip(); i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>"); continue
        if ln.startswith("> "):
            out.append(f"<blockquote>{inline(ln[2:])}</blockquote>"); i += 1; continue
        if not ln.strip():
            i += 1; continue
        para = [ln]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"(#|\||```|> |\s*(-|\d+\.) )", lines[i]):
            para.append(lines[i]); i += 1
        out.append("<p>" + inline(" ".join(para)) + "</p>")
    return "\n".join(out)


def _money(v, d=4):
    return "n/a" if v is None else f"${v:,.{d}f}".rstrip("0").rstrip(".") if d == 4 else f"${v:,.2f}"


def write_all(g) -> list[str]:
    root = Path(g.ROOT)
    gpu_index.main_args(str(root), str(root / "api" / "v1"))
    idx = json.loads((root / "api" / "v1" / "gpu-price-index.json").read_text(encoding="utf-8"))
    base, esc = g.BASE, html.escape
    hist = idx["history"]
    cur = hist[-1]
    n_days = (date.fromisoformat(cur["date"]) - date.fromisoformat(idx["history_starts"])).days + 1
    mc = cur.get("vs_previous_day_matched") or {}
    rows = []
    for s, v in cur["series"].items():
        m = mc.get(s) or {}
        chg = "n/a" if m.get("matched_change_pct") is None else f"{m['matched_change_pct']:+.2f}% ({m['matched_vendors']} matched vendors)"
        low = " <strong>[low coverage]</strong>" if v["low_coverage"] else ""
        rows.append(f"<tr><td data-label=\"GPU\">{esc(s)}{low}</td><td data-label=\"Median\">{_money(v['median_usd_per_gpu_hour'])}/hr</td>"
                    f"<td data-label=\"Lowest\">{_money(v['min_usd_per_gpu_hour'])}/hr</td><td data-label=\"Vendors\">{v['vendors']}</td>"
                    f"<td data-label=\"730 h basis\">{_money(v['monthly_basis_usd'], 2)}</td><td data-label=\"Day change\">{esc(chg)}</td></tr>")
    early = ("" if n_days >= TREND_MIN_DAYS else
             "<p><strong>Early data, coverage still growing; changes mostly reflect new vendors.</strong> "
             f"Trend claims wait for {TREND_MIN_DAYS} days of history.</p>")
    attribution = ("Source: Lantern Works GPU Price Index (https://thelanternworks.com), licensed CC BY 4.0. Median on-demand rental price "
                   f"per GPU-hour across tracked vendors; methodology at {base}/{MPATH}/.")
    body = f"""  <h1>Lantern Works GPU Price Index</h1>
  <p class="meta"><strong>History: {n_days} days since {esc(idx['history_starts'])}</strong> · latest {esc(cur['date'])} · license {esc(idx['license'])}</p>
  <p>A daily reference rental price per GPU: the median across tracked vendors of each vendor's lowest on-demand-class rate (one vote per vendor), in USD per GPU-hour. Held, spot/interruptible, reserved/committed and thin or unknown-count marketplace rows are excluded. <a href="{base}/{MPATH}/">Methodology</a>.</p>
  {early}
  <div class="tscroll rates-cards"><table class="howto"><thead><tr><th>GPU</th><th>Median per GPU-hour</th><th>Lowest</th><th>Vendors</th><th>Monthly basis (730 h)</th><th>Matched-vendor change vs previous day</th></tr></thead><tbody>
  {''.join(rows)}
  </tbody></table></div>
  <p class="meta">Low coverage = fewer than 3 vendors; don't headline these. The monthly basis is median × 730 h, a comparison basis, not a quote. The day change compares only vendors present on both days, so a newly tracked provider doesn't count as a price move.</p>
  <p>Download: <a href="{base}/api/v1/gpu-price-index.json">JSON</a> (full history with included/excluded row keys) · <a href="{base}/api/v1/gpu-price-index.csv">CSV</a>. Per-vendor rates and sources: <a href="{base}/gpu/price-comparison/">GPU price comparison</a>.</p>
  <h2 id="attribution">Attribution (CC BY 4.0)</h2>
  <blockquote>{esc(attribution)}</blockquote>
  <p class="meta">Short form: Data: Lantern Works GPU Price Index, CC BY 4.0. Data license: <a href="https://creativecommons.org/licenses/by/4.0/" rel="license noopener">CC BY 4.0</a>; code MIT.</p>
"""
    out = root / PATH / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(g.page_shell("Lantern Works GPU Price Index: daily median GPU rental price",
                                f"Daily median on-demand rental price per GPU-hour for H100, A100, H200, L40S, RTX 4090 and RTX 5090 across tracked vendors. CC BY 4.0.",
                                f"{base}/{PATH}/", body), encoding="utf-8")
    md = (root / "docs" / "GPU-INDEX-METHODOLOGY.md").read_text(encoding="utf-8")
    mout = root / MPATH / "index.html"
    mout.parent.mkdir(parents=True, exist_ok=True)
    mout.write_text(g.page_shell("GPU Price Index methodology | Lantern Works",
                                 "How the Lantern Works GPU Price Index is computed: which rows count, the statistic, matched-vendor changes, license.",
                                 f"{base}/{MPATH}/", _md(md) + f'\n  <p class="meta"><a href="{base}/{PATH}/">Back to the index</a></p>\n'), encoding="utf-8")
    return [PATH, MPATH]
