"""Unit tests for scripts/recite_verda_prices.py.

Fixtures and an injected clock only: no live network, no dependence on wall time,
and no production Verda list prices hardcoded as expected values.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import recite_verda_prices as V  # noqa: E402
from core.gpu import STALE_DAYS  # noqa: E402

NOW = datetime(2026, 4, 2, 10, 30, tzinfo=timezone.utc)
PAGE_URL = "https://verda.com/pricing"
API_URL = "https://api.example.test/v1/instance-types"
# Fixture-only amounts (not live vendor prices). The page under test is built from these.
PRIOR_ON = "3.000"
PRIOR_SPOT = "1.500"
LIVE_ON = "3.150"
LIVE_SPOT = "1.575"
STAMP = "2026-04-01T12:00:00+00:00"

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "verda-daily-recite.yml"


def _line(on: str, spot: str | None = None) -> str:
    tail = f"${on}/h" + (f" ${spot}/h" if spot else "")
    return f"1x H200 SXM5 141GB 44 170 GB 141 GB {tail}"


def _page(*lines: str) -> str:
    rows = "".join(f"<tr><td>{line}</td></tr>" for line in lines)
    return f"<html><body><table>{rows}</table></body></html>"


def _record(*, price: str, quote: str, interruptible: bool, tier: str, source_url=PAGE_URL, **kw):
    val = float(price)
    rec = {
        "vendor": "Verda (formerly DataCrunch)",
        "gpu": "H200 SXM",
        "vram_gb": 141,
        "price_usd": val,
        "billing_unit": "hourly",
        "hourly_usd": val,
        "interruptible": interruptible,
        "tier": tier,
        "form_factor": "SXM",
        "quote": quote,
        "source_url": source_url,
        "checked_at": STAMP,
        "evidence": {"source_url": source_url, "quote": quote, "checked_at": STAMP},
        "verified_at": STAMP,
    }
    rec.update(kw)
    return rec


def _doc(records):
    return {
        "vendor": "Verda (formerly DataCrunch)",
        "deal_id": None,
        "source_url": PAGE_URL,
        "checked_at": STAMP,
        "billing_granularity": "hourly",
        "records": records,
    }


def _page_pair(on: str, spot: str):
    return [
        _record(price=on, quote=_line(on), interruptible=False, tier="On-demand instance (1x GPU)"),
        _record(price=spot, quote=_line(on, spot), interruptible=True, tier="Spot instance (1x GPU)"),
    ]


def _api_row():
    return _record(
        price="9.000",
        quote="instance-types price_per_hour (1 GPU): $9.000",
        interruptible=False,
        tier="On-demand instance (1x GPU)",
        source_url=API_URL,
        gpu="GB300",
        vram_gb=288,
        form_factor=None,
        batch="wider-gpu",
        price_check="batch",
    )


class FakeFetcher:
    """Test double: returns prepared bodies only. Any unexpected URL is a failed test, not a live fetch."""

    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str):
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError(f"test fetcher must not hit the network; unexpected URL {url}")
        return self.pages[url]


def test_price_move_updates_only_pricing_page_rows_and_uses_injected_clock():
    doc = _doc(_page_pair(PRIOR_ON, PRIOR_SPOT) + [_api_row()])
    api_before = json.loads(json.dumps(doc["records"][2]))
    page = _page(_line(LIVE_ON, LIVE_SPOT))
    result = V.recite(doc, FakeFetcher({PAGE_URL: (200, page)}), NOW)

    assert result.prices_moved and result.should_write and not result.new_holds
    assert result.stamp == "2026-04-02T10:30:00+00:00"
    on, spot, api = result.doc["records"]
    # New amounts come from the fixture page, not a hardcoded production list.
    assert on["price_usd"] == float(LIVE_ON) and spot["price_usd"] == float(LIVE_SPOT)
    assert LIVE_ON in on["quote"] and LIVE_ON in spot["quote"] and LIVE_SPOT in spot["quote"]
    assert on["verified_at"] == spot["verified_at"] == result.stamp
    assert api == api_before
    assert result.doc["checked_at"] == STAMP  # vendor stamp stays: API rows were not re-read
    assert {r["result"] for r in result.report} == {"changed"}


def test_nothing_moved_does_not_write_or_bump_timestamps():
    doc = _doc(_page_pair(PRIOR_ON, PRIOR_SPOT) + [_api_row()])
    before = json.loads(json.dumps(doc))
    page = _page(_line(PRIOR_ON, PRIOR_SPOT))
    result = V.recite(doc, FakeFetcher({PAGE_URL: (200, page)}), NOW)

    assert result.report and all(r["result"] == "unchanged" for r in result.report)
    assert not result.prices_moved and not result.should_write
    # Official refresh would bump verified_at on the working copy; we still must not persist a no-op.
    assert before["records"][0]["price_usd"] == result.doc["records"][0]["price_usd"]
    # should_write is the persistence gate used by the job.
    assert result.should_write is False


def test_vanished_price_keeps_old_value_and_does_not_invent():
    doc = _doc(_page_pair(PRIOR_ON, PRIOR_SPOT))
    result = V.recite(doc, FakeFetcher({PAGE_URL: (200, "<html><body>table redesigned, no 1x row</body></html>")}), NOW)

    assert not result.prices_moved and not result.should_write and not result.new_holds
    on, spot = result.doc["records"]
    assert on["price_usd"] == float(PRIOR_ON) and spot["price_usd"] == float(PRIOR_SPOT)
    assert on["verified_at"] == STAMP and spot["verified_at"] == STAMP
    assert on["quote"] == _line(PRIOR_ON) and PRIOR_ON in on["quote"]
    assert all(str(r["result"]).startswith("unreadable") for r in result.report)
    assert "last_failed_check_at" in on


def test_vanished_past_stale_days_applies_existing_hold_without_inventing_a_price():
    doc = _doc(_page_pair(PRIOR_ON, PRIOR_SPOT))
    later = NOW + timedelta(days=STALE_DAYS + 1)
    result = V.recite(doc, FakeFetcher({PAGE_URL: (200, "<html><body>gone</body></html>")}), later)

    assert not result.prices_moved and result.new_holds and result.should_write
    on, spot = result.doc["records"]
    assert on["price_usd"] == float(PRIOR_ON) and spot["price_usd"] == float(PRIOR_SPOT)
    assert on["quote"] == _line(PRIOR_ON)
    assert on["stale"]["auto"] is True and spot["stale"]["auto"] is True
    assert result.stamp == later.replace(microsecond=0).isoformat()


def test_fetcher_is_not_asked_for_api_catalog_urls():
    doc = _doc(_page_pair(PRIOR_ON, PRIOR_SPOT) + [_api_row()])
    fake = FakeFetcher({PAGE_URL: (200, _page(_line(PRIOR_ON, PRIOR_SPOT)))})
    V.recite(doc, fake, NOW)
    assert fake.calls and all(PAGE_URL in u for u in fake.calls)
    assert all(API_URL not in u for u in fake.calls)


def test_cli_no_write_leaves_file_untouched(tmp_path: Path):
    src = tmp_path / "verda.json"
    doc = _doc(_page_pair(PRIOR_ON, PRIOR_SPOT))
    src.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")
    fake = FakeFetcher({PAGE_URL: (200, _page(_line(LIVE_ON, LIVE_SPOT)))})
    rc = V.main(
        ["--no-write", "--file", str(src), "--now", NOW.isoformat(), "--report", str(tmp_path / "out.json")],
        fetcher=fake,
    )
    assert rc == 0
    assert src.read_text(encoding="utf-8") == before
    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert payload["should_write"] is True and payload["prices_moved"] is True
    # Report amounts are whatever the fixture page listed.
    assert payload["changed"] and payload["changed"][0]["new"] == float(LIVE_ON)


def test_cli_writes_only_when_prices_moved(tmp_path: Path):
    src = tmp_path / "verda.json"
    src.write_text(json.dumps(_doc(_page_pair(PRIOR_ON, PRIOR_SPOT)), indent=2) + "\n", encoding="utf-8")
    fake = FakeFetcher({PAGE_URL: (200, _page(_line(LIVE_ON, LIVE_SPOT)))})
    assert V.main(["--file", str(src), "--now", "2026-04-02T10:30:00Z"], fetcher=fake) == 0
    written = json.loads(src.read_text(encoding="utf-8"))
    assert written["records"][0]["price_usd"] == float(LIVE_ON)
    assert written["records"][0]["verified_at"] == "2026-04-02T10:30:00+00:00"


def _workflow_permissions():
    import yaml
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return wf.get("permissions") or {}, (wf["jobs"]["recite"].get("permissions") or {})


def test_workflow_is_scheduled_before_live_checks_and_does_not_touch_the_gate():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cron: \"30 10 * * *\"" in text  # 10:30 UTC, before validate-and-deploy live-checks at 17 11 * * *
    assert "workflow_dispatch:" in text
    assert "contents: write" in text
    top, job = _workflow_permissions()
    assert "contents" in top and "actions" in top
    assert "contents" in job and "actions" in job
    assert "scout/verda-daily-recite" in text
    assert "recite_verda_prices.py" in text
    assert "generate_seo_pages.py" in text
    assert "check_gpu_sources.py" not in text
    assert "gh pr merge" not in text and "enable-auto-merge" not in text
    assert "merge=true" not in text
    # Never pushes the recite to main; dispatches validate on the daily branch only.
    assert "--ref main" not in text
    assert "validate-and-deploy.yml" in text
    assert "rebase_push_main" not in text


def test_workflow_pushes_the_branch_and_notices_without_opening_a_pr():
    """The daily job pushes the branch and dispatches CI; it must not open a PR.

    Run 44515575500 pushed the branch, then failed at gh pr create with
    'GitHub Actions is not permitted to create or approve pull requests'.
    The repo setting is left as-is; this job no longer needs that permission.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    top, job = _workflow_permissions()
    assert "pull-requests" not in top and "pull-requests" not in job
    assert "gh pr create" not in text
    assert "gh pr edit" not in text
    assert "gh pr list" not in text
    assert "gh pr merge" not in text
    assert "compare/main...scout/verda-daily-recite" in text
    assert "GITHUB_STEP_SUMMARY" in text
    assert "This job does not open a pull request" in text
    assert "does not need pull-requests: write" in text
    assert "## Moved rows" in text
    assert "gh workflow run validate-and-deploy.yml --ref \"$BRANCH\"" in text
    # Force-pushing would clobber a daily branch Mart is handling by hand.
    assert "force-with-lease" not in text and "git push --force" not in text
