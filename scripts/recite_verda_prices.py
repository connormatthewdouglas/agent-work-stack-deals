#!/usr/bin/env python3
"""Re-cite Verda's verda.com/pricing rows through the official refresh() + Fetcher() path.

Only those pricing-page rows are re-read. API-catalog rows (other source_url values) are
left untouched. This script never invents a missing price: if the official parser cannot
re-read a row, refresh() keeps the last sourced value and applies the existing STALE_DAYS
holds (#265). Snapshots and other vendor files are not written here.

The live job uses Fetcher() (robots.txt honoured). Tests inject a fetcher and a clock;
they must not open the network.

Usage:
  python3 scripts/recite_verda_prices.py [--no-write] [--report PATH] [--now ISO8601]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import refresh_gpu_prices as R  # noqa: E402
from core.gpu import PRICING_DIR, STALE_DAYS  # noqa: E402

PAGE_URL_MARK = "verda.com/pricing"
VENDOR_FILE = PRICING_DIR / "verda.json"


def is_pricing_page_row(record: dict) -> bool:
    return PAGE_URL_MARK in (record.get("source_url") or "")


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    now = datetime.fromisoformat(text)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _key(record: dict) -> tuple:
    return (record.get("gpu"), record.get("tier"), record.get("vram_gb"), record.get("interruptible"))


def _had_auto_hold(record: dict) -> bool:
    stale = record.get("stale") or {}
    return bool(stale.get("auto"))


@dataclass
class ReciteResult:
    """Outcome of a Verda pricing-page re-cite. doc is the merged vendor document."""

    doc: dict
    report: list[dict]
    stamp: str | None
    prices_moved: bool
    new_holds: bool
    should_write: bool

    def as_dict(self) -> dict[str, Any]:
        changed = [r for r in self.report if r.get("result") == "changed"]
        unreadable = [r for r in self.report if str(r.get("result") or "").startswith("unreadable")]
        unchanged = [r for r in self.report if r.get("result") == "unchanged"]
        return {
            "should_write": self.should_write,
            "prices_moved": self.prices_moved,
            "new_holds": self.new_holds,
            "stamp": self.stamp,
            "changed": changed,
            "unchanged": unchanged,
            "unreadable": unreadable,
            "report": self.report,
        }


def recite(doc: dict, fetcher: Any, now: datetime, stale_days: int = STALE_DAYS) -> ReciteResult:
    """Re-read pricing-page rows on a copy, merge them back, leave every other row alone.

    does not bump the vendor-level checked_at: only a subset of records is attempted.
    """
    if not isinstance(doc, dict) or not doc.get("records"):
        raise ValueError("verda pricing document has no records")
    original = copy.deepcopy(doc)
    page_idx = [i for i, r in enumerate(doc["records"]) if is_pricing_page_row(r)]
    if not page_idx:
        return ReciteResult(doc=copy.deepcopy(doc), report=[], stamp=None,
                            prices_moved=False, new_holds=False, should_write=False)

    page_doc = copy.deepcopy(doc)
    page_doc["records"] = [copy.deepcopy(doc["records"][i]) for i in page_idx]
    before_holds = {_key(r): _had_auto_hold(r) for r in page_doc["records"]}
    report = R.refresh([page_doc], fetcher, now, stale_days=stale_days)

    merged = copy.deepcopy(original)
    new_by = {_key(r): r for r in page_doc["records"]}
    for i in page_idx:
        k = _key(merged["records"][i])
        if k not in new_by:
            raise RuntimeError(f"refresh dropped pricing-page row {k}")
        merged["records"][i] = new_by[k]

    # API-catalog / other rows must be byte-for-byte the pre-refresh records
    for i, rec in enumerate(merged["records"]):
        if i not in page_idx and rec != original["records"][i]:
            raise RuntimeError("non-pricing-page Verda row was mutated")

    prices_moved = any(r.get("result") == "changed" for r in report)
    new_holds = any(_had_auto_hold(r) and not before_holds.get(_key(r), False)
                    for r in page_doc["records"])
    # Prefer the official verified_at written on a successful re-read (report is 1:1 with page rows).
    success_stamps = []
    for rec, row in zip(page_doc["records"], report):
        if row.get("result") in ("changed", "unchanged") and rec.get("verified_at"):
            success_stamps.append(rec["verified_at"])
    stamp = success_stamps[0] if success_stamps else (_iso(now) if new_holds else None)
    should_write = bool(prices_moved or new_holds)
    return ReciteResult(doc=merged, report=report, stamp=stamp,
                        prices_moved=prices_moved, new_holds=new_holds, should_write=should_write)


def load_vendor(path: Path | None = None) -> dict:
    return json.loads((path or VENDOR_FILE).read_text(encoding="utf-8"))


def write_vendor(doc: dict, path: Path | None = None) -> None:
    dest = path or VENDOR_FILE
    dest.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None, fetcher: Any | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-write", action="store_true", help="run the official refresh but do not write verda.json")
    ap.add_argument("--report", help="write a JSON report here")
    ap.add_argument("--now", help="UTC clock (ISO-8601). Default: wall clock. Tests must pass this.")
    ap.add_argument("--file", default=str(VENDOR_FILE), help="vendor JSON path (default: data/gpu_pricing/verda.json)")
    args = ap.parse_args(argv)
    now = _parse_now(args.now)
    fetch = fetcher if fetcher is not None else R.Fetcher()
    result = recite(load_vendor(Path(args.file)), fetch, now)
    if result.should_write and not args.no_write:
        write_vendor(result.doc, Path(args.file))
    payload = result.as_dict()
    text = json.dumps(payload, indent=2, default=str) + "\n"
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
