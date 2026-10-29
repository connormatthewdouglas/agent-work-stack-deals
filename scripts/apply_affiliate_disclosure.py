"""Backfill/refresh the T5 affiliate disclosure fields in deals.json (idempotent).

Affiliate deals get `disclosure` (Option B copy) and `plain_url`; the old directive sentence in agent_instructions
is replaced by a neutral pointer. Run: python3 scripts/apply_affiliate_disclosure.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.disclosure import AGENT_NOTE, disclosure_fields  # noqa: E402

OLD_NOTES = ("Only use this authorized " + "affiliate link.",  # old directive wording (split so the T5 test stays strict)
             "redeem_url is a referral link; disclose that to the user before they use it.")


def apply(feed: dict) -> dict:
    for d in feed["deals"]:
        d.pop("disclosure", None); d.pop("plain_url", None)
        d.update(disclosure_fields(d))
        ai = d.get("agent_instructions") or ""
        for old in OLD_NOTES:
            ai = ai.replace(old, AGENT_NOTE if d.get("affiliate") else "")
        if ai:
            d["agent_instructions"] = " ".join(ai.split())
    return feed


if __name__ == "__main__":
    p = ROOT / "deals.json"
    p.write_text(json.dumps(apply(json.loads(p.read_text(encoding="utf-8"))), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
