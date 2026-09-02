"""Landing page listing every task's leaderboard."""
from __future__ import annotations
import argparse, glob, html, json, os
from datetime import datetime, timezone
from .leaderboard import CSS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hpcbench-index")
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    cards = []
    for path in sorted(glob.glob(os.path.join(a.tasks, "*", "task.yaml"))):
        t = json.load(open(path))
        pm = next((m for m in t["metrics"] if m.get("primary")), t["metrics"][0])
        cards.append(
            f'<a class="tile" style="text-decoration:none;color:inherit;display:block" '
            f'href="{html.escape(t["id"])}.html">'
            f'<div class="k">{html.escape(t["id"])}</div>'
            f'<div class="v" style="font-size:1.1rem">{html.escape(t["title"])}</div>'
            f'<div class="n">{html.escape(t.get("notes","")[:110])}</div>'
            f'<div class="n" style="margin-top:6px">baseline '
            f'{pm.get("baseline","—")} ms &middot; full credit at '
            f'{pm.get("full_credit_at","—")}x</div></a>'
        )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w").write(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>CIS 677 Leaderboards</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>CIS 677 Leaderboards</h1>
<div class="sub">High-Performance Computing &middot; updated {now}</div>
<div class="tiles">{''.join(cards)}</div>
<footer>Handles only. Timings are comparable within a tier, never across tiers.</footer>
</div></body></html>""")
    print(f"wrote {a.out} ({len(cards)} tasks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
