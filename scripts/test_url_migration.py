#!/usr/bin/env python3
"""URL-migration smoke test against the live site (HTTPS only).

- Old GitHub Pages URLs (connormatthewdouglas.github.io/agent-work-stack-deals/...) must 301 to
  the same path on https://thelanternworks.com
- Key pages, canonicals, sitemap URLs and skill links return 200
- /deals.json and /api/v1/deals.json are byte-identical (and match the gist mirror)
Usage: python3 scripts/test_url_migration.py [--all-sitemap] [--no-gist]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request

NEW = "https://thelanternworks.com"
OLD = "https://connormatthewdouglas.github.io/agent-work-stack-deals"
GIST_RAW = "https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json"
KEY_PATHS = ["/", "/deals.json", "/api/v1/deals.json", "/schema.json", "/sitemap.xml", "/robots.txt",
             "/agent.json", "/changelog/", "/lanternworks/", "/for-agents/",
             "/skills/lantern-works-deals/SKILL.html", "/SKILL.md", "/query_deals.py", "/USAGE.html", "/install/", "/api/v1/gpu-prices.json"]
OLD_PATHS = ["/", "/deals.json", "/sitemap.xml", "/changelog/", "/lanternworks/", "/for-agents/",
             "/skills/lantern-works-deals/SKILL.html", "/SKILL.md", "/query_deals.py", "/USAGE.html"]
UA = {"User-Agent": "LanternWorksMigrationTest/1.0"}
fails: list[str] = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def req(url, follow=True):
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    for attempt in range(3):
        try:
            r = opener.open(urllib.request.Request(url, headers=UA), timeout=20)
            return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < 2:
                time.sleep(2); continue
            return e.code, e.headers, e.read() if e.fp else b""
        except Exception as e:
            if attempt == 2:
                return None, {}, str(e).encode()
            time.sleep(2)


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-sitemap", action="store_true", help="GET every sitemap URL (slower)")
    ap.add_argument("--no-gist", action="store_true")
    a = ap.parse_args()

    for p in OLD_PATHS:
        st, h, _ = req(OLD + p, follow=False)
        loc = (h.get("Location") or "") if h else ""
        check(st == 301 and loc.rstrip("/") == (NEW + p).rstrip("/"), f"old {p} -> {st} {loc}")

    for p in KEY_PATHS:
        st, h, body = req(NEW + p)
        check(st == 200, f"200 {p} ({st})")
        if p == "/" and st == 200:
            m = re.search(rb'<link rel="canonical" href="([^"]+)"', body)
            check(bool(m) and m.group(1).decode().startswith(NEW), f"canonical on / = {m.group(1).decode() if m else None}")
            check(b"github.io" not in body, "no github.io in homepage")

    _, _, feed = req(NEW + "/deals.json?cb=%d" % time.time())
    _, _, v1 = req(NEW + "/api/v1/deals.json?cb=%d" % time.time())
    check(feed == v1 and len(feed) > 1000, f"/deals.json == /api/v1/deals.json ({len(feed)} / {len(v1)} bytes)")
    if not a.no_gist:
        _, _, g = req(GIST_RAW + "?cb=%d" % time.time())
        check(g == feed, f"gist mirror == /deals.json ({len(g)} bytes)")

    st, _, sm = req(NEW + "/sitemap.xml")
    locs = re.findall(r"<loc>([^<]+)</loc>", sm.decode("utf-8", "replace"))
    check(len(locs) > 0 and all(u.startswith(NEW + "/") for u in locs), f"sitemap {len(locs)} URLs all on {NEW}")
    sample = locs if a.all_sitemap else locs[:: max(1, len(locs) // 15)]
    for u in sample:
        st, _, _ = req(u)
        check(st == 200, f"sitemap 200 {u.replace(NEW, '')} ({st})")

    st, _, aj = req(NEW + "/agent.json")
    for u in sorted(set(re.findall(r'https://thelanternworks\.com[^"\s)]*', aj.decode("utf-8", "replace")))):
        s2, _, _ = req(u)
        check(s2 == 200, f"agent.json link {u.replace(NEW, '') or '/'} ({s2})")

    print(f"\n{len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
