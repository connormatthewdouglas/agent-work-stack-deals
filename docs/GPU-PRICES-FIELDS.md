# gpu-prices.json: model and form fields

Every rate in `api/v1/gpu-prices.json` carries these fields (since 0.5.0, T75):

| Field | Type | Meaning |
|---|---|---|
| `gpu` | string | The GPU name as the vendor lists it (e.g. `H100 SXM`, `RTX PRO 6000 Max-Q`). Unchanged. |
| `canonical_model` | string | The tracked model this row belongs to, so consumers don't re-derive families: `H100`, `H100 SXM`, `H100 PCIe` and `H100 NVLink` are all `H100`; `A100*` is `A100`; the four `RTX PRO 6000*` strings are `RTX PRO 6000`. `H100 NVL` (94 GB) is its own model. Same grouping as the /gpu/ pages. |
| `form_factor` | string, never null | `SXM`, `SXM2`..., `PCIe`, `NVL`, or `not stated`. Taken from the vendor record when it states one, otherwise from the form named in the GPU string or in the vendor's own GPU id cited in the source (e.g. RunPod `NVIDIA B300 SXM6 AC` → `SXM6`) (an HGX board in the vendor quote counts as SXM). `NVLink` names the bridge, not the form, so it is `not stated`. Never guessed from the model alone. |
| `form_class` | string, H100 rows only | Ranking split used on the H100 pages: `SXM`, `PCIe`, `NVL` or `form not stated`. Unchanged. |

## price_basis_label, form_factor and cheapest grouping (additive, Nov 2026)

- `price_basis_label` (every row in `gpu-prices.json` and `/api/v1/gpu/<model>.json`): plain-language basis of the number.
  On-demand rows: **on-demand list price per GPU-hour; tracked providers only; excludes storage, egress, idle time and preemption.**
  Interruptible, serverless, reserved and monthly rows say so in their own label. The older `price_basis` field is unchanged.
- `form_factor` (every row): `SXM`, `PCIe`, etc. as stated by the vendor or GPU name; `unknown` in model views when the source does not say.
- `tier`: the vendor's own tier (e.g. RunPod Community Cloud vs Secure Cloud); `unknown` when the source does not say.
- `cheapest[bucket]` in model views has one row per (`vram_gb`, `form_factor`, `tier`) group, sorted by `vram_gb` then price,
  so SXM vs PCIe and Community vs Secure are never mixed in one cheapest row. Each cheapest row carries `group`, `verified_at` and `source_url`.
  Compare headline $/GPU-hour only within a group.
