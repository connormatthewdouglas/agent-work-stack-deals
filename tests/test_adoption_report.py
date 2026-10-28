import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("ar", pathlib.Path(__file__).parents[1] / "scripts" / "adoption_report.py")
ar = importlib.util.module_from_spec(spec); spec.loader.exec_module(ar)

OVERALL = {"data": [{"category": "with_mirrors", "date": "2026-10-27", "downloads": 2144},
                    {"category": "without_mirrors", "date": "2026-10-27", "downloads": 847}]}
SYSTEM = {"data": [{"category": "Linux", "date": "2026-10-27", "downloads": 319},
                   {"category": "Darwin", "date": "2026-10-27", "downloads": 8},
                   {"category": "null", "date": "2026-10-27", "downloads": 520}]}

def test_pypi_daily_subtracts_no_os_and_own_ci():
    r = ar.pypi_daily(OVERALL, SYSTEM, {"2026-10-27": 174})
    d = r["days"][0]
    assert (d["with_os_user_agent"], d["no_os_user_agent"], d["est_external_installs"]) == (327, 520, 153)
    assert r["est_external_installs_total"] == 153 and r["complete"]

def test_pypi_daily_unknown_ci_gives_none_and_floor_zero():
    assert ar.pypi_daily(OVERALL, SYSTEM, None)["est_external_installs_total"] is None
    assert ar.pypi_daily(OVERALL, SYSTEM, {"2026-10-27": 9999})["days"][0]["est_external_installs"] == 0

def test_ci_downloads_counts_only_jobs_that_ran():
    jobs = [[{"name": "pypi-install", "conclusion": "success", "started_at": "2026-10-27T01:00:00Z"},
             {"name": "docker", "conclusion": "failure", "started_at": "2026-10-27T01:00:00Z"},
             {"name": "deploy", "conclusion": "success", "started_at": "2026-10-27T01:00:00Z"}],
            [{"name": "pypi-install", "conclusion": "skipped", "started_at": "2026-10-27T02:00:00Z"},
             {"name": "docker", "conclusion": "success", "started_at": "2026-10-28T02:00:00Z"}]]
    assert ar.ci_downloads_by_day(jobs) == {"2026-10-27": 3, "2026-10-28": 1}

def test_telemetry_excludes_test_rows_and_reports_unmeasurable():
    t = ar.telemetry_summary({"rows": [{"day": "2026-10-26", "tool": "compare_deals", "version": "0.0.0", "n": 2},
                                       {"day": "2026-10-28", "tool": "search_deals", "version": "0.3.6", "n": 4}]})
    assert t["calls"] == 4 and t["test_rows_excluded"] == 1 and t["by_tool"] == {"search_deals": 4}
    assert t["distinct_installs"] is None and t["repeat_operators"] is None and "install_id" in t["why_none"]

def test_repeat_operators_need_two_distinct_days():
    rows = [{"day": "2026-10-27", "tool": "x", "version": "0.3.6", "n": 1, "install_id": "a"},
            {"day": "2026-10-28", "tool": "x", "version": "0.3.6", "n": 1, "install_id": "a"},
            {"day": "2026-10-28", "tool": "y", "version": "0.3.6", "n": 3, "install_id": "b"},
            {"day": "2026-10-28", "tool": "x", "version": "0.0.0", "n": 1, "install_id": "ci"}]
    t = ar.telemetry_summary({"rows": rows})
    assert t["distinct_installs"] == 2 and t["repeat_operators"] == 1

def test_telemetry_error_and_beacon_without_creds(monkeypatch):
    assert ar.telemetry_summary({"error": "HTTP 500"})["available"] is False
    for k in ("CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_SITE_TAG"):
        monkeypatch.delenv(k, raising=False)
    assert ar.cloudflare_beacon()["available"] is False

def test_goals_and_no_commission_fields():
    g = ar.goals({"est_external_installs_total": 153}, {"repeat_operators": None})
    assert g["installs"]["value"] == 153 and g["repeat_operators"]["value"] is None
    src = (pathlib.Path(__file__).parents[1] / "scripts" / "adoption_report.py").read_text().lower()
    assert "commission" not in src and "payout" not in src
