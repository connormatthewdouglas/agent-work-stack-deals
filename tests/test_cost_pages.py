import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cost_pages  # noqa: E402

FEED = json.loads((ROOT / "api/v1/gpu-prices.json").read_text(encoding="utf-8"))


def test_twelve_pages_in_sitemap():
    sm = (ROOT / "sitemap.xml").read_text()
    for slug in cost_pages.GPUS:
        for h in cost_pages.HOURS:
            assert (ROOT / f"cost/{slug}-{h}-hours/index.html").is_file()
            assert f"/cost/{slug}-{h}-hours/" in sm


def test_eligibility_fails_closed():
    held = {h["vendor"] for h in FEED["held_stale"]}
    for fam in cost_pages.GPUS.values():
        for (gpu, vram), rows in cost_pages.eligible(FEED, fam).items():
            assert len({r["advertiser"] for r in rows}) >= 2
            for r in rows:
                assert r["tier_class"] == "on-demand" and not r["interruptible"] and (r.get("min_gpus") or 1) == 1
                assert r["advertiser"] not in held and r["billing_unit"] in ("hourly", "per-second")
                assert r["gpu"] == gpu and r["vram_gb"] == vram


def test_pages_math_and_exclusions():
    for p in (ROOT / "cost").glob("*/index.html"):
        s = p.read_text(encoding="utf-8")
        assert "TensorDock" not in s and "Clore" not in s and "Compute subtotal only" in s
        h = int(re.search(r"-(\d+)-hours", str(p)).group(1))
        for rate, sub in re.findall(r'\$/GPU-hr">\$([\d.]+)</td><td data-label="\d+ h subtotal"><strong>\$([\d,.]+)', s):
            assert abs(round(float(rate) * h, 2) - float(sub.replace(",", ""))) < 0.006
