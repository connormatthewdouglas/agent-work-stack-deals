"""Shared GPU-name tokens (0.3.51, re30 b): form-factor generations collapse to the family the feed publishes, so
'A100 SXM4 80GB' == 'A100 SXM 80GB' and 'H100 PCIe5' == 'H100 PCIe' everywhere (compare, estimate, eligibility, watches)."""
from __future__ import annotations

ALIASES = {"sxm2": "sxm", "sxm3": "sxm", "sxm4": "sxm", "sxm5": "sxm", "sxm6": "sxm",
           "pcie3": "pcie", "pcie4": "pcie", "pcie5": "pcie", "pci": "pcie"}


def tokens(s) -> list[str]:
    out = []
    for t in "".join(c if c.isalnum() else " " for c in str(s or "").lower()).split():
        out.append(ALIASES.get(t, t))
    return out
