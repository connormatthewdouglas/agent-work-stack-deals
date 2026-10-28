# Roadmap log

Ships with commits, CI runs, URLs and versions (newest first).

## 2026-10-28 — 0.3.6: optimize_agent_stack + /stack/

- b07eb72: MCP tool `optimize_agent_stack` (deterministic keyword/regex parse, no LLM; cheapest cited option per component from gpu-prices, stack-pricing and priced deals; "no sourced price tracked" where there is no data; pulled / do_not_relist listings excluded; manual-only signups flagged; referral disclosure per option). New core/agent_stack.py, core/compliance.py (pulled-ID hashes shared with the generator), /stack/ page (nav + sitemap), tests/test_agent_stack.py, tests/test_stack_page.py (JS parse matches Python).
- Version 0.3.6: https://pypi.org/project/lantern-works-deals-mcp/0.3.6/ and MCP Registry io.github.connormatthewdouglas/lantern-works-deals 0.3.6.
- Clean-env check: `scripts/test_pypi_install.py --version 0.3.6 --uvx` → RESULT ok, 6 tools listed (compare_deals, compare_gpu_prices, get_deal, optimize_agent_stack, optimize_stack, search_deals).
- CI for b07eb72 (run 40743990395): docker and pypi-install failed only because they ran before PyPI served 0.3.6; follow-up 9b8fb39 run 40744636561 all green (tests, validate, docker, pypi-install, deploy, live-checks).
- Page: https://thelanternworks.com/stack/
