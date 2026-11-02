"""price_check 'rotating snapshot' (Spheron rotates RAM/vCPU/NVMe per read): match GPU name + price only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import refresh_gpu_prices as rg  # noqa: E402

QUOTE = "L40S Ada 48 GB 72 GB RAM 12 vCPUs 625 GB NVMe $0.96 /hr"


def rec(**k):
    return {"gpu": "L40S", "price_usd": 0.96, "hourly_usd": 0.96, "evidence": {"quote": QUOTE}, **k}


def test_rotating_matches_despite_new_specs():
    page = "Pricing L40S Ada 48 GB 96 GB RAM 16 vCPUs 900 GB NVMe $0.96 /hr H100 SXM $2.10 /hr"
    assert rg.parse_listed(rec(price_check="batch"), page)[0] is None  # full-quote match fails on rotated specs
    v, q, msg = rg.parse_listed(rec(price_check="rotating snapshot"), page)
    assert v == "0.96" and q.startswith("L40S") and "rotating" in msg


def test_rotating_reads_a_new_price_and_flags_ambiguity():
    v, _, _ = rg.parse_listed(rec(price_check="rotating snapshot"), "L40S 64 GB RAM $0.89 /hr")
    assert v == "0.89"
    v, _, msg = rg.parse_listed(rec(price_check="rotating snapshot"), "L40S 64 GB $0.89 /hr || L40S 32 GB $0.91 /hr")
    assert v is None and msg.startswith("ambiguous")
    assert rg.parse_listed(rec(price_check="rotating snapshot"), "L40S48 $1 || no gpu here")[0] is None
