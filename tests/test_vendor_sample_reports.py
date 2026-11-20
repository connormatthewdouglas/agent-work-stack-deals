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
    assert "Stale" in page


def test_held_only_vendor_gets_a_stale_labelled_page(tmp_path):
    """A vendor that is only in held_stale (not in vendors[]) still gets a report
    that serves the last cited prices with an honest stale/age label."""
    prices = {
        "feed_updated_at": "2026-11-18T00:00:00Z",
        "prices_verified_through": "2026-11-18T00:00:00Z",
        "vendors": [{"vendor": "RunPod", "source_url": "https://www.runpod.io/pricing"}],
        "rates": [],
        "held_stale": [{
            "vendor": "Beam",
            "reason": "Held: machine price is a 'from' rate.",
            "source_url": "https://www.beam.cloud/pricing",
            "records": [{
                "gpu": "RTX 4090",
                "hourly_usd": 0.44,
                "tier": "Machine (from)",
                "quote": "RTX 4090 from $0.44/hr",
                "source_url": "https://www.beam.cloud/pricing",
                "verified_at": "2026-10-29T23:14:39+00:00",
                "evidence": {
                    "source_url": "https://www.beam.cloud/pricing",
                    "quote": "RTX 4090 from $0.44/hr",
                    "checked_at": "2026-10-29T23:14:39+00:00",
                    "quote_id": "q_beam_fixture",
                },
            }],
        }],
        "unpriced": [{
            "deal_id": "deal-alphavps-001",
            "advertiser": "AlphaVPS",
            "reason": "no structured GPU pricing record",
            "source_url": "https://alphavps.com/",
        }],
    }
    root = _mini_root(tmp_path, prices, [_snap("2026-11-11", [])])
    bundle = vsr.build_all(root)
    names = [r["vendor"] for r in bundle["reports"]]
    assert "Beam" in names
    assert "AlphaVPS" not in names
    assert "GigaGPU" not in names
    vsr.write_pages(_Gen(), bundle, root)
    page = (root / "reports" / "vendors" / "beam" / "index.html").read_text()
    assert "Currently unranked (stale)" in page
    assert "Stale" in page
    assert "last verified 2026-10-29 23:14:39 UTC" in page
    assert "read 19d ago" in page  # 2026-10-29 to 2026-11-18
    assert "$0.44" in page
    assert "RTX 4090 from $0.44/hr" in page
    assert "https://www.beam.cloud/pricing" in page
    assert "quote_id=q_beam_fixture" in page
    assert "1 of " not in page
    assert not (root / "reports" / "vendors" / "alphavps" / "index.html").exists()
    index = (root / "reports" / "vendors" / "index.html").read_text()
    assert "Beam" in index and "held / unranked" in index
    assert "AlphaVPS" not in index



def test_mixed_vendor_held_record_is_served_with_age_label(tmp_path):
    """A vendor with a current ranked row and a 48h-held record must still serve the
    held price with an honest last-verified date and age. The vendor is not given the
    vendor-wide 'Currently unranked' banner."""
    prices = {
        "feed_updated_at": "2026-11-20T00:52:22Z",
        "prices_verified_through": "2026-11-20T00:51:54Z",
        "vendors": [{"vendor": "Spheron", "source_url": "https://www.spheron.network/pricing/"}],
        "rates": [{
            "advertiser": "Spheron", "gpu": "L40S", "vram_gb": 48, "price_usd": 0.96,
            "hourly_usd": 0.96, "hourly_equiv_usd": 0.96, "billing_unit": "hourly",
            "tier": "On-demand", "interruptible": False, "form_factor": "PCIe",
            "source_url": "https://www.spheron.network/pricing/",
            "verified_at": "2026-11-19T19:05:14+00:00",
            "checked_at": "2026-11-19T19:05:14+00:00",
            "evidence": {"source_url": "https://www.spheron.network/pricing/",
                         "quote": "L40S $0.96 /hr", "checked_at": "2026-11-19T19:05:14+00:00"},
        }],
        "held_stale": [{
            "vendor": "Spheron",
            "reason": "stale price (3 days old)",
            "scope": "record",
            "source_url": "https://www.spheron.network/gpu-rental/rtx-5090/",
            "checked_at": "2026-11-16T23:34:52+00:00",
            "records": [{
                "gpu": "RTX 5090",
                "hourly_usd": 0.78,
                "tier": "Marketplace/aggregator listing (on-demand)",
                "quote": "On Spheron the NVIDIA RTX 5090 is $0.78/hr per GPU, billed per minute",
                "source_url": "https://www.spheron.network/gpu-rental/rtx-5090/",
                "verified_at": "2026-11-16T23:34:52+00:00",
                "evidence": {
                    "source_url": "https://www.spheron.network/gpu-rental/rtx-5090/",
                    "quote": "On Spheron the NVIDIA RTX 5090 is $0.78/hr per GPU, billed per minute",
                    "checked_at": "2026-11-16T23:34:52+00:00",
                },
            }],
        }],
    }
    root = _mini_root(tmp_path, prices, [_snap("2026-11-20", [])])
    bundle = vsr.build_all(root)
    vsr.write_pages(_Gen(), bundle, root)
    page = (root / "reports" / "vendors" / "spheron" / "index.html").read_text()
    assert "Currently unranked (stale)" not in page
    assert "Unranked (stale)" in page
    assert "RTX 5090" in page and "$0.78" in page
    assert "last verified 2026-11-16 23:34:52 UTC" in page
    assert "L40S" in page and "$0.96" in page
    assert "On Spheron the NVIDIA RTX 5090 is $0.78/hr per GPU, billed per minute" in page
    assert "https://www.spheron.network/gpu-rental/rtx-5090/" in page
    # Held row is labelled stale; the current L40S row is not the vendor-wide banner.
    assert "Stale" in page


def test_is_age_hold_matches_only_the_three_allowed_kinds():
    assert vsr._is_age_hold({"reason": "stale price (3 days old)"})
    assert vsr._is_age_hold({"reason": "stale price (check time unknown)"})
    assert vsr._is_age_hold({
        "reason": "Price not re-verified on the vendor page since 2026-11-10 "
                  "(> 7 days); held out of rankings until re-verified.",
    })
    assert vsr._is_age_hold({"reason": "Manual snapshot not re-verified for > 7 days"})
    for reason in (
        "Rate withdrawn on https://www.cloudrift.ai/a100 (page: \"the A100 is priced upon request\"); "
        "held, not shown or ranked, until a price is published again.",
        "Changed per-GPU vendor quote cannot substantiate the whole-instance total "
        "under the current evidence contract; held until re-sourced with supported evidence.",
        "no available Lium node at 2026-11-19T22:38:47+00:00; price withheld until a node is listed again",
        "owner_hold",
        "not yet in effect: 2026-11-16T00:00:00+00:00",
        "Marketplace too thin to publish: 2 verified rentable on-demand offers",
    ):
        assert not vsr._is_age_hold({"reason": reason}), reason


def test_held_rows_for_returns_every_entry_for_the_vendor():
    """B2: Lambda 3, Lium 7, Ucartz 3, CloudRift 3 — all entries, not just the first."""
    held = []
    for vendor, n in (("Lambda", 3), ("Lium", 7), ("Ucartz", 3), ("CloudRift", 3)):
        for i in range(n):
            held.append({"vendor": vendor, "reason": f"{vendor} hold {i+1}",
                         "records": [{"gpu": f"GPU{i+1}", "hourly_usd": 1.0 + i}]})
    prices = {"held_stale": held}
    assert [len(vsr.held_rows_for(prices, v)) for v in ("Lambda", "Lium", "Ucartz", "CloudRift")] == [3, 7, 3, 3]
    assert vsr.held_rows_for(prices, "Lambda")[2]["reason"] == "Lambda hold 3"
    assert vsr.held_rows_for(prices, "Missing") == []


def _mix_rate(vendor, gpu, price, url):
    return {
        "advertiser": vendor, "gpu": gpu, "vram_gb": 80, "price_usd": price,
        "hourly_usd": price, "hourly_equiv_usd": price, "billing_unit": "hourly",
        "tier": "On-demand", "interruptible": False, "form_factor": "SXM",
        "source_url": url, "verified_at": "2026-11-19T19:00:00+00:00",
        "checked_at": "2026-11-19T19:00:00+00:00",
        "evidence": {"source_url": url, "quote": f"{gpu} ${price}/hr",
                     "checked_at": "2026-11-19T19:00:00+00:00"},
    }


def _mix_held(vendor, gpu, price, reason, quote, url):
    return {
        "vendor": vendor, "reason": reason, "scope": "record", "source_url": url,
        "checked_at": "2026-11-10T00:00:00+00:00",
        "records": [{
            "gpu": gpu, "hourly_usd": price, "tier": "On-demand", "quote": quote,
            "source_url": url, "verified_at": "2026-11-10T00:00:00+00:00",
            "evidence": {"source_url": url, "quote": quote,
                         "checked_at": "2026-11-10T00:00:00+00:00"},
        }],
    }


def test_unranked_stale_section_omits_withdrawn_evidence_and_withheld_holds(tmp_path):
    """CloudRift A100, Ucartz RTX 4090, Lambda B200 and Lium A100 must not render
    on the mixed-vendor Unranked (stale) section; Spheron RTX 5090 (48h demotion) must."""
    clock = "2026-11-20T00:52:22Z"
    held = [
        _mix_held("CloudRift", "A100 SXM", 1.05,
                  "Rate withdrawn on https://www.cloudrift.ai/a100 (page: \"the A100 is priced upon request\") "
                  "at 2026-11-16T23:32:36+00:00; held, not shown or ranked, until a price is published again.",
                  "Rent NVIDIA A100 80GB SXM4 GPUs from $1.05/hour.",
                  "https://www.cloudrift.ai/a100"),
        _mix_held("CloudRift", "A100 SXM", 0.89,
                  "3-month commitment A100 SXM rate dropped; held, not shown or ranked",
                  "A100 SXM4 3 mo $0.89", "https://www.cloudrift.ai/pricing"),
        _mix_held("CloudRift", "A100 SXM", 0.95,
                  "1-month commitment A100 SXM rate dropped; held, not shown or ranked",
                  "A100 SXM4 1 mo $0.95", "https://www.cloudrift.ai/pricing"),
        _mix_held("Ucartz", "RTX 4090", 1.0941,
                  "RTX 4090 plan withdrawn: no longer listed; held, not shown or ranked, until a price is published again.",
                  "RTX 4090 servers from $798.72", "https://www.ucartz.com/gpu-dedicated-servers"),
        _mix_held("Ucartz", "RTX A5000", 1.1226,
                  "RTX A5000 plan withdrawn; held, not shown or ranked, until a price is published again.",
                  "RTX A5000 servers from $819.52", "https://www.ucartz.com/gpu-dedicated-servers"),
        _mix_held("Ucartz", "A100", 2.1427,
                  "A100 plan withdrawn; held, not shown or ranked, until a price is published again.",
                  "2 x A100 80GB", "https://www.ucartz.com/gpu-dedicated-servers"),
        _mix_held("Lambda", "B200", 6.69,
                  "Changed per-GPU vendor quote cannot substantiate the whole-instance total "
                  "under the current evidence contract; held until re-sourced with supported evidence.",
                  "NVIDIA HGX B200 180 GB $6.69", "https://lambda.ai/pricing"),
        _mix_held("Lambda", "H100 SXM", 3.99,
                  "Changed per-GPU vendor quote cannot substantiate the whole-instance total "
                  "under the current evidence contract; held until re-sourced with supported evidence.",
                  "NVIDIA HGX H100 $3.99", "https://lambda.ai/pricing"),
        _mix_held("Lambda", "A100 SXM", 2.79,
                  "Changed per-GPU vendor quote cannot substantiate the whole-instance total "
                  "under the current evidence contract; held until re-sourced with supported evidence.",
                  "NVIDIA HGX A100 $2.79", "https://lambda.ai/pricing"),
        _mix_held("Lium", "A100 SXM", None,
                  "no available Lium node at 2026-11-19T22:38:47+00:00; price withheld until a node is listed again",
                  "Lium nodes API: lowest price_per_gpu_hour $0.999",
                  "https://lium.io/"),
    ]
    # 6 more Lium no-node entries to make the B2 count of 7
    for gpu in ("B300", "H100 PCIe", "H100 SXM", "H200", "H200 NVL", "L40"):
        held.append(_mix_held("Lium", gpu, None,
                              "no available Lium node at 2026-11-19T22:38:47+00:00; price withheld until a node is listed again",
                              f"Lium nodes API: {gpu} lowest price_per_gpu_hour $0.999",
                              "https://lium.io/"))
    held.append(_mix_held(
        "Spheron", "RTX 5090", 0.78, "stale price (3 days old)",
        "On Spheron the NVIDIA RTX 5090 is $0.78/hr per GPU, billed per minute",
        "https://www.spheron.network/gpu-rental/rtx-5090/",
    ))
    prices = {
        "feed_updated_at": clock, "prices_verified_through": clock,
        "vendors": [
            {"vendor": "CloudRift", "source_url": "https://www.cloudrift.ai/pricing"},
            {"vendor": "Ucartz", "source_url": "https://www.ucartz.com/gpu-dedicated-servers"},
            {"vendor": "Lambda", "source_url": "https://lambda.ai/pricing"},
            {"vendor": "Lium", "source_url": "https://lium.io/"},
            {"vendor": "Spheron", "source_url": "https://www.spheron.network/pricing/"},
        ],
        "rates": [
            _mix_rate("CloudRift", "RTX 5090", 0.50, "https://www.cloudrift.ai/pricing"),
            _mix_rate("Ucartz", "RTX 5090", 0.60, "https://www.ucartz.com/gpu-dedicated-servers"),
            _mix_rate("Lambda", "H100 PCIe", 2.49, "https://lambda.ai/pricing"),
            _mix_rate("Lium", "B200", 2.00, "https://lium.io/"),
            _mix_rate("Spheron", "L40S", 0.96, "https://www.spheron.network/pricing/"),
        ],
        "held_stale": held,
    }
    assert [len(vsr.held_rows_for(prices, v)) for v in ("Lambda", "Lium", "Ucartz", "CloudRift")] == [3, 7, 3, 3]
    root = _mini_root(tmp_path, prices, [_snap("2026-11-20", [])])
    bundle = vsr.build_all(root)
    vsr.write_pages(_Gen(), bundle, root)

    def page(slug):
        return (root / "reports" / "vendors" / slug / "index.html").read_text()

    # Age-hold subset of those four vendors is empty — no Unranked section, no withheld prices.
    for slug, forbidden in (
        ("cloudrift", ("Unranked (stale)", "$1.05", "$0.89", "$0.95", "priced upon request")),
        ("ucartz", ("Unranked (stale)", "$1.0941", "$1.1226", "$2.1427", "plan withdrawn")),
        ("lambda", ("Unranked (stale)", "$6.69", "$3.99", "$2.79", "supported evidence")),
        ("lium", ("Unranked (stale)", "$0.999", "price withheld", "no available Lium node")),
    ):
        html = page(slug)
        assert "Currently unranked (stale)" not in html
        for s in forbidden:
            assert s not in html, f"{slug} unexpectedly contains {s!r}"

    sph = page("spheron")
    assert "Currently unranked (stale)" not in sph
    assert "Unranked (stale)" in sph
    assert "RTX 5090" in sph and "$0.78" in sph
    assert "stale price (3 days old)" in sph
    assert ".)." not in sph
    assert "L40S" in sph and "$0.96" in sph


def test_unranked_stale_section_skips_a_leading_withdrawn_entry_and_shows_each_age_reason(tmp_path):
    """B2: held_rows_for used to return only the first entry, so a withdrawn plan
    ahead of age holds would render (and hide the rest). After the fix, only the
    age-hold subset is served, each with its own reason, and a reason that ends
    in a period is not wrapped as '.).'."""
    clock = "2026-11-20T00:52:22Z"
    auto = ("Price not re-verified on the vendor page since 2026-11-10 "
            "(> 7 days); held out of rankings until re-verified.")
    manual = "Manual snapshot not re-verified for > 7 days"
    withdrawn = ("Rate withdrawn on https://example.com/a100; "
                 "held, not shown or ranked, until a price is published again.")
    prices = {
        "feed_updated_at": clock, "prices_verified_through": clock,
        "vendors": [{"vendor": "Acme", "source_url": "https://example.com/pricing"}],
        "rates": [_mix_rate("Acme", "L40S", 0.96, "https://example.com/pricing")],
        "held_stale": [
            _mix_held("Acme", "A100", 1.05, withdrawn, "A100 from $1.05/hour.", "https://example.com/a100"),
            _mix_held("Acme", "RTX 5090", 0.78, "stale price (3 days old)",
                      "RTX 5090 $0.78/hr", "https://example.com/5090"),
            _mix_held("Acme", "H100", 2.10, auto, "H100 $2.10/hr", "https://example.com/h100"),
            _mix_held("Acme", "MI250", 1.50, manual, "MI250 $1.50/hr", "https://example.com/mi250"),
        ],
    }
    assert len(vsr.held_rows_for(prices, "Acme")) == 4
    root = _mini_root(tmp_path, prices, [_snap("2026-11-20", [])])
    vsr.write_pages(_Gen(), vsr.build_all(root), root)
    html = (root / "reports" / "vendors" / "acme" / "index.html").read_text()
    assert "Unranked (stale)" in html
    assert "Currently unranked (stale)" not in html
    assert "$1.05" not in html and "priced upon request" not in html
    assert "until a price is published again." not in html
    assert "RTX 5090" in html and "$0.78" in html and "stale price (3 days old)" in html
    # Reasons that contain ">" are HTML-escaped on the page; match the verbatim
    # clauses around it so we still check each row's own reason.
    assert "H100" in html and "$2.10" in html
    assert "Price not re-verified on the vendor page since 2026-11-10" in html
    assert "held out of rankings until re-verified." in html
    assert "MI250" in html and "$1.50" in html
    assert "Manual snapshot not re-verified for" in html
    assert ".)." not in html
    # Ranked L40S is still shown as a current rate.
    assert "L40S" in html and "$0.96" in html


def test_unpriced_advertiser_without_cited_prices_is_not_given_a_page(tmp_path):
    prices = {
        "feed_updated_at": "2026-11-18T00:00:00Z",
        "prices_verified_through": "2026-11-18T00:00:00Z",
        "vendors": [],
        "rates": [],
        "held_stale": [],
        "unpriced": [
            {"advertiser": "AlphaVPS", "reason": "no structured GPU pricing record",
             "source_url": "https://alphavps.com/"},
            {"advertiser": "GigaGPU", "reason": "no structured GPU pricing record",
             "source_url": None},
        ],
    }
    root = _mini_root(tmp_path, prices, [_snap("2026-11-11", [])])
    bundle = vsr.build_all(root)
    assert bundle["reports"] == []
    assert "AlphaVPS" not in vsr.tracked_vendors(prices)
    assert "GigaGPU" not in vsr.tracked_vendors(prices)


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
