# hpcbench

A Kaggle-shaped submission and benchmarking platform for CIS 677.

Students push code. It is built in a pinned container, checked against a
canonical checksum, and profiled — first on cloud runners for two-minute
feedback, then on Clipper for the number that counts. Results land on a static
leaderboard.

---

## The design problem, and the answer

You asked that all code yield the same checksum. That requirement and "students
may vectorize and thread" are in direct tension, because floating-point addition
is not associative:

```
(a + b) + c   !=   a + (b + c)
```

An OpenMP reduction, an AVX-512 horizontal sum, and a scalar loop produce
**bit-different** results from identical inputs. Hashing raw IEEE-754 bytes
would fail every correct parallel submission — which would gut the course.

**hpcbench hashes a canonical form instead:** quantize to a declared number of
significant decimal digits, serialize deterministically, SHA-256. Two results
hash identically iff they agree to the declared precision.

This is verified, not asserted. `tests/test_canon.py` takes 5,000 random values,
sums them forward, backward, and pairwise — three bitwise-different answers —
and asserts one digest. It also asserts that a difference *at* the declared
precision still fails.

```
[PASS] test_reordering_is_invisible     forward/backward/pairwise -> one digest
[PASS] test_precision_boundary          9th digit differs -> caught
                                        12th digit differs -> ignored
```

Pick `sig_digits` per task from the numerics, not from taste:

| digits | survives | typical use |
|---|---|---|
| 12 | reordered fp64 sums, FMA contraction | well-conditioned fp64 |
| 9 | fp64 with mild cancellation | most dense linear algebra |
| 7 | fp32 accumulation | mixed-precision kernels |
| 5 | fp16/bf16 accumulation | ML forward passes |

Tasks with integer or index outputs (counts, permutations, sparsity patterns)
declare `exact: true` and get bit-exact hashing, which is the right requirement
there.

---

## Running it yourself, on any machine

Everyone runs everyone's code. See **[RUNNING.md](RUNNING.md)** for the local
and cluster instructions.

```bash
python3 -m hpcbench.device --task tasks/p1-kernel/task.yaml \
    --submissions submissions --input-path data/p1-kernel/public.bin \
    --device-label "my laptop" --device-kind laptop --out results/devices
```

A device never reports a rankable wall-clock time. It runs the shipped baseline
alongside every submission and reports each one's **speedup over the baseline
measured on that same machine**. Ratios survive the trip between a laptop, a
login node and a browser; milliseconds do not. The leaderboard combines those
ratios with a geometric mean over the devices the instructor has marked as
scoring in `scoring/devices.json`; every other device still appears on the plot,
marked "not scored".

---

## Two tiers

Identical evaluation code, different hardware.

| | **cloud** | **hpc** |
|---|---|---|
| Runs on | GitHub-hosted runners | Clipper `class` partition |
| Trigger | every push | nightly, instructor-owned |
| Latency | ~2 minutes | overnight |
| Purpose | correctness + provisional timing | **the official score** |
| Hardware counters | no (`perf` is restricted) | yes |
| Cost | free | your existing allocation |
| Authoritative | no | yes |

The two tiers are never compared to each other, and the leaderboard says so on
the page. Within a tier they are comparable, because the toolchain is a pinned
Apptainer image and the node is constrained.

**Why the official run is instructor-side.** If a student's own run produced the
official number, a determined student could forge the JSON, and you would be in
the business of detecting that. Making their run *practice* and the nightly
re-run of their committed code *authoritative* means forgery buys nothing. It
costs one cron job and removes an entire category of problem.

---

## Architecture

```
  student repo (one per student, from template)
        │  push
        ▼
  GitHub Actions ──► build in container ──► oracle ──► provisional timing
        │                                                    │
        │                                          2-min feedback, no cluster
        │
        │            ┌─────────── nightly, 02:00 ───────────┐
        ▼            │                                       │
  grader repo ◄──────┤  poll.sh on Clipper (course account) │
   (private)         │    • git fetch every student repo     │
        │            │    • sbatch one scoring job each      │
        │            │    • --constraint pinned, --exclusive │
        │            │    • run inside hpcbench.sif          │
        │            │  collect.sh commits results back      │
        │            └───────────────────────────────────────┘
        │  push to results/
        ▼
  GitHub Pages ──► leaderboard (handles only)
```

Nothing ever connects *in* to Clipper. The cluster reaches out over HTTPS to
github.com and nothing else. No self-hosted runner, no daemon, no long-lived
cluster credential in GitHub, no MFA problem.

---

## What gets measured

Every submission record carries:

- **runtime** — median, IQR, min, max, stdev over 7 runs after 2 warmups
- **memory** — peak RSS
- **CPU efficiency** — `(user + sys) / (wall × threads)`; catches a submission
  that requested four cores and used one
- **hardware counters** (HPC tier) — IPC, cache-miss rate, branch-miss rate
- **host fingerprint** — CPU model, core count, AVX-512 presence, Slurm job id,
  node name

**A noisy run is not a result.** Any submission whose IQR exceeds 10% of its
median is rejected rather than scored. That guard is not decoration — it fired
correctly during development on a contended 2-vCPU container.

---

## Anti-gaming

| Attack | Defence |
|---|---|
| Hardcode the expected output | Grade on a **held-out input** of the same distribution, released after the deadline |
| Ship an easier `data/` in your repo | The grader supplies the input by absolute path; a submission's own `data/` is ignored |
| Forge the result JSON | Student runs are practice; the nightly instructor-account re-run is authoritative |
| Return early / emit garbage | Digest covers shape, element count, and every value; non-finite values are rejected outright |
| Win by getting a fast node | `--constraint` pins the node type; `--exclusive` keeps neighbours out |
| Win by getting a quiet minute | Median of 7, IQR reported, unstable runs rejected |

None of these require accusing anyone of anything. A held-out input simply
produces a different number.

---

## Repository layout

```
hpcbench/
  hpcbench/
    canon.py         canonical quantized hashing  ← the core idea
    measure.py       timing, memory, perf counters
    task.py          task spec + threshold scoring
    run.py           evaluate one submission (both tiers use this)
    reference.py     generate a task's digests and baseline
    leaderboard.py   static site generator
    index.py         landing page
  harness/
    canon.hpp        C++ result writer (students include this)
  tasks/<id>/task.yaml
  data/<id>/{public,holdout}.bin      ← never in a student repo
  results/<id>/*.json
  clipper/
    poll.sh          pull-model cron on the login node
    score.sbatch     one scoring job
    collect.sh       push results back to GitHub
  .github/workflows/
    submit.yml       student-side (copy into the template repo)
    publish.yml      instructor-side leaderboard build
  hpcbench.def       pinned Apptainer image
  tests/
```

---

## Scoring

Threshold-plus-curve, not rank. Full benchmark credit at a stated speedup over
the shipped baseline — everyone in the room can earn all 25 points, and the
leaderboard supplies pull rather than the floor.

```python
full credit          speedup >= full_credit_at
linear               1.0 < speedup < full_credit_at
floor (20%)          speedup <= 1.0
zero                 checksum mismatch
not scored           IQR > 10% of median
```

This matches the course rubric, where 75 of 100 project points are for
understanding and 25 are for the number.

---

## Quick start

```bash
# 1. define a task
$EDITOR tasks/p3-spmm/task.yaml

# 2. generate reference digests and the baseline timing
python3 -m hpcbench.reference \
    --task tasks/p3-spmm/task.yaml \
    --reference reference-impl/ \
    --data-dir data/p3-spmm/

# 3. evaluate a submission
python3 -m hpcbench.run \
    --task tasks/p3-spmm/task.yaml \
    --submission /path/to/student/repo \
    --input-path data/p3-spmm/public.bin \
    --handle bitshift --tier cloud \
    --out results/p3-spmm/bitshift.json

# 4. rebuild the leaderboard
python3 -m hpcbench.leaderboard \
    --task tasks/p3-spmm/task.yaml \
    --results results --out site/p3-spmm.html
```

Zero dependencies outside the Python standard library, deliberately — it has to
run on whatever the cluster has after the next migration.

See `DEPLOY.md` for the full setup, including what to ask ARC for.
