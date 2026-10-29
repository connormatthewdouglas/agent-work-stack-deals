"""T20 Phase A/B: cost-per-job estimator (user-supplied duration/throughput; Phase B: published benchmark fallback via core.throughput).

Pricing is NOT reimplemented: every candidate is priced by gpu.estimate() (the shared T35 whole-instance
calculation: instances = ceil(max(gpus, min_gpus) / gpus_per_instance), all allocated GPUs billed).
No throughput/benchmark numbers ship with this module (spec t20-t24 §2: no cited throughput library exists yet),
so a request naming a workload/model without user throughput returns missing: throughput, never a guess.
Only hourly-billed, non-reserved rates from the published feed (held_stale is never in `rates`) are ranked.
"""
from __future__ import annotations

import math

from . import data_age
from .gpu import estimate
from .ids import rate_id
from . import throughput as _tp

MAX_TOP = 25
LABEL = "compute subtotal only; excludes storage, egress, vCPU/RAM add-ons and tax"


class JobCostError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _num(name, v, positive=True):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or (v <= 0 if positive else v < 0):
        raise JobCostError("invalid_argument", f"{name} must be a number > 0")
    return float(v)


def _tokens(s: str) -> set:
    import re
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def estimate_job_cost(data: dict, gpu_family: str, gpus_per_job: int, job_hours: float | None = None,
                      work_units: float | None = None, throughput_units_per_gpu_hour: float | None = None,
                      workload: str | None = None, allow_interruptible: bool = False, min_vram_gb: int | None = None,
                      runs_per_month: float | None = None, top_n: int = 5, max_data_age_hours: float | None = None,
                      now=None) -> dict:
    if not gpu_family or not _tokens(gpu_family):
        raise JobCostError("invalid_argument", "gpu_family is required, e.g. 'H100', 'A100 80GB', 'L40S'")
    if isinstance(gpus_per_job, bool) or not isinstance(gpus_per_job, int) or gpus_per_job < 1:
        raise JobCostError("invalid_argument", "gpus_per_job must be an integer >= 1")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= MAX_TOP:
        raise JobCostError("invalid_argument", f"top_n must be an integer 1-{MAX_TOP}")
    job_hours = _num("job_hours", job_hours)
    work_units = _num("work_units", work_units)
    tput = _num("throughput_units_per_gpu_hour", throughput_units_per_gpu_hour)
    runs = _num("runs_per_month", runs_per_month)
    try:
        max_h = data_age.validate_max_age(max_data_age_hours)
    except ValueError as e:
        raise JobCostError("invalid_argument", str(e))
    gpu_l = gpu_family.strip()
    assumptions = []
    if job_hours is not None and (work_units is not None or tput is not None):
        raise JobCostError("invalid_argument", "give job_hours OR (work_units + throughput_units_per_gpu_hour), not both")
    basis, source = "user_supplied", None
    if job_hours is None:
        if work_units is None or tput is None:
            fig, why = (None, None)
            if tput is None and workload:
                fig, why = _tp.lookup(gpu_l, workload)
            miss = f"throughput for {gpu_l}" + (f" running {workload}" if workload else "")
            if fig is None:
                raise JobCostError("not_found", f"missing: {miss}. No directly applicable cited throughput"
                                                + (f" ({why})" if why else "") + ", so no duration is estimated. Pass "
                                                "job_hours, or work_units plus throughput_units_per_gpu_hour from your own benchmark.")
            if work_units is None:
                raise JobCostError("not_found", f"missing: work_units ({fig['unit']}) for {workload}. A published "
                                                f"throughput exists ({fig['throughput_source']['url']}); pass work_units "
                                                f"in {fig['unit']} to estimate a duration.")
            tput, basis, source = fig["value_per_gpu_hour"], "published_benchmark", fig["throughput_source"]
            job_hours = work_units / (tput * gpus_per_job)
            assumptions.append(f"{work_units:g} {fig['unit']} at {tput:.6g} {fig['unit']}/GPU-hour (published benchmark: "
                               f"{source['benchmark']}"
                               + ("; derived per-GPU from " + str(source['reported_gpu_count']) + "-GPU result, assumes linear scaling"
                                  if source["derived"] else "") + f") on {gpus_per_job} GPUs = {job_hours:.4g} h "
                               "(linear scaling across GPUs assumed)")
        else:
            job_hours = work_units / (tput * gpus_per_job)
            assumptions.append(f"{work_units:g} work units at {tput:g} units/GPU-hour (your benchmark) on {gpus_per_job} GPUs "
                               f"= {job_hours:.4g} h (your input; linear scaling across GPUs assumed)")
    assumptions.insert(0, f"Assumes {job_hours:.4g} h on {gpus_per_job} GPUs"
                          + (" (from published benchmark)" if source else " (your input)"))
    if workload and not source:
        assumptions.append(f"workload '{workload}' is a label only; no throughput is inferred from it")

    import re
    vm = re.search(r"\b(\d{2,3})\s*gb\b", gpu_l, re.I)
    want_vram = int(vm.group(1)) if vm else None
    q = _tokens(re.sub(r"\b\d{2,3}\s*gb\b", " ", gpu_l, flags=re.I))
    rows, too_old = [], 0
    for r in data.get("rates") or []:
        if not isinstance(r, dict) or r.get("unit") != "hour" or not isinstance(r.get("price_usd"), (int, float)):
            continue
        if not q <= _tokens(r.get("gpu", "")) or (want_vram and r.get("vram_gb") != want_vram):
            continue
        if r.get("tier_class") == "reserved" or (r.get("interruptible") and not allow_interruptible):
            continue
        if data_age.too_old(r, max_h, now):
            too_old += 1
            continue
        rows.append(r)
    if not rows:
        raise JobCostError("not_found", f"No rankable hourly rate tracked for '{gpu_l}'"
                                        + (f" ({too_old} older rates excluded by max_data_age_hours)" if too_old else ""))
    priced = estimate(rows, job_hours, gpus_per_job, min_vram_gb=min_vram_gb)
    from .deals import oos_note, out_of_stock
    from .stack import avail_fields
    priced.sort(key=out_of_stock)  # F1: stable; explicit out-of-stock rows rank after in-stock/unknown rows
    out_rows = []
    for i, r in enumerate(priced[:top_n], 1):
        per = r.get("gpu_count") or 1
        inst = math.ceil(max(gpus_per_job, r.get("min_gpus") or 1) / per)
        row = {"rank": i, "rate_id": rate_id(r), "vendor": r.get("advertiser"), "gpu": r.get("gpu"), "vram_gb": r.get("vram_gb"),
               "tier": r.get("tier"), "tier_class": r.get("tier_class"), "hourly_usd_per_gpu": r["price_usd"],
               "gpus_per_instance": per, "requested_gpus": gpus_per_job, "allocated_gpus": inst * per, "instances": inst,
               "job_hours": round(job_hours, 4), "compute_subtotal_usd": r["monthly_cost_usd"], "calc": r["calc"],
               "deal_id": r.get("deal_id"), "source_url": r.get("source_url"), "verified_at": r.get("verified_at"),
               "checked_at": r.get("checked_at"), **data_age.age_fields(r, now), **avail_fields(r)}
        if runs:
            row["monthly_subtotal_usd"] = round(r["monthly_cost_usd"] * runs, 2)
        out_rows.append(row)
    best = out_rows[0]
    oos_msg = ""
    if out_of_stock(priced[0]):
        oos_msg = f" Note: this row was {oos_note(priced[0])}; no in-stock or unknown-availability row matched."
    else:
        cheaper = [r for r in priced if out_of_stock(r) and r["monthly_cost_usd"] < priced[0]["monthly_cost_usd"]]
        if cheaper:
            c = min(cheaper, key=lambda r: r["monthly_cost_usd"])
            oos_msg = (f" Cheaper but {oos_note(c)}: {c.get('advertiser')} {c.get('gpu')} at ${c['monthly_cost_usd']:,.2f}; not picked.")
    return {"gpu_family": gpu_l, "requested_gpus": gpus_per_job, "job_hours": round(job_hours, 4), "count": len(out_rows),
            "results": out_rows, "label": LABEL,
            "summary": (f"Cheapest among tracked providers: {best['vendor']} {best['gpu']} at ${best['compute_subtotal_usd']:,.2f} "
                        f"({best['instances']} instance(s), {best['allocated_gpus']} GPUs billed) for {job_hours:.4g} h; {LABEL}." + oos_msg),
            "assumptions": assumptions, "citations": [source["url"]] if source else [],
            "throughput_basis": basis, "throughput_source": source,
            "missing_costs": ["storage", "egress", "vCPU/RAM add-ons", "tax", "billing minimums/commitments not in feed"],
            "budget_verdict": "unresolved", "excluded_too_old": too_old}
