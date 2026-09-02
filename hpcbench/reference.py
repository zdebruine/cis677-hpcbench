"""
Generate a task's reference digests and baseline timings.

Run this once per task, against the instructor's reference implementation, on
the machine that will do the scoring. It writes the digests and the baseline
back into task.yaml so student submissions have something to be checked against.

    python -m hpcbench.reference --task tasks/p3-spmm/task.yaml \
        --reference reference-impl/ --data-dir data/

Re-run it whenever the reference implementation, the input data, or the canon
spec changes. The digest is version-stamped, so a canon change invalidates old
results loudly rather than silently.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .run import evaluate
from .task import Task


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hpcbench-reference")
    ap.add_argument("--task", required=True)
    ap.add_argument("--reference", required=True, help="reference implementation dir")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--tier", default=os.environ.get("HPCBENCH_TIER", "cloud"))
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    a = ap.parse_args(argv)

    with open(a.task) as f:
        raw = json.load(f)
    raw["reference_digest"] = {}   # always regenerate from scratch
    for m in raw["metrics"]:
        if m.get("primary"):
            m["baseline"] = None
            m["baseline_by_sweep"] = {}
    tmp = a.task + ".tmp"
    with open(tmp, "w") as f:
        json.dump(raw, f)
    task = Task.load(tmp)
    os.unlink(tmp)

    digests, baseline = {}, None
    for which in ("public", "holdout"):
        path = os.path.join(a.data_dir, f"{which}.bin")
        if not os.path.exists(path):
            print(f"  skip {which}: {path} not found", file=sys.stderr)
            continue
        rec = evaluate(a.reference, task, input_path=path,
                       which_input=which, tier=a.tier, allow_unstable=True)
        # A reference run only needs digests and a ballpark baseline; a noisy
        # measurement is a warning here, not a failure.
        if rec["status"] == "unstable":
            print(f"  WARNING {which}: {rec['error']}", file=sys.stderr)
        elif rec["status"] not in ("reference", "ok"):
            print(f"FAILED on {which}: {rec['status']}: {rec.get('error')}",
                  file=sys.stderr)
            print(rec["log"][-3000:], file=sys.stderr)
            return 1
        digests[which] = rec["digests"] if len(rec["digests"]) > 1 or task.sweep_values \
            else list(rec["digests"].values())[0]
        print(f"  {which}:", file=sys.stderr)
        for k, e in rec["per_sweep"].items():
            print(f"    {task.sweep_arg or 'run'}={k:<5} {e['median_ms']:>9.1f} ms  "
                  f"{e['peak_rss_mb']:>6.0f} MB  {rec['digests'][k][:16]}...",
                  file=sys.stderr)
        if which == "public":
            if task.sweep_values:
                baseline = {k: e["median_ms"] for k, e in rec["per_sweep"].items()}
            else:
                baseline = round(list(rec["per_sweep"].values())[0]["median_ms"], 3)

    raw["reference_digest"] = digests
    if baseline is not None:
        for m in raw["metrics"]:
            if m.get("primary"):
                if isinstance(baseline, dict):
                    m["baseline_by_sweep"] = baseline
                    m["baseline"] = round(sum(baseline.values()) / len(baseline), 3)
                else:
                    m["baseline"] = baseline

    text = json.dumps(raw, indent=2)
    if a.dry_run:
        print(text)
    else:
        with open(a.task, "w") as f:
            f.write(text)
        print(f"\nwrote {a.task}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
