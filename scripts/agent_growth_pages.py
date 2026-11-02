"""Small, durable entry points for the first useful call and third-party placements."""
from __future__ import annotations

import html

from integration_snippet import RAW, render


def write_all(g) -> list[str]:
    download = f"curl --fail --location {RAW} --output first_quote.py"
    first = download + "\npython3 first_quote.py --gpu 'H100 SXM' --hours 100 --ref quickstart"
    quick = f"""<nav class="crumbs"><a href="{g.BASE}/">Lantern Works</a> › First GPU quote</nav>
<h1>A cited GPU quote in one minute</h1>
<p>Compare GPU rentals before a training run or estimate a job's compute budget. Python 3.10+ is enough: no package installation, account or API key for these read-only queries.</p>
<h2>Download, inspect, run</h2>
<p><a href="{RAW}">Read the complete example</a>, then download it and run it locally:</p>
<pre style="overflow-x:auto"><code>{html.escape(first)}</code></pre>
<p>The example connects to the public hosted MCP, initializes the session, requests three on-demand <strong>H100 SXM</strong> rates checked within 24 hours, and estimates a 100-hour, one-GPU job. Output is JSON with vendor source links, check times, assumptions, missing costs and a quote receipt. No purchase or watch is created.</p>
<p>Change <code>--gpu 'A100 PCIe'</code>, <code>--hours 10</code> or <code>--gpus 4</code> for your workload. Omit <code>--hours</code> to compare hourly prices only. Use <code>--qa</code> for internal tests.</p>
<h2>Already using an MCP client?</h2>
<p>Connect with Streamable HTTP to:</p>
<pre style="overflow-x:auto"><code>https://lantern-works-mcp.lantern-works.workers.dev/mcp?ref=quickstart</code></pre>
<p>Ask for <code>compare_gpu_prices(gpu="H100 SXM", on_demand_only=true, limit=3, mode="brief")</code>. <a href="{g.BASE}/install/">Client-specific configuration</a> · <a href="{g.BASE}/agent.json">Agent discovery JSON</a></p>
<h2>Read the answer safely</h2>
<ul><li>Cheapest means among tracked providers. Match the GPU variant and tier; unknown stock is not a promise of capacity.</li>
<li>The job result is a compute subtotal. Review <code>assumptions</code> and <code>missing_costs</code> for storage, egress and taxes. Whole-instance billing may allocate more GPUs than requested.</li>
<li>Check <code>source_url</code> and <code>checked_at</code> before acting. An empty fresh result is not evidence that the model is unavailable everywhere.</li>
<li>Referral links are labeled and never change ranking. Confirm vendor terms before paying.</li></ul>
<h2>Only need JSON?</h2>
<p>Start with the <a href="{g.BASE}/api/v1/gpu/index.json">small per-model feed index</a>, or the <a href="{g.BASE}/api/v1/gpu-prices.json">complete GPU feed</a>. Enforce stock expiry when reading a static snapshot. See <a href="{g.BASE}/for-agents/">the agent data contract</a>.</p>
<p>Maintain a GPU tool, dataset or agent guide? <a href="{g.BASE}/integrate/">Add a short integration to your README</a>.</p>"""
    link = render("partner-readme")
    snippet = render("partner-readme", format="quickstart")
    integrate = f"""<nav class="crumbs"><a href="{g.BASE}/">Lantern Works</a> › Integrate</nav>
<h1>Add cited GPU prices to your agent or README</h1>
<p>Give builders a useful next step after discovering your GPU tool, dataset or agent guide: compare rental costs with source links, then estimate their job. Free read-only queries, no signup.</p>
<p>Start with one direct price link. Replace <code>partner-readme</code> with a short channel tag (lowercase letters, digits, underscores or hyphens; at most 32 characters). The tag records aggregate channel counts; it does not identify a user or prove an installation.</p>
<pre style="overflow-x:auto"><code>{html.escape(link)}</code></pre>
<details><summary>Optional runnable MCP integration (Markdown)</summary><pre style="overflow-x:auto"><code>{html.escape(snippet)}</code></pre></details>
<h2>Generate a placement-specific version</h2>
<p>In the <a href="https://github.com/connormatthewdouglas/agent-work-stack-deals">source repository</a>, run <code>python3 scripts/integration_snippet.py --ref your-project</code>. Add <code>--format quickstart</code> for the runnable example; use <code>--ref hf</code> or <code>--ref kaggle</code> for dataset cards.</p>
<p>Keep the source/freshness and missing-cost limits beside the example. Use the JSON model index when your application does not support MCP. Client configuration formats vary: link to <a href="{g.BASE}/install/">the client-specific install guide</a>.</p>
<p><a href="{g.BASE}/quickstart/">Try the first quote</a> · <a href="{g.BASE}/coverage/">Check model coverage</a> · <a href="{g.BASE}/methodology/">Price methodology</a></p>"""
    pages = [("quickstart", "GPU prices for AI agents: no-install MCP quickstart", "Get a cited GPU comparison and job-cost estimate with Python's standard library and the public Lantern Works MCP.", quick),
             ("integrate", "Add cited GPU prices to an agent, README or dataset", "Copy a short, channel-tagged GPU price integration with remote MCP configuration, a runnable example and source limits.", integrate)]
    for slug, title, desc, body in pages:
        path = g.ROOT / slug / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(g.page_shell(title, desc, f"{g.BASE}/{slug}/", body), encoding="utf-8")
    return [p[0] for p in pages]
