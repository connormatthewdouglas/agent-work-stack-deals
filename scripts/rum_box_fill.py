#!/usr/bin/env python3
"""Box-side Web Analytics fill (no token in CI or in this repo).

1. Read rumPageloadEventsAdaptiveGroups through the Cloudflare connector (execute tool, account ef442e8e...):
     query($a:String!,$s:String!,$d:Date!){viewer{accounts(filter:{accountTag:$a}){rumPageloadEventsAdaptiveGroups(
       limit:5000,filter:{siteTag:$s,date_geq:$d}){count dimensions{date requestPath}}}}}
   with a=ef442e8e10dbf540761ddc41055775f1, s=b392c8b327c143ae8483491ccd72751d, d=today-84d; save the array as JSON.
2. python3 scripts/rum_box_fill.py groups.json [--push]
   rebuilds stats.json with page_views / visits_by_ref (/e/ref/<ref>/) from those rows; an empty array stays null
   with a reason (never a fake zero). --push commits stats.json and pushes to main (rebase retry).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    push = "--push" in argv
    argv = [a for a in argv if a != "--push"]
    if len(argv) != 1:
        print(__doc__)
        return 2
    sys.path.insert(0, str(ROOT / "scripts"))
    import site_stats
    rc = site_stats.main(["--rum-groups", argv[0]])
    if rc or not push:
        return rc
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], check=True)  # noqa: E731
    if not subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "stats.json"], capture_output=True, text=True).stdout:
        print("stats.json unchanged")
        return 0
    git("add", "stats.json")
    git("commit", "-qm", "data: site stats, Web Analytics box-side fill")
    for _ in range(3):
        if subprocess.run(["git", "-C", str(ROOT), "push", "-q", "origin", "HEAD:main"]).returncode == 0:
            return 0
        git("pull", "-q", "--rebase", "origin", "main")
    return 1


if __name__ == "__main__":
    sys.exit(main())
