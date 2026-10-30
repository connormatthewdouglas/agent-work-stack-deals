"""T20 Phase B: look up a directly applicable published throughput figure (data/gpu_throughput.json, PR #43).

Never invents or interpolates. A figure is used only if ALL hold:
  * MLPerf Inference, closed division, result_validity VALID (vendor TFLOPS specs are peaks, not workload throughput);
  * GPU model AND variant (form factor / memory) resolve to exactly one variant in the dataset;
  * workload is an inference workload in the dataset (training / fine-tune never resolve);
  * not flagged unrepresentative (reference implementations, e.g. 4090 SDXL fp32 PyTorch reference) or sparsity;
  * per-GPU value is either reported per-GPU (gpu_count == 1) or derivable by dividing by the exact stated
    accelerator count (labelled derived, assumes linear scaling).
Exactly one eligible figure must remain; otherwise None (caller keeps the 'missing: throughput' error).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# T43: the benchmark asset ships INSIDE the package (wheel and hosted bundle), loaded package-relative, never from a
# source checkout. core/assets/gpu_throughput.json is a byte copy of data/gpu_throughput.json (tests enforce it).
PATH = Path(__file__).resolve().parent / "assets" / "gpu_throughput.json"
SCHEMA = "lantern-works-gpu-throughput/1"
ASSET_ERROR = "benchmark asset missing or corrupt"


class AssetError(Exception):
    """The packaged benchmark asset could not be read. Not the same as an unsupported workload."""
TRAINING = re.compile(r"\b(train|training|fine[- ]?tun\w*|finetun\w*|lora|qlora|sft|rlhf|dpo|pre[- ]?train\w*)\b", re.I)
ALIASES = {  # dataset workload key -> regex over the user's workload label
    "bert-large": r"\bbert(?:[- ]?large|[- ]?99)?\b",
    "resnet50": r"\bresnet[- ]?50\b",
    "sdxl": r"\bsdxl\b|stable[- ]diffusion[- ]xl",
    "llama2-70b": r"\bllama[- ]?2[- ]?70b\b",
    "gpt-j-6b": r"\bgpt[- ]?j(?:[- ]?6b)?\b",
}
FORMS = {"sxm", "pcie", "nvl"}


def _read(path=None):
    if path is not None:
        return Path(path).read_text()
    try:
        from importlib import resources
        return resources.files(__package__).joinpath("assets", "gpu_throughput.json").read_text()
    except Exception:
        pass
    try:  # hosted worker bundle: build.sh embeds the same bytes as a module (Workers ship .py modules only)
        from . import _asset_gpu_throughput
        return _asset_gpu_throughput.TEXT
    except ImportError:
        return PATH.read_text()


def _load(path=None):
    try:
        doc = json.loads(_read(path))
    except (OSError, ValueError, TypeError) as e:
        raise AssetError(f"{ASSET_ERROR}: {type(e).__name__}") from None
    figs = doc.get("figures") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(figs, list) or not figs:
        raise AssetError(f"{ASSET_ERROR}: unexpected schema or no figures")
    return figs


def asset_info(path=None):
    """Version and size of the packaged benchmark asset (for artifact checks)."""
    doc = json.loads(_read(path))
    return {"schema": doc.get("schema"), "generated_at": doc.get("generated_at"), "figures": len(doc.get("figures") or [])}


def _toks(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def workload_key(workload: str | None):
    if not workload or TRAINING.search(workload):
        return None
    keys = [k for k, rx in ALIASES.items() if re.search(rx, workload, re.I)]
    return keys[0] if len(keys) == 1 else None


def _skip_reason(f):
    c = f.get("conditions") or {}
    if f.get("source_type") != "mlperf_inference":
        return "not an inference benchmark result"
    if c.get("division") != "closed" or c.get("result_validity") != "VALID":
        return "not a valid closed-division result"
    if c.get("sparsity"):
        return "sparsity figure"
    if "reference" in (c.get("software") or "").lower() or "reference" in (c.get("system") or "").lower():
        return "reference implementation (unrepresentative)"
    n = c.get("gpu_count")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        return "accelerator count not stated"
    if f.get("unit") not in ("samples/s", "tokens/s") or not isinstance(f.get("value"), (int, float)):
        return "unit not a throughput rate"
    return None


def lookup(gpu_family: str, workload: str | None, path=None):
    """Return (figure_dict, None) or (None, reason)."""
    key = workload_key(workload)
    if key is None:
        return None, "no inference workload in the dataset matches (training/fine-tune are never resolved)"
    gq = gpu_family.lower()
    q = _toks(re.sub(r"(\d{2,3})\s*gb", r"\1gb", gq))
    form = q & FORMS
    mem = {t for t in q if re.fullmatch(r"\d{2,3}gb", t)}
    cands = []
    for f in _load(path):
        model = _toks(f.get("gpu"))
        model_id = max(model, key=lambda t: any(ch.isdigit() for ch in t)) if model else None
        if f.get("workload") != key or model_id not in q:
            continue
        vt = _toks(f.get("variant"))
        if (form and not form <= vt) or (mem and not mem <= vt):
            continue
        cands.append(f)
    variants = sorted({f"{f['gpu']} {f['variant']}" for f in cands})
    if len(variants) > 1:
        return None, f"'{gpu_family}' is ambiguous across {', '.join(variants)}; name the variant"
    ok = [f for f in cands if not _skip_reason(f)]
    if not cands:
        return None, f"no published {key} figure for {gpu_family}"
    if len(ok) != 1:
        return None, ("published figure skipped: " + "; ".join(sorted({_skip_reason(f) for f in cands if _skip_reason(f)}))
                      if not ok else "more than one eligible figure; not choosing")
    f = ok[0]
    c = f["conditions"]
    n = c["gpu_count"]
    derived = n > 1
    per_gpu_s = f["value"] / n
    caveats = [f"{c.get('scenario')} scenario, {c.get('precision')}, {c.get('software')}",
               f"batch: {c.get('batch')}", "benchmark-tuned submission; your stack/model config may differ"]
    if derived:
        caveats.insert(0, f"derived per-GPU from {n}-GPU result, assumes linear scaling")
    unit = f["unit"].replace("/s", "")
    return {"value_per_gpu_hour": per_gpu_s * 3600, "unit": unit, "workload_key": key,
            "throughput_source": {"url": f["source_url"], "quote": f["quote"], "date": f.get("publication_date"),
                                  "benchmark": f"{f['metric']} ({f.get('workload_name')}, {c.get('system')}, {c.get('submitter')})",
                                  "gpu": f"{f['gpu']} {f['variant']}", "reported_value": f["value"],
                                  "reported_unit": f["unit"], "reported_gpu_count": n, "derived": derived,
                                  "caveats": caveats}}, None
