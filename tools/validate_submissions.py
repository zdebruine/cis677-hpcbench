#!/usr/bin/env python3
"""
Reject results that do not belong to somebody on the roster.

This is where ownership is actually enforced. The website cannot do it -- it is
static files on a CDN with no server to check anything against. CI can, because
it sees both the declared owner inside the file and the GitHub account that
pushed it, and can refuse to publish when they disagree.

    python3 tools/validate_submissions.py                 # check everything
    python3 tools/validate_submissions.py --actor zdebruine  # also check authorship

Exit status is non-zero on the first violation, so it fails the build.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

SCHEMA_PREFIX = "hpcbench/device-run/"


def load_roster(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster", default="users/users.json")
    ap.add_argument("--results", default="results")
    ap.add_argument("--actor", default=os.environ.get("GITHUB_ACTOR"),
                    help="the GitHub login that pushed; when given, a result's "
                         "owner must map to it (admins may push for anyone)")
    a = ap.parse_args(argv)

    cfg = load_roster(a.roster)
    users = cfg.get("users", {})
    admins = {h for h, u in users.items() if u.get("role") == "admin"}
    by_github = {u.get("github", "").lower(): h for h, u in users.items()}

    problems: list[str] = []
    checked = 0

    for path in sorted(glob.glob(os.path.join(a.results, "**", "*.json"),
                                 recursive=True)):
        try:
            with open(path) as f:
                rec = json.load(f)
        except ValueError as e:
            problems.append(f"{path}: not valid JSON ({e})")
            continue
        checked += 1

        owner = rec.get("owner")
        if not owner:
            problems.append(f"{path}: no owner. Every result belongs to somebody.")
            continue
        if owner not in users:
            problems.append(
                f"{path}: owner '{owner}' is not on the roster. "
                f"Add them to {a.roster} first.")
            continue

        if rec.get("schema", "").startswith(SCHEMA_PREFIX):
            dev_owner = rec.get("device", {}).get("owner")
            if dev_owner and dev_owner != owner:
                problems.append(
                    f"{path}: bundle owner '{owner}' but device owner "
                    f"'{dev_owner}'. Pick one.")
            if not rec.get("entries"):
                problems.append(f"{path}: bundle has no entries.")
            elif not any(e.get("handle") == "baseline" for e in rec["entries"]):
                problems.append(
                    f"{path}: no 'baseline' entry. A device's numbers have no "
                    f"scale without it and cannot be compared to any other "
                    f"device's.")

        if a.actor:
            actor_handle = by_github.get(a.actor.lower())
            if actor_handle is None:
                problems.append(
                    f"{path}: pushed by GitHub user '{a.actor}', who is not on "
                    f"the roster.")
            elif actor_handle != owner and actor_handle not in admins:
                problems.append(
                    f"{path}: owner is '{owner}' but '{actor_handle}' pushed it. "
                    f"Only the owner or an admin may submit a result.")

    if problems:
        print(f"{len(problems)} problem(s) in {checked} file(s):\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"ok: {checked} result file(s), every one owned by a roster member")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
