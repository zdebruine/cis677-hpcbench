"""
Run every submission on one device and emit a comparable result bundle.

The point of this module is that wall-clock times from a laptop, a login node
and a browser are not comparable, but *ratios measured on the same machine* are.
So a device never reports "submission X took 106 ms" as a rankable fact. It runs
the shipped baseline alongside every submission, in the same session, on the
same input, and reports each submission's speedup over that baseline. Those
ratios are what the leaderboard aggregates across devices.

    python3 -m hpcbench.device \
        --task tasks/p1-kernel/task.yaml \
        --submissions submissions/ \
        --baseline baselines/p1-kernel \
        --input-path data/p1-kernel/public.bin \
        --device-label "ThinkPad X1 / i7-1365U" --device-kind laptop \
        --out results/devices/

Every bundle carries a device fingerprint so results can be read, grouped and
argued about later. The fingerprint describes the machine, not the person.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

from .run import evaluate
from .task import Task, geometric_mean

SCHEMA = "hpcbench/device-run/1"
BASELINE_HANDLE = "baseline"


# ---------------------------------------------------------------- fingerprint

def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def _cmd(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except Exception:
        return ""


def _cpu_model() -> str:
    txt = _read("/proc/cpuinfo")
    m = re.search(r"model name\s*:\s*(.+)", txt)
    if m:
        return m.group(1).strip()
    if sys.platform == "darwin":
        return _cmd("sysctl", "-n", "machdep.cpu.brand_string") or platform.processor()
    return platform.processor() or platform.machine()


def _physical_cores() -> int:
    txt = _read("/proc/cpuinfo")
    ids = set(re.findall(r"physical id\s*:\s*(\d+)", txt))
    cores = set(re.findall(r"core id\s*:\s*(\d+)", txt))
    if ids and cores:
        return len(ids) * len(cores)
    n = _cmd("nproc", "--all")
    return int(n) if n.isdigit() else (os.cpu_count() or 0)


def _memory_gb() -> float:
    m = re.search(r"MemTotal:\s*(\d+) kB", _read("/proc/meminfo"))
    if m:
        return round(int(m.group(1)) / 1048576, 1)
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
    except (ValueError, OSError):
        return 0.0


def _isa_flags() -> list[str]:
    flags = set(re.findall(r"^flags\s*:\s*(.+)$", _read("/proc/cpuinfo"), re.M)[:1])
    have = set(" ".join(flags).split())
    interesting = ["avx", "avx2", "avx512f", "avx512vl", "fma", "sse4_2",
                   "neon", "asimd", "sve"]
    return [f for f in interesting if f in have]


def _compiler() -> str:
    for cc in ("c++", "g++", "clang++"):
        out = _cmd(cc, "--version")
        if out:
            return out.splitlines()[0].strip()
    return "unknown"


def _slurm() -> dict:
    keys = ("SLURM_JOB_ID", "SLURM_JOB_PARTITION", "SLURM_JOB_NODELIST",
            "SLURM_CPUS_ON_NODE", "SLURM_JOB_ACCOUNT")
    got = {k.lower(): os.environ[k] for k in keys if k in os.environ}
    return got


def fingerprint(label: str | None = None, kind: str = "unknown",
                runner: str = "native") -> dict:
    """Describe the machine well enough to group and defend results by it."""
    model = _cpu_model()
    logical = os.cpu_count() or 0
    physical = _physical_cores() or logical
    arch = platform.machine()
    osname = f"{platform.system()} {platform.release()}"

    # Stable across runs on the same machine; it is a hash of hardware and OS
    # family, never of a hostname, user or MAC address.
    ident = hashlib.sha256(
        "|".join([model, str(physical), str(logical), arch,
                  platform.system(), runner]).encode()
    ).hexdigest()[:12]

    dev = {
        "id": ident,
        "label": label or f"{model} ({physical}c/{logical}t)",
        "kind": kind,
        "runner": runner,
        "cpu": model,
        "cores_physical": physical,
        "cores_logical": logical,
        "arch": arch,
        "memory_gb": _memory_gb(),
        "os": osname,
        "isa": _isa_flags(),
        "compiler": _compiler(),
    }
    sl = _slurm()
    if sl:
        dev["slurm"] = sl
        if kind == "unknown":
            dev["kind"] = "hpc"
    return dev


# ------------------------------------------------------------------ run a set

def _discover(subs_dir: str) -> list[tuple[str, str]]:
    """(handle, path) for every immediate subdirectory holding a CMakeLists."""
    out = []
    for name in sorted(os.listdir(subs_dir)):
        p = os.path.join(subs_dir, name)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, "CMakeLists.txt")):
            out.append((name, p))
    return out


def run_device(task: Task, subs: list[tuple[str, str]], *, input_path: str,
               device: dict, quick: bool = False, tier: str = "device") -> dict:
    """Run every submission here and report each one's speedup over the baseline.

    The baseline is run first and is not optional. Without it the bundle has no
    scale of its own and its numbers cannot be compared to any other device's.
    """
    if quick:
        task.runs, task.warmup = 3, 1

    entries: list[dict] = []
    for handle, path in subs:
        t0 = time.time()
        rec = evaluate(path, task, input_path=input_path, which_input="public",
                       tier=tier, allow_unstable=True)
        entries.append({
            "handle": handle,
            "commit": rec.get("commit_short", ""),
            "status": rec["status"],
            "error": rec.get("error"),
            "checksum_ok": rec.get("checksum_ok", False),
            "per_sweep": {k: {"median_ms": v["median_ms"], "iqr_ms": v["iqr_ms"],
                              "peak_rss_mb": v["peak_rss_mb"]}
                          for k, v in rec.get("per_sweep", {}).items()},
            "peak_rss_mb": rec.get("metrics", {}).get("peak_rss_mb"),
            "cpu_efficiency": rec.get("metrics", {}).get("cpu_efficiency"),
            "elapsed_s": round(time.time() - t0, 1),
        })
        print(f"  {handle:<22} {rec['status']:<12} {rec.get('error','') or ''}"[:110],
              file=sys.stderr)

    base = next((e for e in entries if e["handle"] == BASELINE_HANDLE), None)
    if base is None or base["status"] != "ok":
        raise SystemExit(
            f"the '{BASELINE_HANDLE}' submission must be present and pass on this "
            f"device -- without it there is nothing to measure the others against")

    for e in entries:
        e["speedup_by_sweep"], ratios = {}, []
        if e["status"] != "ok":
            e["speedup"] = None
            continue
        for k, v in e["per_sweep"].items():
            b = base["per_sweep"].get(k, {}).get("median_ms")
            if b and v["median_ms"]:
                r = b / v["median_ms"]
                e["speedup_by_sweep"][k] = round(r, 4)
                ratios.append(r)
        e["speedup"] = round(geometric_mean(ratios), 4) if ratios else None

    return {
        "schema": SCHEMA,
        "task": task.id,
        "tier": tier,
        "input": os.path.basename(input_path),
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": task.runs,
        "warmup": task.warmup,
        "threads": task.threads,
        "device": device,
        "entries": entries,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="hpcbench-device",
        description="Run every submission on this device and emit one bundle.")
    ap.add_argument("--task", required=True)
    ap.add_argument("--submissions", required=True,
                    help="directory of submission directories, one per handle")
    ap.add_argument("--baseline", default=None,
                    help="the shipped baseline; copied in as 'baseline' if the "
                         "submissions directory does not already contain it")
    ap.add_argument("--input-path", required=True)
    ap.add_argument("--device-label", default=None)
    ap.add_argument("--device-kind", default="unknown",
                    choices=["laptop", "desktop", "workstation", "hpc",
                             "vm", "browser", "unknown"])
    ap.add_argument("--out", default="results/devices")
    ap.add_argument("--quick", action="store_true",
                    help="3 runs after 1 warmup instead of the task's settings")
    a = ap.parse_args(argv)

    task = Task.load(a.task)
    subs = _discover(a.submissions)
    handles = {h for h, _ in subs}
    if BASELINE_HANDLE not in handles:
        if not a.baseline:
            raise SystemExit("no 'baseline' in --submissions and no --baseline given")
        dst = os.path.join(a.submissions, BASELINE_HANDLE)
        shutil.copytree(a.baseline, dst, dirs_exist_ok=True)
        subs = _discover(a.submissions)
    # Baseline first: it is the scale everything else is reported against.
    subs.sort(key=lambda t: (t[0] != BASELINE_HANDLE, t[0]))

    dev = fingerprint(a.device_label, a.device_kind)
    print(f"device {dev['id']}  {dev['label']}", file=sys.stderr)
    print(f"  {dev['cpu']}  {dev['cores_physical']}c/{dev['cores_logical']}t  "
          f"{dev['memory_gb']} GB  {dev['os']}", file=sys.stderr)
    print(f"  isa: {', '.join(dev['isa']) or 'n/a'}", file=sys.stderr)
    print(f"running {len(subs)} submissions on {task.id}", file=sys.stderr)

    bundle = run_device(task, subs, input_path=os.path.abspath(a.input_path),
                        device=dev, quick=a.quick)

    stamp = bundle["measured_at"].replace(":", "").replace("-", "")
    out_dir = os.path.join(a.out, task.id, dev["id"])
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{stamp}.json")
    with open(out, "w") as f:
        json.dump(bundle, f, indent=2)

    print(f"\n  {'handle':<22}{'status':<12}{'speedup vs baseline here':>26}",
          file=sys.stderr)
    for e in bundle["entries"]:
        sp = f"{e['speedup']:.2f}x" if e.get("speedup") else "-"
        print(f"  {e['handle']:<22}{e['status']:<12}{sp:>26}", file=sys.stderr)
    print(f"\nwrote {out}", file=sys.stderr)
    print("Commit this file to the grader repo (or send it to your instructor) "
          "and it joins the cross-device board.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
