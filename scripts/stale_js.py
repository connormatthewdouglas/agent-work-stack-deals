"""0.3.30: static GPU/cost pages are rebuilt only on the daily refresh or a deploy, but a Scout stock check expires after
AVAIL_MAX_AGE_H. Every in/out-of-stock claim carries data-av-checked; this inline script rewrites any claim older than
the limit to "unknown (stale availability, last checked <ET time>)" in the reader's browser, so a page never shows a
stale stock claim between builds. Ranking order on the page is fixed at build time (see LOG 0.3.30)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.gpu_availability import AVAIL_MAX_AGE_H  # noqa: E402

BEGIN, END = "<!-- av-stale -->", "<!-- /av-stale -->"
JS = (BEGIN + "\n<script>(function(){var L=" + str(AVAIL_MAX_AGE_H) + "*36e5,f=new Intl.DateTimeFormat('en-CA',"
      "{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});"
      "document.querySelectorAll('[data-av-checked]').forEach(function(e){var t=Date.parse(e.getAttribute('data-av-checked')),"
      "x=Date.parse(e.getAttribute('data-av-expires')||'')||t+L;if(!t||Date.now()<=x)return;var s='unknown (stale availability, last checked '+f.format(new Date(t)).replace(', ',' ')"
      ".replace(/^24:/,'00:')+' ET)';e.textContent=e.tagName==='SMALL'?'('+s+')':s;e.className='av-stale';});})();</script>\n" + END)


def inject(root: Path) -> int:
    n = 0
    for p in list(root.glob("gpu/**/*.html")) + list(root.glob("cost/**/*.html")) + [root / "index.html"]:
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        t2 = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", t, flags=re.S)
        if "data-av-checked" in t2:
            t2 = t2.replace("</body>", JS + "\n</body>", 1)
            n += 1
        if t2 != t:
            p.write_text(t2, encoding="utf-8")
    return n
