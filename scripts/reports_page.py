"""Pulse weekly reports: /reports/<slug>/ rendered verbatim from data/reports/<slug>.md (a copy; the source is never edited),
plus a /reports/ index. Canonical is each page's own URL; front-matter canonical_url/published are ignored."""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "reports"
# Report rows for models whose /gpu/ page exists now but was blank in the source table's Page column.
PAGE_LINKS = {"B300 288GB": ("B300", "b300"), "MI300X 192GB": ("MI300X", "mi300x"), "L4 24GB": ("L4", "l4")}
FORBIDDEN = re.compile(r"github\.com|connormatthewdouglas|/workspace/|/home/", re.I)


def front_matter(md: str):
    meta = {}
    if md.startswith("---\n"):
        end = md.index("\n---\n", 4)
        for line in md[4:end].splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
        md = md[end + 5:]
    return meta, md


_RENTAL_LINK = re.compile(r"\[([^\]]+)\]\((https://thelanternworks\.com)?(/gpu/[a-z0-9-]+-rental-price/?)\)")


def guard_rental_links(md: str, root: Path | None = None) -> str:
    """A model page that was not built must not stay linked. The label remains as text.

    `root` is the site root to check. Tests pass a temp tree; the generator uses the repo.
    """
    base = root or ROOT

    def repl(m):
        path = m.group(3).strip("/")
        if (base / path).is_dir():
            return m.group(0)
        return m.group(1)
    return _RENTAL_LINK.sub(repl, md)


def link_rows(gen, md: str) -> str:
    out = []
    for line in md.splitlines():
        cells = line.split("|")
        if len(cells) >= 7 and cells[1].strip() in PAGE_LINKS and cells[-2].strip() == "":
            label, slug = PAGE_LINKS[cells[1].strip()]
            if (ROOT / "gpu" / f"{slug}-rental-price").is_dir():
                cells[-2] = f" [{label}]({gen.BASE}/gpu/{slug}-rental-price/) "
                line = "|".join(cells)
        out.append(line)
    return "\n".join(out)


def inline(gen, s: str) -> str:
    esc = gen.esc
    parts, pos = [], 0
    for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`|(https?://[^\s)]+)", s):
        parts.append(esc(s[pos:m.start()]))
        if m.group(1) is not None:
            parts.append(f'<a href="{esc(m.group(2))}">{inline(gen, m.group(1))}</a>')
        elif m.group(3) is not None:
            parts.append(f"<strong>{inline(gen, m.group(3))}</strong>")
        elif m.group(4) is not None:
            parts.append(f"<em>{inline(gen, m.group(4))}</em>")
        elif m.group(5) is not None:
            parts.append(f"<code>{esc(m.group(5))}</code>")
        else:
            parts.append(f'<a href="{esc(m.group(6))}">{esc(m.group(6))}</a>')
        pos = m.end()
    parts.append(esc(s[pos:]))
    return "".join(parts)


def render(gen, md: str) -> str:
    out, para, lst, tbl = [], [], [], []

    def flush():
        if para:
            out.append(f"<p>{inline(gen, ' '.join(para))}</p>"); para.clear()
        if lst:
            out.append("<ul>" + "".join(f"<li>{inline(gen, x)}</li>" for x in lst) + "</ul>"); lst.clear()
        if tbl:
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in tbl if not re.match(r"^\|[\s\-|:]+\|$", r.strip())]
            head, body = rows[0], rows[1:]
            out.append('<div class="tscroll"><table class="howto"><thead><tr>' + "".join(f"<th>{inline(gen, c)}</th>" for c in head)
                       + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{inline(gen, c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</tbody></table></div>"); tbl.clear()

    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith("|"):
            if para or lst:
                flush()
            tbl.append(s); continue
        if tbl:
            flush()
        if not s.strip():
            flush(); continue
        mimg = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", s.strip())
        if mimg:
            flush()
            alt, src = mimg.group(1), mimg.group(2).strip()
            if re.search(r"://|^/|\\|\.\.", src):
                raise ValueError(f"report image src must be a same-directory relative file, got {src!r}")
            esc = gen.esc
            out.append(f'<p><img src="{esc(src)}" alt="{esc(alt)}" /></p>')
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", s)
        if m:
            flush(); n = len(m.group(1)) + 1
            out.append(f"<h{n}>{inline(gen, m.group(2))}</h{n}>"); continue
        if s.startswith("- "):
            if para:
                flush()
            lst.append(s[2:]); continue
        para.append(s.strip())
    flush()
    return "\n  ".join(out)


def _report_date(p: Path) -> str:
    """Sort key: front-matter date, else a YYYY-MM-DD stamp in the filename."""
    meta, _ = front_matter(p.read_text(encoding="utf-8"))
    m = re.search(r"(\d{4}-\d{2}-\d{2})", meta.get("date") or "") or re.search(r"(\d{4}-\d{2}-\d{2})", p.stem)
    return m.group(1) if m else ""


def reports():
    return sorted(SRC.glob("*.md"), key=lambda p: (_report_date(p), p.stem), reverse=True)



def _llms_update(root: Path | None = None) -> None:
    """Keep weekly report bullets in llms.txt in date order (newest first)."""
    path = (root or ROOT) / "llms.txt"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    bullets = []
    for p in reports():
        meta, _ = front_matter(p.read_text(encoding="utf-8"))
        title = meta.get("title") or p.stem
        bullets.append(f"- [{title}](https://thelanternworks.com/reports/{p.stem}/)")
    weekly = "\n".join(bullets)
    text = re.sub(
        r"\n- \[[^\]]+\]\(https://thelanternworks\.com/reports/(?!vendors/)[^/]+/\)[^\n]*",
        "",
        text,
    )
    marker = "- [Vendor sample reports]"
    if marker in text:
        def repl(m):
            return m.group(0) + (("\n" + weekly) if weekly else "")
        text, n = re.subn(r"^- \[Vendor sample reports\][^\n]*$", repl, text, count=1, flags=re.M)
        if n != 1:
            return
    elif "- [GPU price reports]" in text:
        text = text.replace(
            "- [GPU price reports](https://thelanternworks.com/reports/): weekly, newest first",
            "- [GPU price reports](https://thelanternworks.com/reports/): weekly, newest first\n" + weekly,
            1,
        )
    else:
        return
    path.write_text(text, encoding="utf-8")


def write_all(gen) -> list[str]:
    paths, items = [], []
    for p in reports():
        slug = p.stem
        meta, md = front_matter(p.read_text())
        md = guard_rental_links(link_rows(gen, md))
        title = meta.get("title") or slug
        url = f"{gen.BASE}/reports/{slug}/"
        html = render(gen, md)
        assert not FORBIDDEN.search(html), f"forbidden link/path in report {slug}"
        body = (f'  <p class="crumbs"><a href="{gen.BASE}/">Home</a> · <a href="{gen.BASE}/reports/">Reports</a></p>\n'
                f"  <h1>{gen.esc(title)}</h1>\n  {html}\n")
        desc = "Weekly GPU rental price report from Lantern Works: what moved, cheapest on-demand, spot and community rates per GPU, from the public feeds."
        out = ROOT / "reports" / slug
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(gen.page_shell(f"{title} | Lantern Works", desc, url, body))
        asset_dir = SRC / slug
        if asset_dir.is_dir():
            for f in asset_dir.iterdir():
                if f.is_file() and f.suffix.lower() in {".svg", ".png", ".json", ".csv"}:
                    (out / f.name).write_bytes(f.read_bytes())
        paths.append(f"reports/{slug}")
        items.append((slug, title))
    url = f"{gen.BASE}/reports/"
    lis = "".join(f'<li><a href="{gen.BASE}/reports/{s}/">{gen.esc(t)}</a></li>' for s, t in items)
    body = (f'  <p class="crumbs"><a href="{gen.BASE}/">Home</a> · Reports</p>\n  <h1>GPU price reports</h1>\n'
            f"  <p>Weekly GPU rental price reports, newest first. Each one is built from the public "
            f'<a href="{gen.BASE}/api/v1/gpu-prices.json">gpu-prices.json</a> and '
            f'<a href="{gen.BASE}/api/v1/gpu-price-changes.json">gpu-price-changes.json</a> feeds on its date. '
            f'Price data is licensed <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a> (attribution: Lantern Works). '
            f"Some vendor links are referral links; affiliate status does not affect rankings.</p>\n"
            f'  <p>Also: <a href="{gen.BASE}/reports/vendors/">vendor sample reports</a> — one generated page per tracked instance vendor, with rank per GPU, 14-day undercuts, and a chart.</p>\n'
            f"  <ul>{lis}</ul>\n")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "index.html").write_text(gen.page_shell("GPU price reports | Lantern Works",
                                                                "Weekly GPU rental price reports from Lantern Works, newest first.", url, body))
    _llms_update(ROOT)
    return ["reports"] + paths
