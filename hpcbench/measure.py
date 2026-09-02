"""
Measurement: runtime, memory, and hardware counters for one submission.

Everything here is deliberately conservative. A number this module reports
should be one a student can defend in front of the room, which means we
report spread alongside central tendency and we refuse to report at all when
the run was too noisy to mean anything.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

# A run whose IQR exceeds this fraction of its median is rejected.
UNSTABLE_IQR_FRAC = 0.10


@dataclass
class RunResult:
    """One execution of the submission binary."""

    wall_ms: float
    user_ms: float
    sys_ms: float
    max_rss_kb: int
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class Measurement:
    """Aggregated result across repetitions."""

    ok: bool
    runs: int
    median_ms: float = 0.0
    iqr_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0
    stdev_ms: float = 0.0
    peak_rss_mb: float = 0.0
    cpu_efficiency: float = 0.0  # (user+sys) / (wall * threads)
    unstable: bool = False
    counters: dict = field(default_factory=dict)
    samples_ms: list = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _quantiles(xs: list[float]) -> tuple[float, float, float]:
    s = sorted(xs)

    def q(p: float) -> float:
        if len(s) == 1:
            return s[0]
        x = p * (len(s) - 1)
        i = int(x)
        f = x - i
        return s[i] * (1 - f) + s[i + 1] * f if i + 1 < len(s) else s[i]

    return q(0.25), q(0.50), q(0.75)


def run_once(cmd: list[str], cwd: str, env: dict, timeout: int) -> RunResult:
    """Execute once, capturing wall time and the peak RSS of *this* child.

    getrusage(RUSAGE_CHILDREN).ru_maxrss is a high-water mark over every child
    the calling process has ever reaped, and it never falls. Reading it after a
    run therefore reports the largest child so far, not the one just measured --
    so an untimed `prepare` step that materialises the dense corpus pins
    peak_rss for every subsequent solution run, and a submission that cuts its
    memory tenfold sees the number refuse to move. Memory is a metric students
    are asked to improve and defend, so it has to be theirs alone.

    os.wait4() returns the rusage of one specific child, which is what we want.
    Popen is used only to spawn; the wait is ours, and proc.returncode is set by
    hand afterwards so Popen does not try to reap an already-reaped pid.
    """
    with tempfile.TemporaryFile(mode="w+") as fo, tempfile.TemporaryFile(mode="w+") as fe:
        t0 = time.perf_counter()
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=fo, stderr=fe)
        except Exception as e:
            return RunResult(wall_ms=0.0, user_ms=0, sys_ms=0, max_rss_kb=0,
                             exit_code=127, stderr=f"could not launch: {e}")

        timed_out = threading.Event()

        def _kill():
            timed_out.set()
            try:
                proc.kill()
            except Exception:
                pass

        killer = threading.Timer(timeout, _kill)
        killer.start()
        try:
            _, status, ru = os.wait4(proc.pid, 0)
        finally:
            killer.cancel()
        wall_ms = (time.perf_counter() - t0) * 1000.0

        # Mark the child reaped so Popen's destructor does not wait on it again.
        code = os.waitstatus_to_exitcode(status) if not timed_out.is_set() else 124
        proc.returncode = code

        if timed_out.is_set():
            return RunResult(wall_ms=timeout * 1000.0, user_ms=0, sys_ms=0,
                             max_rss_kb=0, exit_code=124,
                             stderr=f"timed out after {timeout}s")

        fo.seek(0); fe.seek(0)
        return RunResult(
            wall_ms=wall_ms,
            user_ms=ru.ru_utime * 1000.0,
            sys_ms=ru.ru_stime * 1000.0,
            max_rss_kb=ru.ru_maxrss,
            exit_code=code, stdout=fo.read()[-8000:], stderr=fe.read()[-8000:],
        )


PERF_EVENTS = [
    "cycles", "instructions",
    "cache-references", "cache-misses",
    "branches", "branch-misses",
]


def perf_available() -> bool:
    if shutil.which("perf") is None:
        return False
    try:
        r = subprocess.run(
            ["perf", "stat", "-e", "cycles", "--", "true"],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def collect_counters(cmd: list[str], cwd: str, env: dict, timeout: int) -> dict:
    """One `perf stat` pass. Best effort — absence is never a failure.

    perf is usually unavailable on cloud runners (needs perf_event_paranoid
    relaxed) and usually available on the cluster. Counters therefore appear
    on HPC-tier results and not on cloud-tier ones, which is documented rather
    than papered over.
    """
    if not perf_available():
        return {}
    try:
        r = subprocess.run(
            ["perf", "stat", "-x,", "-e", ",".join(PERF_EVENTS), "--"] + cmd,
            cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
        )
    except Exception as e:
        return {"_error": str(e)}

    out: dict = {}
    for line in r.stderr.splitlines():
        parts = line.split(",")
        if len(parts) < 3:
            continue
        raw, _unit, event = parts[0], parts[1], parts[2]
        if not raw or raw.startswith("<"):
            continue
        try:
            out[event.strip()] = float(raw)
        except ValueError:
            continue

    if "instructions" in out and out.get("cycles"):
        out["ipc"] = out["instructions"] / out["cycles"]
    if "cache-misses" in out and out.get("cache-references"):
        out["cache_miss_rate"] = out["cache-misses"] / out["cache-references"]
    if "branch-misses" in out and out.get("branches"):
        out["branch_miss_rate"] = out["branch-misses"] / out["branches"]
    return out


def measure(
    cmd: list[str],
    cwd: str,
    *,
    runs: int = 7,
    warmup: int = 2,
    timeout: int = 900,
    threads: int = 1,
    env: Optional[dict] = None,
    with_counters: bool = True,
) -> Measurement:
    """Warm up, repeat, summarize, and refuse to report an unstable result."""
    e = dict(os.environ if env is None else env)
    e.setdefault("OMP_NUM_THREADS", str(threads))
    e.setdefault("OMP_PROC_BIND", "close")
    e.setdefault("OMP_PLACES", "cores")
    e.setdefault("MKL_NUM_THREADS", str(threads))
    e.setdefault("OPENBLAS_NUM_THREADS", str(threads))

    for _ in range(warmup):
        r = run_once(cmd, cwd, e, timeout)
        if r.exit_code != 0:
            return Measurement(
                ok=False, runs=0,
                error=f"warmup failed (exit {r.exit_code}): {r.stderr[-2000:]}",
            )

    samples: list[float] = []
    cpu_effs: list[float] = []
    peak_rss_kb = 0
    for _ in range(runs):
        r = run_once(cmd, cwd, e, timeout)
        if r.exit_code != 0:
            return Measurement(
                ok=False, runs=len(samples),
                error=f"run failed (exit {r.exit_code}): {r.stderr[-2000:]}",
            )
        samples.append(r.wall_ms)
        peak_rss_kb = max(peak_rss_kb, r.max_rss_kb)
        if r.wall_ms > 0 and threads > 0:
            cpu_effs.append((r.user_ms + r.sys_ms) / (r.wall_ms * threads))

    q1, med, q3 = _quantiles(samples)
    iqr = q3 - q1
    cpu_eff = statistics.median(cpu_effs) if cpu_effs else 0.0

    m = Measurement(
        ok=True,
        runs=runs,
        median_ms=med,
        iqr_ms=iqr,
        min_ms=min(samples),
        max_ms=max(samples),
        mean_ms=statistics.fmean(samples),
        stdev_ms=statistics.stdev(samples) if len(samples) > 1 else 0.0,
        peak_rss_mb=peak_rss_kb / 1024.0,
        cpu_efficiency=round(cpu_eff, 4),
        unstable=iqr > UNSTABLE_IQR_FRAC * med if med > 0 else True,
        samples_ms=[round(s, 3) for s in samples],
    )
    if with_counters:
        m.counters = collect_counters(cmd, cwd, e, timeout)
    return m


def host_fingerprint() -> dict:
    """Everything needed to decide whether two results are comparable."""
    info: dict = {
        "hostname": os.uname().nodename,
        "kernel": os.uname().release,
        "machine": os.uname().machine,
        "cpu_count": os.cpu_count(),
    }
    try:
        with open("/proc/cpuinfo") as f:
            txt = f.read()
        m = re.search(r"model name\s*:\s*(.+)", txt)
        if m:
            info["cpu_model"] = m.group(1).strip()
        info["cpu_flags_avx512"] = "avx512f" in txt
    except OSError:
        pass
    try:
        with open("/proc/meminfo") as f:
            m = re.search(r"MemTotal:\s+(\d+) kB", f.read())
        if m:
            info["mem_total_gb"] = round(int(m.group(1)) / 1048576, 1)
    except OSError:
        pass
    for var in ("SLURM_JOB_ID", "SLURM_JOB_PARTITION", "SLURM_JOB_NODELIST",
                "GITHUB_RUN_ID", "HPCBENCH_TIER"):
        if os.environ.get(var):
            info[var.lower()] = os.environ[var]
    return info
