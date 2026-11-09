"""Exit 3 (and say why) if any availability_expires_at in <out>/*_latest.json is already in the past. Used by push_hook.sh --force."""
import json, glob, sys
from datetime import datetime, timezone
def expired(out_dir, now=None):
    now = now or datetime.now(timezone.utc); bad = []
    def walk(x, f, path):
        if isinstance(x, dict):
            v = x.get("availability_expires_at")
            if isinstance(v, str) and datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= now:
                bad.append((f, path, v))
            for k, y in x.items(): walk(y, f, f"{path}.{k}")
        elif isinstance(x, list):
            for i, y in enumerate(x): walk(y, f, f"{path}[{i}]")
    for f in sorted(glob.glob(out_dir.rstrip("/") + "/*_latest.json")): walk(json.load(open(f)), f, "$")
    return bad
if __name__ == "__main__":
    bad = expired(sys.argv[1] if len(sys.argv) > 1 else "out")
    if bad:
        f, p, v = min(bad, key=lambda b: b[2])
        print(f"refuse push: {len(bad)} availability_expires_at already in the past in *_latest.json (earliest {v} at {f.split('/')[-1]} {p}); run a fresh collect/refresh first")
        sys.exit(3)
    print("expiry check ok")
