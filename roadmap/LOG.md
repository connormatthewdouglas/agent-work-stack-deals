# Roadmap log

Ships with commits, CI runs, URLs and versions (newest first).

## 2026-10-28 — 0.3.6: optimize_agent_stack + /stack/

- b07eb72: MCP tool `optimize_agent_stack` (deterministic keyword/regex parse, no LLM; cheapest cited option per component from gpu-prices, stack-pricing and priced deals; "no sourced price tracked" where there is no data; pulled / do_not_relist listings excluded; manual-only signups flagged; referral disclosure per option). New core/agent_stack.py, core/compliance.py (pulled-ID hashes shared with the generator), /stack/ page (nav + sitemap), tests/test_agent_stack.py, tests/test_stack_page.py (JS parse matches Python).
- Version 0.3.6: https://pypi.org/project/lantern-works-deals-mcp/0.3.6/ and MCP Registry io.github.connormatthewdouglas/lantern-works-deals 0.3.6.
- Clean-env check: `scripts/test_pypi_install.py --version 0.3.6 --uvx` → RESULT ok, 6 tools listed (compare_deals, compare_gpu_prices, get_deal, optimize_agent_stack, optimize_stack, search_deals).
- CI for b07eb72 (run 40743990395): docker and pypi-install failed only because they ran before PyPI served 0.3.6; follow-up 9b8fb39 run 40744636561 all green (tests, validate, docker, pypi-install, deploy, live-checks).
- Page: https://thelanternworks.com/stack/

## 2026-10-28 (Oct 28 evening): adoption measurement

`scripts/adoption_report.py` now reports installs, opt-in telemetry and repeat operators against the goal (50 installs, 10 repeat operators), with caveats. Tests: `tests/test_adoption_report.py`. No new tracking was added.

Numbers from a run at ~6:10 PM ET on Oct 28 (pypistats has data only for 2026-10-27 UTC so far):

- **PyPI, 2026-10-27:** 847 downloads without mirrors (2,144 with mirrors).
  - Minus 520 with no OS in the user agent (scanners and mirroring tools) and 174 from our own CI (pypi-install job = 2 per run, docker job = 1 per run, counted from Actions job history).
  - That leaves an estimated **153 external installs**. This is an upper bound: other people's CI, registry builds, repeat downloads and our manual test installs all still count.
- **Opt-in telemetry:** 0 real calls. The 2 test rows (version 0.0.0) are excluded.
- **Distinct opt-in installs and repeat operators:** not measurable. The collector stores no install ID (by design), and adding one would be new tracking that needs approval.
- **Cloudflare beacon:** not queried. This needs a read-only CF_API_TOKEN + CF_ACCOUNT_ID + CF_SITE_TAG; for now, use the dashboard.
- **Goal status:** installs ~153 / 50, but this is an unverified upper bound. Repeat operators: unknown / 10.
