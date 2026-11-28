#!/usr/bin/env python3
"""Generate Pulse SEO batch-1 pages from the live GPU price feed at build time.

Writes:
  /reports/cheapest-h100-week-of-2026-11-23/
  /reports/cheapest-l40s-week-of-2026-11-23/
  /reports/cheapest-a100-week-of-2026-11-23/
  /cost/fine-tune-7b-8b-lora/

Figures come from seo_batch1_compute.build_figures() (live api/v1 feeds), never from a
copied draft. Markdown is rendered through the site page shell.
"""

from __future__ import annotations

import re
from pathlib import Path

import reports_page
from seo_batch1_compute import ROOT, build_figures, fmt_usd, fmt_usd_mul

FORBIDDEN = re.compile(r"github\.com|connormatthewdouglas|/workspace/|/home/|Frosty Condor|Connor Douglas", re.I)

PAGE_SPECS = {
    "H100": {
        "path": "reports/cheapest-h100-week-of-2026-11-23",
        "kind": "family",
    },
    "L40S": {
        "path": "reports/cheapest-l40s-week-of-2026-11-23",
        "kind": "family",
    },
    "A100": {
        "path": "reports/cheapest-a100-week-of-2026-11-23",
        "kind": "family",
    },
    "cost": {
        "path": "cost/fine-tune-7b-8b-lora",
        "kind": "cost",
    },
}

def md_cell(value) -> str:
    if value is None:
        return "—"
    s = str(value).replace("|", "\\|")
    return s


def referral_cell(flag: bool) -> str:
    return "Yes" if flag else "No"


def source_link(url: str | None, referral: bool = False) -> str:
    # Always cite the vendor source_url. Referral status is a separate column.
    if not url:
        return "—"
    return f"[Vendor page]({url})"


def rate_table(rows: list[dict], include_min_gpus: bool = False) -> str:
    if not rows:
        return "_None in this snapshot._\n"
    cols = ["Vendor", "GPU / form", "VRAM", "Tier", "$/GPU-hr", "Price date (ET)", "Source", "Referral"]
    if include_min_gpus:
        cols = ["Vendor", "GPU / form", "VRAM", "Min GPUs", "Tier", "$/GPU-hr", "Price date (ET)", "Source", "Referral"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        form = r["form_factor"]
        gpu = r["gpu"] or ""
        gpu_form = gpu if form == "not stated" or form in gpu else f"{gpu} ({form})"
        vram = f"{r['vram_gb']} GB" if r.get("vram_gb") is not None else "—"
        cells = [
            md_cell(r["vendor"]),
            md_cell(gpu_form),
            md_cell(vram),
        ]
        if include_min_gpus:
            cells.append(md_cell(r["min_gpus"]))
        cells.extend(
            [
                md_cell(r["tier"]),
                md_cell(r["price"]),
                md_cell(r["verified_et"]),
                source_link(r["source_url"], r["referral"]),
                referral_cell(r["referral"]),
            ]
        )
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def changes_table(changes: list[dict]) -> str:
    if not changes:
        return "_No listed price-change events for this GPU family in the week-of-Nov-23 history window._\n"
    cols = ["Snapshot date", "Vendor", "GPU", "Tier", "From", "To", "Change", "Status", "Source"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for c in changes:
        pct = c.get("change_pct")
        if pct is None:
            change = "—"
        else:
            # Feed stores change_pct already rounded (e.g. 1.0, -5.8, 10.4).
            change = f"{pct:+g}%"
        flag = c.get("composition_flag")
        status = c.get("status") or "—"
        if flag:
            status = f"{status}; composition: {flag}"
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(c["date"]),
                    md_cell(c["vendor"]),
                    md_cell(c["gpu"]),
                    md_cell(c["tier"]),
                    md_cell(c["from_price"] or "—"),
                    md_cell(c["to_price"] or "—"),
                    md_cell(change),
                    md_cell(status),
                    source_link(c.get("source_url"), False),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def install_block(figs: dict, example_title: str, example_body: str) -> str:
    mcp = figs["mcp"]
    return f"""## Get these prices from the MCP server

Copy-paste install (no API key). More clients are on the [Install (MCP)]({mcp['install_docs']}) page. The hosted URL's `?ref=` tag only marks which snippet was used.

Hosted endpoint (Streamable HTTP):

```bash
{mcp['hosted_add']}
```

Local (stdio, via `uvx`):

```bash
{mcp['uvx_add']}
```

You can also run `{mcp['uvx_command']}` as the local command, or add the hosted URL `{mcp['hosted_url']}` in any MCP client.

{example_title}

{example_body}

JSON without an MCP client: [gpu-prices.json](https://thelanternworks.com/api/v1/gpu-prices.json), [history.json](https://thelanternworks.com/api/v1/gpu-prices/history.json), and the [API docs]({mcp['api_docs']}).
"""


def shared_scope(figs: dict) -> str:
    lic = figs["license"]
    return f"""## Scope, sources, and license

- Times labelled ET are America/New_York (UTC-5 on these dates).
- **"Cheapest" means cheapest among tracked providers**, not the whole market.
- **GPU-hour price only:** excludes storage, data egress, extra vCPU/RAM, and taxes. Confirm those on the vendor page before you spend.
- **On-demand and spot/community are listed separately** and are not mixed in the headline ranking. Reserved/commitment and serverless rows are listed only as notes, and are excluded from the cheapest on-demand and cheapest spot figures. Marketplace listings are also separated and labelled.
- **Single-GPU, per GPU-hour** unless a row is labelled with a multi-GPU minimum.
- Each row cites the vendor `source_url` and that row's own price date (`verified_at`). A price can change after it was checked.
- This page uses the live ranked feed at snapshot time. Held-stale records (prices not currently ranked) are omitted. A vendor may still appear here on other live SKUs.
- History for the week comes from the daily snapshots in [history.json](https://thelanternworks.com/api/v1/gpu-prices/history.json) ({figs['history_snapshot_count_this_week']} snapshots, {figs['week_start']} through {figs['week_end_snapshot']}). The calendar week of Nov 23 continues through {figs['week_end_calendar']}; this snapshot stops at the Nov 28 feed.
- Some links are referral links (marked in the tables). Lantern Works may earn a commission if you sign up through them. That never changes the price you pay, and affiliate status is not a ranking factor. See the [affiliate disclosure](https://thelanternworks.com/disclosure/).
- Data: [Lantern Works GPU price feed](https://thelanternworks.com/api/v1/gpu-prices.json) and [history](https://thelanternworks.com/api/v1/gpu-prices/history.json), licensed [CC BY 4.0]({lic['data_license_url']}). Attribution: {lic['attribution']}. Methodology: [license notes]({lic['details']}).
- Found a wrong price? [Report it](https://thelanternworks.com/report-price/).
"""


def complement_blurb(fam: str, figs: dict) -> str:
    live = figs["live_pages"][fam]
    return (
        f"This is a **dated weekly snapshot**, not the live comparison. "
        f"For the current list, with form-factor groups and availability notes, see "
        f"[Cheapest {fam} rental today among tracked providers]({live})."
    )


def cheapest_page(fam: str, figs: dict) -> str:
    data = figs["families"][fam]
    od = data["cheapest_on_demand_single"]
    spot = data["cheapest_spot_single"]
    slug = figs["slugs"][fam]
    live = figs["live_pages"][fam]
    week = figs["week_label"]
    title = f"Cheapest {fam} rental this week ({week})"
    if fam == "H100":
        meta = (
            f"Cheapest H100 rental this week among tracked providers: {od['vendor']} {od['gpu']} at "
            f"{od['price']}/GPU-hr, verified {od['verified_et']}. Week-of-Nov-23 snapshot."
        )
        extra_lead = (
            f"The cheapest H100 SXM on-demand rate in the same snapshot is "
            f"{data['extras']['cheapest_on_demand_sxm']['vendor']} "
            f"{data['extras']['cheapest_on_demand_sxm']['gpu']} at "
            f"{data['extras']['cheapest_on_demand_sxm']['price']}/GPU-hr, "
            f"verified {data['extras']['cheapest_on_demand_sxm']['verified_et']}. "
            f"H100 NVL (94 GB) is listed separately below and is not the same product as the 80 GB H100."
        )
        example = (
            "### Example call: cheapest tracked H100 on-demand rates",
            "After install, call `compare_gpu_prices` with `{ \"gpu\": \"H100\", \"on_demand_only\": true }`. "
            "To include labelled spot and community rows, pass `on_demand_only` as `false`. "
            "You can also ask: *What's the cheapest H100 to rent among tracked providers? Show sources.*",
        )
    elif fam == "L40S":
        meta = (
            f"Cheapest L40S rental this week among tracked providers: {od['vendor']} at "
            f"{od['price']}/GPU-hr, verified {od['verified_et']}. Week-of-Nov-23 snapshot; fewer listed rates than H100."
        )
        n_od = len(data["by_bucket"]["on-demand"]["single"])
        extra_lead = (
            f"L40S coverage among tracked providers is thinner than H100 or A100: this snapshot has "
            f"{n_od} single-GPU on-demand rates (48 GB, form factor not stated on the vendor pages). "
            f"A two-GPU Lium marketplace listing is cheaper per GPU-hour but is not a single-GPU rate, "
            f"and is in the marketplace table."
        )
        example = (
            "### Example call: cheapest tracked L40S on-demand rates",
            "After install, call `compare_gpu_prices` with `{ \"gpu\": \"L40S\", \"on_demand_only\": true }`. "
            "To include labelled spot and community rows, pass `on_demand_only` as `false`.",
        )
    else:
        od80 = data["extras"]["cheapest_on_demand_80gb"]
        meta = (
            f"Cheapest A100 rental this week among tracked providers: {od['vendor']} 40GB at "
            f"{od['price']}/GPU-hr, verified {od['verified_et']}. Cheapest 80GB on-demand: {od80['vendor']} at {od80['price']}/hr."
        )
        extra_lead = (
            f"That headline rate is a **40 GB** A100. The cheapest **80 GB** on-demand single-GPU rate "
            f"in this snapshot is {od80['vendor']} at {od80['price']}/GPU-hr "
            f"({od80['gpu']}, form {od80['form_factor']}, verified {od80['verified_et']}"
            f"{'; this row is a referral offer' if od80['referral'] else ''}). "
            f"40 GB and 80 GB A100s are different products; compare them separately."
        )
        example = (
            "### Example call: cheapest tracked A100 on-demand rates",
            "After install, call `compare_gpu_prices` with `{ \"gpu\": \"A100\", \"on_demand_only\": true }`. "
            "To include labelled spot and community rows, pass `on_demand_only` as `false`.",
        )

    hundred = fmt_usd_mul(od["price_usd"], 100)
    spot_line = ""
    if spot:
        pre = " May be preempted." if spot["interruptible"] else ""
        comm = " Community Cloud is grouped with spot, not with on-demand, on this page." if "community" in (spot["tier"] or "").lower() else ""
        ref = " This row is a referral offer." if spot["referral"] else ""
        spot_line = (
            f"**Cheapest spot/community (single-GPU) among tracked providers:** "
            f"{spot['price']}/GPU-hr · {spot['vendor']} · {spot['gpu']} · {spot['tier']}, "
            f"verified {spot['verified_et']}.{pre}{comm}{ref} "
            f"Source: {source_link(spot['source_url'], spot['referral'])}."
        )

    # Stability sentence from daily cheapest
    daily = data["daily_cheapest_on_demand"]
    vendors_prices = {(d["cheapest"]["vendor"], d["cheapest"]["price"]) for d in daily if d["cheapest"]}
    if len(vendors_prices) == 1:
        v, p = next(iter(vendors_prices))
        stable = (
            f"In all {len(daily)} daily snapshots from {figs['week_start']} through "
            f"{figs['week_end_snapshot']}, the cheapest single-GPU on-demand {fam} rate among tracked "
            f"providers was {v} at {p}/GPU-hr. That list price did not move during this window; "
            f"the price date below is when this snapshot last confirmed it on the vendor page."
        )
    else:
        stable = "The cheapest single-GPU on-demand rate among tracked providers on each daily snapshot is listed under the week view."

    reserved = data["by_bucket"]["reserved"]["all"]
    serverless = data["by_bucket"]["serverless"]["all"]
    marketplace_single = data["by_bucket"]["marketplace"]["single"]
    marketplace_multi = data["by_bucket"]["marketplace"]["multi"]
    od_multi = data["by_bucket"]["on-demand"]["multi"]
    spot_multi = data["by_bucket"]["spot"]["multi"]

    reserved_note = ""
    if reserved:
        cheapest_res = min(reserved, key=lambda r: r["price_usd"])
        reserved_note = (
            f"Reserved or commitment rates are excluded from the cheapest on-demand ranking. "
            f"The lowest reserved row in this snapshot is {cheapest_res['vendor']} {cheapest_res['gpu']} "
            f"at {cheapest_res['price']}/GPU-hr ({cheapest_res['tier']}, verified {cheapest_res['verified_et']})."
        )
    serverless_note = ""
    if serverless:
        bits = ", ".join(
            f"{r['vendor']} at {r['price']}/GPU-hr ({r['tier']}, verified {r['verified_et']})"
            for r in serverless
        )
        serverless_note = f"Serverless rows (also excluded from the on-demand ranking): {bits}."

    parts = [
        "---",
        f"title: \"{title}\"",
        f"meta_description: \"{meta}\"",
        f"slug: {slug}",
        f"h1: \"{title}\"",
        f"live_complement: {live}",
        f"feed_updated_at: {figs['feed_updated_at']}",
        "---",
        "",
        f"# {title}",
        "",
        complement_blurb(fam, figs),
        "",
        (
            f"Snapshot from the Lantern Works GPU price feed, last updated "
            f"**{figs['feed_updated_at_et']}**. Prices in this feed were verified through "
            f"{figs['prices_verified_through_et']}. This window is the {week} "
            f"(Monday {figs['week_start']} through the {figs['week_end_snapshot']} snapshot; "
            f"the calendar week runs through Sunday {figs['week_end_calendar']}). "
            f"Among tracked providers only, this snapshot has **{data['rate_count']} ranked {fam} rates** "
            f"from **{data['vendor_count']} vendors**."
        ),
        "",
        (
            f"**Cheapest on-demand (single-GPU) among tracked providers:** "
            f"**{od['price']}/GPU-hr** · {od['vendor']} · {od['gpu']}"
            f"{'' if od['form_factor']=='not stated' or od['form_factor'] in (od['gpu'] or '') else ' ('+od['form_factor']+')'}"
            f" · {od['vram_gb']} GB · {od['tier']}, verified **{od['verified_et']}**. "
            f"A 100 GPU-hour compute subtotal at this rate is {hundred} "
            f"(GPU-hour price only). Source: {source_link(od['source_url'], od['referral'])}."
        ),
        "",
        extra_lead,
        "",
        spot_line,
        "",
        stable,
        "",
        "## On-demand (single-GPU)",
        "",
        rate_table(data["by_bucket"]["on-demand"]["single"]),
    ]
    if od_multi:
        parts += [
            "",
            "### On-demand with a multi-GPU minimum",
            "",
            "These are priced per GPU-hour but require more than one GPU. They are not in the single-GPU cheapest ranking.",
            "",
            rate_table(od_multi, include_min_gpus=True),
        ]
    parts += [
        "",
        "## Spot and community (single-GPU)",
        "",
        "Interruptible spot rates and RunPod Community Cloud are grouped here, not with on-demand. Community Cloud is not marked interruptible in the feed, but it is a community tier and is ranked with spot on the live {fam} page as well.".format(fam=fam)
        if fam
        else "",
        "",
        rate_table(data["by_bucket"]["spot"]["single"]),
    ]
    if spot_multi:
        parts += [
            "",
            "### Spot/community with a multi-GPU minimum",
            "",
            rate_table(spot_multi, include_min_gpus=True),
        ]
    if marketplace_single or marketplace_multi:
        parts += [
            "",
            "## Marketplace listings",
            "",
            "These are marketplace or aggregator listings, not a single cloud provider's published on-demand SKU. Some are medians across hosts, and available nodes can disappear between checks. They are excluded from the cheapest on-demand headline.",
            "",
        ]
        if marketplace_single:
            parts += [rate_table(marketplace_single)]
        if marketplace_multi:
            parts += [
                "### Marketplace listings with a multi-GPU minimum",
                "",
                rate_table(marketplace_multi, include_min_gpus=True),
            ]
    if reserved or serverless:
        parts += ["", "## Reserved and serverless (excluded from the cheapest ranking)", ""]
        if reserved_note:
            parts += [reserved_note, ""]
        if reserved:
            parts += [rate_table(reserved), ""]
        if serverless_note:
            parts += [serverless_note, ""]
        if serverless:
            parts += [rate_table(serverless), ""]

    parts += [
        "",
        "## What moved during the week",
        "",
        (
            f"Price-change events from the history feed with snapshot dates {figs['week_start']} through "
            f"{figs['week_end_snapshot']}. `change_pct` is the feed's own figure. "
            "A 'held' or 'removed' status means the rate was not ranked that day (for example, briefly stale, or a marketplace node that was not listed)."
        ),
        "",
        changes_table(data["changes"]),
        "",
        shared_scope(figs),
        "",
        install_block(figs, example[0], example[1]),
        "",
    ]
    # filter accidental empty issues
    text = "\n".join(parts)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def cost_page(figs: dict) -> str:
    calc = figs["calculator"]
    slug = figs["slugs"]["cost"]
    title = "Cost to fine-tune a 7B or 8B model (LoRA, e.g. Llama 3.1 8B)"
    meta = (
        "Estimate the GPU-hour cost to LoRA fine-tune a 7B or 8B model such as Llama 3.1 8B. "
        "Worked examples at 2, 4, 8 and 24 hours use this week's tracked on-demand rates."
    )
    # table
    headers = ["Job hours (assumed)"] + [c["label"] + f" ({c['rate']}/hr)" for c in calc["columns"]]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for h in calc["hours"]:
        row = [f"{h} hours"]
        for c in calc["columns"]:
            row.append(calc["cells"][c["key"]][str(h)]["display"])
        lines.append("| " + " | ".join(row) + " |")
    table = "\n".join(lines)

    rate_bits = []
    for c in calc["columns"]:
        ref = " This row is a referral offer." if c["referral"] else ""
        rate_bits.append(
            f"- **{c['label']}:** {c['rate']}/GPU-hr, verified {c['verified_et']}. "
            f"Source: {source_link(c['source_url'], c['referral'])}.{ref}"
        )

    h100 = figs["families"]["H100"]["cheapest_on_demand_single"]
    l40 = figs["families"]["L40S"]["cheapest_on_demand_single"]
    a40 = figs["families"]["A100"]["extras"]["cheapest_on_demand_40gb"]
    a80 = figs["families"]["A100"]["extras"]["cheapest_on_demand_80gb"]

    example_body = (
        "After install, call `estimate_job_cost` with "
        '`{ "gpu_family": "H100", "gpus_per_job": 1, "job_hours": 8, "allow_interruptible": false }`. '
        "The tool returns a compute subtotal among tracked providers, with assumptions, missing costs "
        "(storage, egress, and similar), sources, and a re-openable quote. "
        "This page's 8-hour H100 PCIe example uses the same hour count and the Hyperstack on-demand rate "
        f"from the snapshot, which is {calc['cells']['h100_pcie_hyperstack']['8']['display']}. "
        "For an L40S quote, pass `gpu_family` as `L40S` instead. "
        "`job_hours` is wall-clock duration per job, not a total of GPU-hours across many GPUs; "
        "eight hours on one GPU is `job_hours: 8` and `gpus_per_job: 1`."
    )

    text = f"""---
title: "{title}"
meta_description: "{meta}"
slug: {slug}
h1: "{title}"
feed_updated_at: {figs['feed_updated_at']}
---

# {title}

This is a **job-cost calculator**, not a claim that a named fine-tune takes a fixed number of hours. It complements the fixed-hour tables on [GPU rental cost by hours]({figs['live_pages']['cost_index']}) (10, 100, or 730 GPU-hours) and the [GPU cost calculator]({figs['live_pages']['calculator']}). Rates below are the cheapest single-GPU on-demand figures among tracked providers in the week-of-Nov-23 snapshot (feed last updated **{figs['feed_updated_at_et']}**).

**Formula (GPU-hour compute subtotal only):** `cost = job_hours × GPUs × hourly rate`. Every worked example here uses **1 GPU** and the stated hour count.

## Assumptions (read these first)

- **Hours are examples, not a measured Llama 3.1 8B run.** Time to LoRA fine-tune a 7B or 8B model depends on dataset size, sequence length, epochs, batch size, LoRA rank, precision, and the framework. This page does not have a sourced hour count for a specific official recipe, so it does not invent one. Plug in your own hour count, or use the worked rows at 2, 4, 8, and 24 hours.
- **One GPU, on-demand, continuous.** Examples ignore spot preemption, queue time, and multi-GPU setups. If you use two GPUs for eight wall-clock hours, the compute subtotal is `8 × 2 × rate`.
- **GPU-hour price only.** Storage, dataset egress, checkpoints, extra vCPU/RAM, and taxes are not included. The MCP tool flags those as missing costs.
- **"Cheapest" means cheapest among tracked providers**, not the whole market. The 80 GB A100 column uses a referral rate (marked below). The 40 GB and 80 GB A100 columns are different products.
- Rates are from the snapshot dated {figs['feed_updated_at_et']}. Each rate's own price date is listed with its source. Confirm the vendor page before you spend.

## Worked examples

{table}

## Rates used in the table

{chr(10).join(rate_bits)}

Headline rates in this snapshot, for context: cheapest L40S on-demand {l40['price']}/GPU-hr ({l40['vendor']}, verified {l40['verified_et']}); cheapest A100 on-demand {a40['price']}/GPU-hr ({a40['vendor']}, 40 GB, verified {a40['verified_et']}); cheapest A100 80 GB on-demand {a80['price']}/GPU-hr ({a80['vendor']}, verified {a80['verified_et']}); cheapest H100 on-demand {h100['price']}/GPU-hr ({h100['vendor']} {h100['gpu']}, verified {h100['verified_et']}). Weekly rate tables: [H100]({figs['slugs']['H100']}), [L40S]({figs['slugs']['L40S']}), [A100]({figs['slugs']['A100']}). Live lists: [H100 today]({figs['live_pages']['H100']}), [L40S today]({figs['live_pages']['L40S']}), [A100 today]({figs['live_pages']['A100']}).

{shared_scope(figs)}

{install_block(figs, "### Example call: estimate an 8-hour H100 job", example_body)}
"""
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def front_matter(md: str):
    return reports_page.front_matter(md)


def _strip_leading_h1(md: str) -> str:
    lines = md.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines)


def render_markdown(gen, md: str) -> str:
    """Render page markdown to HTML, including fenced copy-paste install blocks.

    Existing report pages do not use fences, so this stays local instead of changing
    reports_page.render.
    """
    parts: list[str] = []
    rest = md
    fence = re.compile(r"^```(\w*)\n(.*?)\n```", re.M | re.S)

    def flush_prose(chunk: str) -> None:
        chunk = chunk.strip("\n")
        if chunk:
            parts.append(reports_page.render(gen, chunk))

    pos = 0
    for m in fence.finditer(md):
        flush_prose(md[pos:m.start()])
        code = m.group(2)
        parts.append(f"<pre><code>{gen.esc(code)}</code></pre>")
        pos = m.end()
    flush_prose(md[pos:])
    return "\n  ".join(p for p in parts if p)


def page_markdown(key: str, figs: dict) -> str:
    if key == "cost":
        return cost_page(figs)
    return cheapest_page(key, figs)


def write_all(gen) -> list[str]:
    figs = build_figures()
    paths: list[str] = []
    for key, spec in PAGE_SPECS.items():
        raw = page_markdown(key, figs)
        meta, body_md = front_matter(raw)
        title = meta.get("title") or (f"Cheapest {key} rental this week ({figs['week_label']})" if key != "cost" else "Cost to fine-tune a 7B or 8B model (LoRA, e.g. Llama 3.1 8B)")
        desc = meta.get("meta_description") or title
        rel = spec["path"]
        url = f"{gen.BASE}/{rel}/"
        html = render_markdown(gen, _strip_leading_h1(body_md))
        assert not FORBIDDEN.search(html), f"forbidden link/path in {rel}"
        assert not FORBIDDEN.search(title + desc), f"forbidden text in {rel} title/meta"
        if rel.startswith("reports/"):
            crumbs = (
                f'  <p class="crumbs"><a href="{gen.BASE}/">Home</a> · '
                f'<a href="{gen.BASE}/reports/">Reports</a></p>\n'
            )
        else:
            crumbs = (
                f'  <p class="crumbs"><a href="{gen.BASE}/">Home</a> · '
                f'<a href="{gen.BASE}/cost/">Cost</a></p>\n'
            )
        body = crumbs + f"  <h1>{gen.esc(title)}</h1>\n  {html}\n"
        out = ROOT / rel
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(
            gen.page_shell(f"{title} | Lantern Works", desc, url, body),
            encoding="utf-8",
        )
        paths.append(rel)
        print(f"seo_batch1={rel}")
    return paths
