"""T39: rate_id on every compare_gpu_prices row and optimizer option (from core.ids, T38), and a deterministic
quote_id receipt (+ issued_at) on optimize_stack / optimize_agent_stack."""
import copy
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import contract, deals, ids, quote, stack  # noqa: E402
from mcp_server import server as s  # noqa: E402

GPU = json.loads((ROOT / "api/v1/gpu-prices.json").read_text())
STACK = json.loads((ROOT / "api/v1/stack-pricing.json").read_text())
RID = re.compile(r"^r_[0-9a-f]{12}$")
QID = re.compile(r"^q_[0-9a-f]{20}$")


def _options(out):
    for line in out["lines"]:
        for o in [line.get("choice")] + list(line.get("alternatives") or []) + list(line.get("unknown_price") or []) \
                + list(line.get("not_enough") or []):
            if o:
                yield o


def test_rate_id_is_imported_from_core_ids_not_duplicated():
    assert stack.rate_id is ids.rate_id and quote.rate_id is ids.rate_id
    src = "".join((ROOT / f).read_text() for f in ("core/quote.py", "core/stack.py", "core/deals.py", "core/agent_stack.py"))
    assert "def rate_id" not in src and "def rate_identity" not in src


def test_every_compare_row_has_the_feed_rate_id():
    by_id = {ids.rate_id(r): r for r in GPU["rates"]}
    for g in ("H100", "A100", "RTX 4090", "L40S"):
        out = s.compare_gpu_prices(gpu=g, limit=25, include_reserved=True)
        assert out["ok"] and out["results"]
        for row in out["results"]:
            assert RID.match(row["rate_id"]) and row["rate_id"] in by_id
            assert by_id[row["rate_id"]]["source_url"] == row["source_url"]
        assert len({r["rate_id"] for r in out["results"]}) == len(out["results"])
        brief = s.compare_gpu_prices(gpu=g, limit=25, include_reserved=True, mode="brief")
        assert [r["rate_id"] for r in brief["results"]] == [r["rate_id"] for r in out["results"]]


def test_every_optimizer_option_has_rate_id():
    a = s.optimize_stack(scrape_pages=20000, proxy_gb=5, emails_sent=5000, search_queries=2000, gpu_hours=50)
    b = s.optimize_agent_stack(description="scrapes 20k JS pages via 5 GB residential proxies, 3k search queries, "
                                           "LLM API, 100 H100 gpu hours, postgres database, monitoring")
    for out in (a, b):
        opts = list(_options(out))
        assert opts and all(RID.match(o["rate_id"]) for o in opts), [o for o in opts if not o.get("rate_id")][:2]


def test_gpu_option_ids_match_compare_ids():
    cmp_ids = {r["rate_id"] for r in s.compare_gpu_prices(gpu="H100", limit=25)["results"]}
    line = s.optimize_stack(gpu_hours=10, gpu_model="H100")["lines"][0]
    assert {o["rate_id"] for o in [line["choice"]] + line["alternatives"]} <= cmp_ids


def test_ids_stable_across_sort_order():
    rates = copy.deepcopy(GPU["rates"])
    base = {id(r): ids.rate_id(r) for r in rates}
    for seed in range(3):
        random.Random(seed).shuffle(rates)
        data = {**GPU, "rates": rates}
        assert {id(r): ids.rate_id(r) for r in rates} == base
        out = deals.compare_gpu_prices(data, "H100", limit=25)
        ref = deals.compare_gpu_prices(GPU, "H100", limit=25)
        assert [r["rate_id"] for r in out["results"]] == [r["rate_id"] for r in ref["results"]]
        opts = stack._gpu_options(data, 10, "A100", set())
        assert sorted(o["rate_id"] for o in opts) == sorted(o["rate_id"] for o in stack._gpu_options(GPU, 10, "A100", set()))


def test_ids_stable_across_label_rename():
    renamed = copy.deepcopy(GPU)
    for r in renamed["rates"]:
        tc = deals.tier_class(r)
        if tc == "on-demand":
            r["tier"] = "Pay-as-you-go instance (renamed)"
        r["gpu"] = "  " + r["gpu"].upper() + " "
    a = {r["rate_id"] for r in deals.compare_gpu_prices(GPU, "H100", limit=25)["results"]}
    b = {r["rate_id"] for r in deals.compare_gpu_prices(renamed, "H100", limit=25)["results"]}
    assert a == b
    sa = {o["rate_id"] for o in stack._gpu_options(GPU, 10, None, set())}
    sb = {o["rate_id"] for o in stack._gpu_options(renamed, 10, None, set())}
    assert sa == sb


def test_receipt_is_deterministic_and_ignores_issued_at_and_order():
    lines = s.optimize_stack(scrape_pages=1000, emails_sent=5000, gpu_hours=10)["lines"]
    ts = {"stack_pricing_feed_updated_at": "2026-10-29T00:00:00Z", "gpu_prices_feed_updated_at": "2026-10-29T13:57:45Z"}
    t1, t2 = datetime(2026, 10, 29, 12, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc)
    r1 = quote.receipt("optimize_stack", lines, ts, t1)
    r2 = quote.receipt("optimize_stack", list(reversed(copy.deepcopy(lines))), dict(reversed(list(ts.items()))), t2)
    assert QID.match(r1["quote_id"]) and r1["quote_id"] == r2["quote_id"]
    assert r1["issued_at"] == "2026-10-29T12:00:00Z" and r2["issued_at"] == "2027-01-01T00:00:00Z"
    # any hashed input changes the id
    q2 = copy.deepcopy(lines); q2[0]["quantity"] = q2[0]["quantity"] + 1
    assert quote.receipt("optimize_stack", q2, ts, t1)["quote_id"] != r1["quote_id"]
    assert quote.receipt("optimize_stack", lines, {**ts, "gpu_prices_feed_updated_at": "2026-10-30T00:00:00Z"}, t1)["quote_id"] != r1["quote_id"]
    q3 = copy.deepcopy(lines); q3[0]["choice"]["rate_id"] = "r_000000000000"
    assert quote.receipt("optimize_stack", q3, ts, t1)["quote_id"] != r1["quote_id"]
    q4 = copy.deepcopy(lines); q4[0]["choice"]["checked_at"] = "2020-01-01T00:00:00Z"
    assert quote.receipt("optimize_stack", q4, ts, t1)["quote_id"] != r1["quote_id"]


def test_tool_receipts_repeatable_and_schema_valid():
    for tool, kw in (("optimize_stack", dict(scrape_pages=1000, gpu_hours=10)),
                     ("optimize_agent_stack", dict(description="scraping 1000 pages and 10 H100 gpu hours, budget $500/mo"))):
        a, b = getattr(s, tool)(**kw), getattr(s, tool)(**kw, mode="brief")
        assert QID.match(a["quote_id"]) and a["quote_id"] == b["quote_id"]
        datetime.fromisoformat(a["issued_at"].replace("Z", "+00:00"))
        assert a["quote_basis"]["items"] and all(RID.match(i["rate_id"]) for i in a["quote_basis"]["items"])
        gpu_items = [i for i in a["quote_basis"]["items"] if i["hours"] is not None]
        gpu_line = next(l for l in a["lines"] if l.get("need", l.get("component")) in ("gpu_hours", "gpu"))
        assert gpu_items and gpu_items[0]["hours"] == gpu_line["quantity"] and gpu_items[0]["gpus"] == 1
        for out in (a, b):
            jsonschema.validate(json.loads(json.dumps(out)), contract.output_schema(tool))
        assert getattr(s, tool)(**kw)["quote_id"] == a["quote_id"]


def test_schema_rejects_missing_ids():
    out = s.compare_gpu_prices(gpu="H100", limit=2)
    bad = copy.deepcopy(out); del bad["results"][0]["rate_id"]
    try:
        jsonschema.validate(bad, contract.output_schema("compare_gpu_prices"))
        raise AssertionError("missing rate_id accepted")
    except jsonschema.ValidationError:
        pass
    o = s.optimize_stack(gpu_hours=10)
    bad = copy.deepcopy(o); del bad["quote_id"]
    try:
        jsonschema.validate(bad, contract.output_schema("optimize_stack"))
        raise AssertionError("missing quote_id accepted")
    except jsonschema.ValidationError:
        pass
