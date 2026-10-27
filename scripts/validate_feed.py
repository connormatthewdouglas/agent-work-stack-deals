#!/usr/bin/env python3
"""Validate the public deal feed. Exit non-zero on any error (blocks deploy in CI).

Checks:
  - deals.json conforms to schema.json (JSON Schema 2020-12) + timestamp parsing
  - no private commission/payout/compliance keys or values anywhere in public output
  - /api/v1/deals.json is byte-identical to /deals.json
  - sitemap.xml URLs are on https://thelanternworks.com, no github.io hardcodes in public files
  --gist   : gist mirror raw deals.json is byte-identical to deals.json
  --links  : redeem_url link check (403/429/405/timeouts = warning; 404/410/DNS/5xx-after-retries = error)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_seo_pages as gen  # noqa: E402

GIST_RAW = "https://gist.githubusercontent.com/connormatthewdouglas/ab5c3a8dceaf396d8f0c631913433a5e/raw/deals.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 LanternWorksLinkCheck/1.0"
SOFT_STATUSES = {401, 403, 405, 406, 409, 425, 429, 451, 999}  # bot walls / rate limits: warn only
# Pages that intentionally reference the old host (redirect stubs). Keep empty unless needed.
GITHUB_IO_ALLOW: set[str] = set()

errors: list[str] = []
warnings: list[str] = []


def err(m: str) -> None:
    errors.append(m)
    print(f"ERROR: {m}")


def warn(m: str) -> None:
    warnings.append(m)
    print(f"WARN:  {m}")


def check_schema(feed: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        err("jsonschema not installed (pip install jsonschema)")
        return
    schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    for e in sorted(v.iter_errors(feed), key=lambda e: list(e.absolute_path)):
        err(f"schema: {'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:200]}")
    if feed.get("schema_version") != schema.get("x-schema-version"):
        err(f"schema_version {feed.get('schema_version')} != schema.json x-schema-version {schema.get('x-schema-version')}")
    ids = [d.get("id") for d in feed.get("deals", [])]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        err(f"duplicate deal ids: {sorted(dup)[:10]}")
    deals = feed.get("deals", [])
    for d in deals:
        if d.get("offer_type") not in gen.OFFER_TYPES:
            err(f"{d.get('id')}.offer_type missing/invalid: {d.get('offer_type')!r} (allowed: {', '.join(gen.OFFER_TYPES)})")
        # Truthfulness: nothing may claim verification without a verified_at timestamp.
        if d.get("offer_type") == "verified_discount" and not d.get("verified_at"):
            err(f"{d.get('id')}: offer_type verified_discount requires verified_at (re-verify or use listed_discount)")
        page = ROOT / "deals" / gen.slug_for(d["id"]) / "index.html"
        if page.exists():
            html_text = page.read_text(encoding="utf-8")
            if not d.get("verified_at") and "Verified-on:" in html_text:
                err(f"{d.get('id')}: deal page shows Verified-on but verified_at is null")
            if d.get("verified_at") and f"Verified-on: {str(d['verified_at'])[:10]}" not in html_text:
                err(f"{d.get('id')}: deal page Verified-on date does not match verified_at")
    from collections import Counter
    dist = Counter(d.get("offer_type") for d in deals)
    print("offer_type " + " ".join(f"{k}={dist.get(k, 0)}" for k in gen.OFFER_TYPES))
    n_ver = sum(1 for d in deals if d.get("verified_at"))
    n_upd = sum(1 for d in deals if d.get("updated_at"))
    # Coverage is reported, never failed on: null means "not recorded", and dates are never invented.
    print(f"verified_at coverage={n_ver}/{len(deals)} ({100 * n_ver / max(1, len(deals)):.0f}%) null={len(deals) - n_ver}; "
          f"updated_at coverage={n_upd}/{len(deals)}")
    for d in deals:
        for k in ("updated_at", "verified_at", "expires_at"):
            val = d.get(k)
            if val is None:
                continue
            try:
                datetime.fromisoformat(val.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                err(f"{d.get('id')}.{k}: not ISO-8601: {val!r}")


def check_private(feed: dict) -> None:
    for leak in gen.find_private_leaks(feed):
        err(f"private leak in deals.json: {leak}")
    private = gen.load_private_model()
    public = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix in (".html", ".json", ".xml", ".txt", ".md")
              and ".git" not in p.parts and "scripts" not in p.parts]
    try:
        gen.assert_outputs_clean(public, private)
    except SystemExit as e:
        err(str(e))
    print(f"private_check files={len(public)} private_model={'present' if private else 'absent'}")


def check_static() -> None:
    a, b = (ROOT / "deals.json").read_bytes(), (ROOT / "api/v1/deals.json").read_bytes() if (ROOT / "api/v1/deals.json").exists() else b""
    if a != b:
        err("api/v1/deals.json is not byte-identical to deals.json (run scripts/generate_seo_pages.py)")
    sm = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", sm)
    off = [u for u in locs if not u.startswith(gen.BASE + "/")]
    if off:
        err(f"sitemap has {len(off)} URLs not on {gen.BASE}: {off[:3]}")
    if len(set(locs)) != len(locs):
        err("sitemap has duplicate URLs")
    print(f"sitemap_urls={len(locs)}")
    for p in ROOT.rglob("*"):
        if not p.is_file() or ".git" in p.parts or p.suffix not in (".html", ".json", ".xml", ".txt", ".md", ".py", ".yml"):
            continue
        rel = str(p.relative_to(ROOT))
        if rel in GITHUB_IO_ALLOW or rel == "scripts/validate_feed.py" or rel.startswith("scripts/test_url_migration"):
            continue
        if "github.io" in p.read_text(encoding="utf-8", errors="replace"):
            err(f"github.io hardcode in {rel}")


def fetch(url: str, method: str = "GET", timeout: int = 20) -> tuple[int | None, str]:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if method == "GET":
                r.read(2048)
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # DNS, TLS, timeout
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def check_gist() -> None:
    req = urllib.request.Request(GIST_RAW + f"?cb={int(time.time())}", headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    try:
        body = urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        warn(f"gist fetch failed ({type(e).__name__}); parity not checked")
        return
    local = (ROOT / "deals.json").read_bytes()
    if body != local:
        err(f"gist mirror differs from deals.json (gist sha256 {hashlib.sha256(body).hexdigest()[:12]} vs local {hashlib.sha256(local).hexdigest()[:12]})")
    else:
        print("gist_parity=ok")


def check_link(url: str) -> tuple[str, str, str]:
    last = ""
    for attempt in range(3):
        status, why = fetch(url, "GET")
        if status is not None and status < 400:
            return "ok", url, str(status)
        if status in SOFT_STATUSES:
            return "soft", url, str(status)
        if status in (404, 410):
            return "error", url, str(status)
        last = str(status) if status else why
        time.sleep(2 * (attempt + 1))
    # persistent 5xx or network errors after retries
    return ("error" if (last and last[:1] == "5") or "NameResolution" in last or "gaierror" in last else "soft"), url, last


def check_links(feed: dict) -> None:
    urls = sorted({d["redeem_url"] for d in feed["deals"] if d.get("redeem_url")})
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check_link, urls))
    n_ok = sum(1 for r in results if r[0] == "ok")
    for kind, url, why in results:
        if kind == "soft":
            warn(f"link {why}: {url}")
        elif kind == "error":
            err(f"link {why}: {url}")
    print(f"links_checked={len(urls)} ok={n_ok} soft={sum(r[0]=='soft' for r in results)} errors={sum(r[0]=='error' for r in results)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gist", action="store_true", help="check gist mirror byte parity")
    ap.add_argument("--links", action="store_true", help="link-check redeem URLs")
    a = ap.parse_args()
    feed = json.loads((ROOT / "deals.json").read_text(encoding="utf-8"))
    print(f"deals={len(feed.get('deals', []))}")
    check_schema(feed)
    check_private(feed)
    check_static()
    if a.gist:
        check_gist()
    if a.links:
        check_links(feed)
    print(f"\nRESULT: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
