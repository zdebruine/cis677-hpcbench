"""Task definition and scoring."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
import math
from typing import Optional

from .canon import CanonSpec

# YAML is nicer to author but adds a dependency the cluster may not have.
# Tasks are therefore JSON with a .yaml-ish name; if PyYAML is importable we
# accept YAML too.
try:  # pragma: no cover
    import yaml  # type: ignore
    _HAVE_YAML = True
except ImportError:  # pragma: no cover
    _HAVE_YAML = False


@dataclass
class Metric:
    """One thing the leaderboard ranks on."""

    key: str                      # "median_ms", "peak_rss_mb", "cpu_efficiency"
    label: str
    direction: str = "min"        # "min" or "max"
    unit: str = ""
    primary: bool = False
    # Only used for the scored metric:
    baseline: Optional[float] = None      # measured baseline value
    full_credit_at: Optional[float] = None  # speedup (min) or absolute (max)
    # For a swept task: {"8": 412.0, "16": 430.1, ...}
    baseline_by_sweep: dict = field(default_factory=dict)


@dataclass
class Task:
    id: str
    title: str
    canon: CanonSpec
    metrics: list[Metric]
    build: list[str] = field(default_factory=lambda: [
        "cmake -B build -DCMAKE_BUILD_TYPE=Release",
        "cmake --build build -j",
    ])
    # Two-phase execution.
    #   prepare  -- UNTIMED. Reads the raw corpus, writes whatever on-disk
    #               representation the student chose, into a scratch workdir.
    #   solution -- TIMED end to end: load that representation, compute,
    #               write the result. Checksumming is done by the harness
    #               afterwards and is therefore never on the clock.
    prepare: list[str] = field(default_factory=list)
    entrypoint: list[str] = field(default_factory=lambda: ["./build/solution"])
    result_file: str = "result.bin"
    workdir: str = "work"
    # Sweep one argument across values; every value must produce a correct
    # result, and the score is the geometric mean of the per-value speedups.
    # This is what stops a kernel being tuned to one operand width.
    sweep_arg: str = ""
    sweep_values: list = field(default_factory=list)
    # Hard sanity ceiling. A run slower than this is cancelled, not scored --
    # it protects the queue from a submission that would never finish.
    sanity_timeout_s: int = 0
    threads: int = 4
    mem_limit_mb: int = 32768
    timeout_s: int = 900
    runs: int = 7
    warmup: int = 2
    public_input: str = "data/public.bin"
    holdout_input: str = "data/holdout.bin"
    reference_digest: dict = field(default_factory=dict)  # input name -> digest
    notes: str = ""

    @property
    def primary_metric(self) -> Metric:
        for m in self.metrics:
            if m.primary:
                return m
        return self.metrics[0]

    @classmethod
    def load(cls, path: str) -> "Task":
        with open(path) as f:
            text = f.read()
        if _HAVE_YAML and not text.lstrip().startswith("{"):
            raw = yaml.safe_load(text)
        else:
            raw = json.loads(text)
        c = raw.get("canon", {})
        return cls(
            id=raw["id"],
            title=raw["title"],
            canon=CanonSpec(
                sig_digits=c.get("sig_digits", 9),
                exact=c.get("exact", False),
            ),
            metrics=[Metric(**m) for m in raw["metrics"]],
            build=raw.get("build", [
                "cmake -B build -DCMAKE_BUILD_TYPE=Release",
                "cmake --build build -j",
            ]),
            prepare=raw.get("prepare", []),
            entrypoint=raw.get("entrypoint", ["./build/solution"]),
            result_file=raw.get("result_file", "result.bin"),
            workdir=raw.get("workdir", "work"),
            sweep_arg=raw.get("sweep_arg", ""),
            sweep_values=raw.get("sweep_values", []),
            sanity_timeout_s=raw.get("sanity_timeout_s", 0),
            threads=raw.get("threads", 4),
            mem_limit_mb=raw.get("mem_limit_mb", 32768),
            timeout_s=raw.get("timeout_s", 900),
            runs=raw.get("runs", 7),
            warmup=raw.get("warmup", 2),
            public_input=raw.get("public_input", "data/public.bin"),
            holdout_input=raw.get("holdout_input", "data/holdout.bin"),
            reference_digest=raw.get("reference_digest", {}),
            notes=raw.get("notes", ""),
        )


def score_benchmark(value: float, metric: Metric, points: float = 25.0) -> float:
    """Threshold-plus-curve scoring. Everyone can earn full marks.

    For a "min" metric (time, memory): full credit at
    `full_credit_at` times better than baseline. Below baseline earns a floor.

    For a "max" metric (utilization, throughput): full credit at the
    absolute value in `full_credit_at`.
    """
    if metric.baseline is None or metric.full_credit_at is None:
        return points  # unscored metric — reported, not graded

    floor = points * 0.20

    if metric.direction == "min":
        if value <= 0:
            return 0.0
        speedup = metric.baseline / value
        target = metric.full_credit_at
        if speedup >= target:
            return points
        if speedup <= 1.0:
            return floor
        return floor + (points - floor) * (speedup - 1.0) / (target - 1.0)

    # direction == "max"
    target = metric.full_credit_at
    if value >= target:
        return points
    if value <= metric.baseline:
        return floor
    return floor + (points - floor) * (value - metric.baseline) / (target - metric.baseline)


def geometric_mean(xs: list) -> float:
    """Right average for a set of ratios measured at different scales.

    An arithmetic mean of speedups lets one enormous win at a single operand
    width paper over five mediocre ones; a geometric mean does not. That is
    exactly the behaviour a swept task is trying to produce.
    """
    xs = [x for x in xs if x and x > 0]
    if not xs:
        return 0.0
    return math.exp(sum(math.log(x) for x in xs) / len(xs))
