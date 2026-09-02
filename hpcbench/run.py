"""
Evaluate one submission: prepare, verify, measure, score.

Two-phase by design.

    prepare   UNTIMED. Reads the raw corpus once and writes whatever on-disk
              representation the student chose into a scratch workdir. Format
              decisions, sorting, compression and quantization happen here and
              none of it is on the clock.

    solution  TIMED, end to end, by process wall clock: load that
              representation, compute, write the result. Nothing inside the
              process has to be trusted, because the harness holds the watch.

    checksum  Computed by the harness from the result file afterwards, so it
              is never on the clock either.

A swept task runs `solution` once per sweep value. Every value must produce a
correct result, and the score is the geometric mean of the per-value speedups —
which is what stops a kernel being tuned to one operand width.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from .canon import NonFiniteError, digest_file
from .measure import host_fingerprint, measure
from .task import Metric, Task, geometric_mean, score_benchmark


def _sh(cmd: str, cwd: str, timeout: int = 3600, env: Optional[dict] = None):
    p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True,
                       text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout + p.stderr)[-8000:]


def _git(cwd: str, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def _mem_limiter(mb: int):
    def limiter():
        soft = mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
    return limiter


def _expected(task: Task, which_input: str, key: str):
    ref = task.reference_digest.get(which_input)
    if isinstance(ref, dict):
        return ref.get(key)
    return ref


def evaluate(submission_dir: str, task: Task, *, input_path: Optional[str] = None,
             which_input: str = "public", tier: str = "cloud",
             enforce_mem: bool = True, allow_unstable: bool = False) -> dict:
    """Full evaluation of one submission. Never raises on student error."""
    t_start = time.time()
    rec: dict = {
        "task": task.id, "tier": tier, "input": which_input,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "commit": _git(submission_dir, "rev-parse", "HEAD"),
        "commit_short": _git(submission_dir, "rev-parse", "--short", "HEAD"),
        "host": host_fingerprint(), "status": "error", "checksum_ok": False,
        "digests": {}, "metrics": {}, "per_sweep": {}, "score": None, "log": "",
    }
    rec["host"]["tier"] = tier

    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = str(task.threads)
    env.setdefault("OMP_PROC_BIND", "close")
    env.setdefault("OMP_PLACES", "cores")

    # ---- build ------------------------------------------------------------
    for step in task.build:
        code, out = _sh(step, submission_dir, env=env)
        rec["log"] += f"$ {step}\n{out}\n"
        if code != 0:
            rec["status"] = "build_failed"
            rec["error"] = f"build step failed: {step}"
            return rec

    # ---- resolve the input (always the grader's copy) ----------------------
    if input_path:
        inp = os.path.abspath(input_path)
    else:
        rel = task.public_input if which_input == "public" else task.holdout_input
        inp = os.path.abspath(rel if os.path.isabs(rel)
                              else os.path.join(submission_dir, rel))
    if not os.path.exists(inp):
        rec["status"] = "error"
        rec["error"] = f"input not found: {inp}"
        return rec
    rec["input_path"] = inp

    # Absolute: prepare and solution both run with cwd=submission_dir,
    # so a relative workdir would resolve twice.
    work = os.path.abspath(os.path.join(submission_dir, task.workdir))
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    # ---- prepare: UNTIMED --------------------------------------------------
    if task.prepare:
        t0 = time.time()
        for step in task.prepare:
            cmd = step.replace("{input}", inp).replace("{work}", work)
            code, out = _sh(cmd, submission_dir, timeout=3600, env=env)
            rec["log"] += f"$ [prepare, untimed] {cmd}\n{out}\n"
            if code != 0:
                rec["status"] = "prepare_failed"
                rec["error"] = f"prepare step failed: {cmd}"
                return rec
        rec["prepare_s"] = round(time.time() - t0, 1)

    # ---- solution: TIMED ---------------------------------------------------
    values = task.sweep_values or [None]
    result_path = os.path.join(submission_dir, task.result_file)
    per: dict = {}
    speedups: list = []
    limit = task.sanity_timeout_s or task.timeout_s
    pm = task.primary_metric

    for v in values:
        key = str(v) if v is not None else "-"
        cmd = list(task.entrypoint) + [work, task.result_file]
        if v is not None:
            cmd.append(str(v))

        # A stale or committed result.bin must never stand in for a
        # computation that did not happen.
        if os.path.exists(result_path):
            try:
                os.unlink(result_path)
            except OSError as e:
                rec["status"] = "error"
                rec["error"] = f"could not clear stale result: {e}"
                return rec

        try:
            p = subprocess.run(
                cmd, cwd=submission_dir, env=env, capture_output=True, text=True,
                timeout=limit,
                preexec_fn=_mem_limiter(task.mem_limit_mb) if enforce_mem else None)
        except subprocess.TimeoutExpired:
            rec["status"] = "too_slow"
            rec["error"] = (f"exceeded the {limit}s sanity ceiling at "
                            f"{task.sweep_arg}={key}. Cancelled, not scored.")
            return rec
        except Exception as e:
            rec["status"] = "error"
            rec["error"] = f"could not launch: {e}"
            return rec

        rec["log"] += f"$ [timed] {' '.join(cmd)}\n{(p.stdout + p.stderr)[-4000:]}\n"
        if p.returncode != 0:
            rec["status"] = "run_failed"
            rec["error"] = f"exit {p.returncode} at {task.sweep_arg}={key}"
            return rec
        if not os.path.exists(result_path):
            rec["status"] = "no_result"
            rec["error"] = f"no {task.result_file} at {task.sweep_arg}={key}"
            return rec

        # ---- checksum: harness-side, untimed -------------------------------
        try:
            got, n, dims = digest_file(result_path, task.canon)
        except NonFiniteError as e:
            rec["status"] = "nonfinite"
            rec["error"] = f"{e} (at {task.sweep_arg}={key})"
            return rec
        except Exception as e:
            rec["status"] = "bad_result"
            rec["error"] = f"unreadable result at {task.sweep_arg}={key}: {e}"
            return rec

        rec["digests"][key] = got
        want = _expected(task, which_input, key)
        if want is None:
            rec["checksum_ok"] = True
            rec["status"] = "reference"
        elif got != want:
            rec["status"] = "wrong_answer"
            rec["error"] = (f"checksum mismatch at {task.sweep_arg}={key}\n"
                            f"  expected {want}\n  got      {got}\n"
                            f"Differs from the reference at "
                            f"{task.canon.sig_digits} significant digits.")
            return rec
        else:
            rec["checksum_ok"] = True

        # ---- measurement ---------------------------------------------------
        m = measure(cmd, submission_dir, runs=task.runs, warmup=task.warmup,
                    timeout=limit, threads=task.threads, env=env,
                    with_counters=(v == values[-1]))
        if not m.ok:
            rec["status"] = "measure_failed"
            rec["error"] = f"{m.error} (at {task.sweep_arg}={key})"
            return rec
        if m.unstable and not allow_unstable:
            rec["status"] = "unstable"
            rec["error"] = (f"IQR is {100 * m.iqr_ms / m.median_ms:.1f}% of median "
                            f"at {task.sweep_arg}={key} (limit 10%). Not scored.")
            return rec

        e = {"median_ms": round(m.median_ms, 3), "iqr_ms": round(m.iqr_ms, 3),
             "peak_rss_mb": round(m.peak_rss_mb, 2),
             "cpu_efficiency": m.cpu_efficiency,
             "counters": {k: round(x, 6) for k, x in m.counters.items()
                          if isinstance(x, float)}}
        base = pm.baseline_by_sweep.get(key) if pm.baseline_by_sweep else pm.baseline
        if base:
            e["speedup"] = round(base / m.median_ms, 3)
            speedups.append(base / m.median_ms)
        per[key] = e

    rec["per_sweep"] = per

    # ---- aggregate ---------------------------------------------------------
    meds = [x["median_ms"] for x in per.values()]
    rec["metrics"] = {
        "median_ms": round(sum(meds) / len(meds), 3),
        "total_ms": round(sum(meds), 3),
        "iqr_ms": round(max(x["iqr_ms"] for x in per.values()), 3),
        "peak_rss_mb": round(max(x["peak_rss_mb"] for x in per.values()), 2),
        "cpu_efficiency": max(x["cpu_efficiency"] for x in per.values()),
        "runs": task.runs, "unstable": False,
    }
    rec["metrics"].update(per[list(per)[-1]].get("counters", {}))

    if speedups:
        g = geometric_mean(speedups)
        rec["speedup"] = round(g, 3)
        rec["metrics"]["geomean_speedup"] = round(g, 3)
        if pm.full_credit_at:
            synth = Metric(key="geomean_speedup", label="Speedup", direction="min",
                           baseline=1.0, full_credit_at=pm.full_credit_at)
            rec["score"] = round(score_benchmark(1.0 / g, synth), 2)

    if rec["status"] != "reference":
        rec["status"] = "ok"
    rec["elapsed_s"] = round(time.time() - t_start, 1)
    return rec


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="hpcbench-run")
    ap.add_argument("--task", required=True)
    ap.add_argument("--submission", required=True)
    ap.add_argument("--input", choices=["public", "holdout"], default="public")
    ap.add_argument("--input-path", default=None)
    ap.add_argument("--tier", default=os.environ.get("HPCBENCH_TIER", "cloud"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--handle", default=os.environ.get("HPCBENCH_HANDLE", "anon"))
    ap.add_argument("--no-mem-limit", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    task = Task.load(a.task)
    rec = evaluate(a.submission, task, input_path=a.input_path,
                   which_input=a.input, tier=a.tier,
                   enforce_mem=not a.no_mem_limit)
    rec["handle"] = a.handle

    text = json.dumps(rec, indent=2)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w").write(text)

    s = rec["status"]
    if s in ("ok", "reference"):
        lab = task.sweep_arg or "run"
        print(f"\n  {lab:>6} {'median':>11} {'IQR':>9} {'RSS':>8} {'speedup':>9}",
              file=sys.stderr)
        for k, e in rec["per_sweep"].items():
            sp = f"{e['speedup']:.2f}x" if e.get("speedup") else "-"
            print(f"  {k:>6} {e['median_ms']:>9.1f}ms {e['iqr_ms']:>7.1f}ms "
                  f"{e['peak_rss_mb']:>6.0f}MB {sp:>9}", file=sys.stderr)
        if rec.get("speedup"):
            print(f"\n  geometric mean speedup: {rec['speedup']:.2f}x"
                  f"    score {rec.get('score')}/25", file=sys.stderr)
        if rec.get("prepare_s"):
            print(f"  (prepare took {rec['prepare_s']}s -- untimed)", file=sys.stderr)
    else:
        print(f"\n{s.upper()}: {rec.get('error','')}", file=sys.stderr)

    if not a.quiet:
        print(text)
    return 0 if s in ("ok", "reference") else 1


if __name__ == "__main__":
    raise SystemExit(main())
