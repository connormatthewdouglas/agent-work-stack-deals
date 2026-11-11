"""Vendor sample reports: ranks, 14-day undercuts, missing history, page guards."""
from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import vendor_sample_reports as vsr  # noqa: E402


def test_vendor_slug_known_and_unique():
    names = list(vsr.VENDOR_SLUGS)
    slugs = [vsr.vendor_slug(n) for n in names]
    assert vsr.vendor_slug("RunPod") == "runpod"
    assert vsr.vendor_slug("Verda (formerly DataCrunch)") == "verda"
    assert vsr.vendor_slug("DigitalOcean GPU Droplets") == "digitalocean"
    assert vsr.vendor_slug("Amazon Web Services") == "aws"
    assert vsr.vendor_slug("99Stack Cloud") == "99stack"
    assert len(slugs) == len(set(slugs))
    for s in slugs:
        assert s and s == s.lower() and " " not in s


def test_window_days_inclusive():
    start, end, days = vsr.window_days(date(2026, 11, 11), 14)
    assert start == date(2026, 10, 29) and end == date(2026, 11, 11)
    assert len(days) == 14 and days[0] == start and days[-1] == end
    assert date(2026, 11, 7) in days and date(2026, 11, 8) in days


def _snap(day, rows):
    return {"schema": "lantern-works-gpu-snapshot/1", "date": day, "rows": rows}


def _row(vendor, gpu, price, *, status="ranked", tier="On-demand", gpu_count=1):
    return {
        "key": f"{vendor}|{gpu}|{tier}|80|{gpu_count}",
        "vendor": vendor, "gpu": gpu, "tier": tier, "vram_gb": 80,
        "gpu_count": gpu_count, "billing_unit": "hourly",
        "price_usd": price, "hourly_usd": price, "status": status,
        "source_url": "https://example.com/pricing",
    }


def test_undercuts_count_and_disclose_missing_days():
    # Window 10-29..11-11. Snapshots on 11-06, 11-09, 11-10, 11-11 only.
    snaps = [
        _snap("2026-11-06", [_row("A", "H100", 1.00), _row("B", "H100", 2.00)]),
        _snap("2026-11-09", [_row("A", "H100", 2.00), _row("B", "H100", 2.00)]),
        _snap("2026-11-10", [_row("A", "H100", 1.50)]),
        _snap("2026-11-11", [_row("A", "H100", 1.00), _row("B", "H100", 1.50),
                             _row("C", "H100", 0.90)]),
    ]
    result = vsr.build_undercuts(snaps, date(2026, 11, 11), "B")
    assert result["window_start"] == "2026-10-29" and result["window_end"] == "2026-11-11"
    assert "2026-11-07" in result["snapshot_days_missing"]
    assert "2026-11-08" in result["snapshot_days_missing"]
    assert "2026-11-06" in result["snapshot_days_present"]
    assert result["history_incomplete"] is True
    # B comparable on 11-06 (undercut by A), 11-09 (not), 11-11 (undercut by A and C). Not on 11-10.
    assert result["days_with_comparable_rate"] == 3
    assert result["undercut_count"] == 2
    by = {x["vendor"]: x for x in result["undercut_by"]}
    assert by["A"]["times"] == 2 and by["C"]["times"] == 1
    dates = {o["date"] for o in result["undercut_observations"]}
    assert dates == {"2026-11-06", "2026-11-11"}
    assert "2026-11-07" not in dates and "2026-11-08" not in dates


def test_undercuts_ignore_held_spot_and_multi_gpu():
    snaps = [
        _snap("2026-11-11", [
            _row("B", "H100", 2.00),
            _row("A", "H100", 0.50, status="held"),
            _row("S", "H100", 0.40, tier="Spot (interruptible)"),
            _row("M", "H100", 0.10, gpu_count=8),
        ]),
    ]
    result = vsr.build_undercuts(snaps, date(2026, 11, 11), "B")
    assert result["undercut_count"] == 0
    assert result["days_with_comparable_rate"] == 1


def test_competition_ranks_ties():
    ranks = vsr.competition_ranks([("Civo", 1.50), ("RunPod", 1.50), ("Verda", 2.00)])
    assert ranks["Civo"][0] == 1 and ranks["RunPod"][0] == 1 and ranks["Civo"][2] is True
    assert ranks["Verda"] == (3, 3, False)


def _price_row(vendor, gpu, price, **kw):
    return {
        "advertiser": vendor, "gpu": gpu, "canonical_model": kw.get("canonical_model", gpu),
        "vram_gb": 80, "price_usd": price, "hourly_equiv_usd": price,
        "gpu_count": kw.get("gpu_count", 1), "min_gpus": kw.get("min_gpus", 1),
        "price_status": "listed", "unit": "hour", "tier": kw.get("tier", "On-demand"),
        "tier_class": kw.get("tier_class", "on-demand"), "interruptible": kw.get("interruptible", False),
        "form_factor": kw.get("form_factor", "not stated"),
        "billing": "per hour while running", "billing_unit": "hourly",
        "source_url": kw.get("source_url", "https://example.com/pricing"),
        "verified_at": "2026-11-11T02:14:49+00:00",
        "evidence": {
            "source_url": "https://example.com/pricing",
            "quote": kw.get("quote", f"{gpu} {price}/hr"),
            "checked_at": "2026-11-11T02:14:49+00:00",
        },
    }


def test_build_ranks_comparable_and_ineligible():
    prices = {
        "vendors": [{"vendor": "Civo"}, {"vendor": "RunPod"}, {"vendor": "Modal"}],
        "rates": [
            _price_row("Civo", "H100", 1.80),
            _price_row("RunPod", "H100", 2.40),
            _price_row(
                "Modal", "H100", 0.50,
                tier="Serverless, preemptible (per second)",
                tier_class="interruptible", interruptible=True,
                quote="serverless 0.50",
            ),
        ],
        "held_stale": [],
        "feed_updated_at": "2026-11-11T02:14:49Z",
    }
    ranks = vsr.build_ranks(prices)
    civo = {r["gpu"]: r for r in ranks["Civo"]}["H100"]
    runpod = {r["gpu"]: r for r in ranks["RunPod"]}["H100"]
    modal = {r["gpu"]: r for r in ranks["Modal"]}["H100"]
    assert civo["comparable"] and civo["rank"] == 1 and civo["field"] == 2
    assert runpod["rank"] == 2 and runpod["cheapest_vendor"] == "Civo"
    assert modal["comparable"] is False and "interruptible" in (modal["reason"] or "")
    assert civo["rate_id"] and civo["rate_id"].startswith("r_")


class _Gen:
    BASE = "https://thelanternworks.com"

    @staticmethod
    def esc(s):
        return escape(str(s or ""), quote=True)

    def page_shell(self, title, description, canonical, body, robots="index,follow"):
        return (
            "<!DOCTYPE html><html><head><!-- brand -->"
            f"<title>{escape(title)}</title>"
            f'<link rel="canonical" href="{escape(canonical)}" />'
            f'<meta name="description" content="{escape(description)}" />'
            "</head><body>" + body + "</body></html>"
        )


def _mini_root(tmp_path, prices, snaps, history=None, verify=None):
    (tmp_path / "api" / "v1" / "gpu-prices").mkdir(parents=True)
    (tmp_path / "data" / "gpu_pricing" / "snapshots").mkdir(parents=True)
    (tmp_path / "data" / "reports").mkdir(parents=True)
    (tmp_path / "api" / "v1" / "gpu-prices.json").write_text(json.dumps(prices) + "\n")
    if history is None:
        history = {
            "schema": "lantern-works-gpu-price-history/2",
            "last_snapshot": "2026-11-11",
            "snapshot_ids": [],
            "series": [],
            "changes": [],
        }
    (tmp_path / "api" / "v1" / "gpu-prices" / "history.json").write_text(json.dumps(history) + "\n")
    (tmp_path / "api" / "v1" / "gpu-price-changes.json").write_text(
        json.dumps({"schema": "x", "date": "2026-11-11", "changes": []}) + "\n"
    )
    for snap in snaps:
        (tmp_path / "data" / "gpu_pricing" / "snapshots" / f"{snap['date']}.json").write_text(
            json.dumps(snap) + "\n"
        )
    if verify is not None:
        (tmp_path / "data" / "reports" / "vendor-verification.json").write_text(json.dumps(verify) + "\n")
    return tmp_path


def test_pages_disclose_gap_and_ban_personal_names(tmp_path):
    prices = {
        "schema": "lantern-works-gpu-prices/1",
        "feed_updated_at": "2026-11-11T02:14:49Z",
        "prices_verified_through": "2026-11-11T02:14:49Z",
        "vendors": [
            {"vendor": "Civo", "source_url": "https://www.civo.com/pricing"},
            {"vendor": "RunPod", "source_url": "https://www.runpod.io/pricing"},
        ],
        "rates": [_price_row("Civo", "H100", 1.80), _price_row("RunPod", "H100", 2.40)],
        "held_stale": [],
        "license": {"data": "CC-BY-4.0"},
    }
    snaps = [
        _snap("2026-11-06", [_row("Civo", "H100", 1.80), _row("RunPod", "H100", 2.40)]),
        _snap("2026-11-11", [_row("Civo", "H100", 1.80), _row("RunPod", "H100", 2.40)]),
    ]
    root = _mini_root(tmp_path, prices, snaps)
    bundle = vsr.build_all(root)
    paths = vsr.write_pages(_Gen(), bundle, root)
    assert "reports/vendors" in paths and "reports/vendors/civo" in paths
    page = (root / "reports" / "vendors" / "runpod" / "index.html").read_text()
    assert "Lantern Works" in page and "CC BY 4.0" in page
    assert "feed_updated_at=" in page
    assert "rate_id=" in page
    assert "History is incomplete" in page
    assert "2026-11-07" in page and "2026-11-08" in page
    assert "No daily snapshot was published" in page
    assert "do not assume prices held steady" in page
    assert "2 undercut observation" in page
    assert "Civo" in page
    assert "creativecommons.org/licenses/by/4.0/" in page
    assert "Connor" not in page and "Frosty" not in page and "Douglas" not in page
    assert "connormatthew" not in page.lower()
    assert "/workspace/" not in page and "github.com" not in page
    chart = (root / "reports" / "vendors" / "runpod" / "rank-chart.svg").read_text()
    assert "<svg" in chart and "Civo" in chart and "Frosty" not in chart
    index = (root / "reports" / "vendors" / "index.html").read_text()
    assert "/reports/vendors/civo/" in index and "incomplete" in index


def test_held_vendor_is_not_given_a_live_rank(tmp_path):
    prices = {
        "feed_updated_at": "2026-11-11T02:14:49Z",
        "prices_verified_through": "2026-11-11T02:14:49Z",
        "vendors": [{"vendor": "Lambda", "source_url": "https://lambda.ai/service/gpu-cloud"}],
        "rates": [],
        "held_stale": [{
            "vendor": "Lambda",
            "reason": "Owner hold until 2026-11-16",
            "source_url": "https://lambda.ai/service/gpu-cloud",
            "records": [{"gpu": "H100", "hourly_usd": 2.99, "tier": "On-demand", "quote": "H100 $2.99"}],
        }],
    }
    root = _mini_root(tmp_path, prices, [_snap("2026-11-11", [])])
    bundle = vsr.build_all(root)
    vsr.write_pages(_Gen(), bundle, root)
    page = (root / "reports" / "vendors" / "lambda" / "index.html").read_text()
    assert "Currently unranked" in page
    assert "Owner hold until 2026-11-16" in page
    assert "H100" in page and "$2.99" in page
    assert "1 of " not in page


def test_robots_allow_and_disallow():
    robots = "User-agent: *\nDisallow: /api/\nAllow: /pricing\n"
    ok, _ = vsr._robots_allowed(robots, "/pricing")
    blocked, why = vsr._robots_allowed(robots, "/api/secret")
    assert ok is True
    assert blocked is False and "disallows" in why
    all_blocked, _ = vsr._robots_allowed("User-agent: *\nDisallow: /\n", "/pricing")
    assert all_blocked is False
    open_ok, _ = vsr._robots_allowed("User-agent: *\nDisallow:\n", "/pricing")
    assert open_ok is True


def test_body_has_price_formats():
    assert vsr._body_has_price("On-demand H100 $1.80 per hour", 1.80)
    assert vsr._body_has_price('{"price": "1.0060000000"}', 1.006)
    assert not vsr._body_has_price("no figures here", 2.99)
