# Deploying hpcbench

Roughly a day of work, most of it waiting on ARC. Order matters: step 1 blocks
the leaderboard, so file it first.

---

## 0 · What to ask ARC for (do this today)

Open an ARC Help ticket. Everything else can proceed in parallel, but **item 1
is the genuine blocker** — without it the leaderboard ranks luck rather than
skill, because the `class` partition spans 48-, 40-, 52- and 64-core hosts.

> **Subject: CIS 677 (Fall 2026) — class partition and scoring node**
>
> 1. **A `--constraint` feature tag** (e.g. `cis677score`) applied to one or two
>    homogeneous `class`-partition nodes, so that student submissions can be
>    timed against each other. Ideally these also accept `--exclusive` for
>    scoring runs, since a neighbouring job corrupts timing.
> 2. **The `--account` value** the course should use, under the mandatory-account
>    rule introduced in the 2026.08 release.
> 3. **A shared read-only project directory**, ~200 GB, for datasets. The 50 GB
>    home quota makes per-student copies impossible for 9 students.
> 4. **A course service account** able to run a cron job on the login node that
>    makes *outbound* HTTPS requests to github.com, clones repositories into
>    `/mnt/projects`, and submits `sbatch` jobs. No inbound connectivity and no
>    daemon are required.
> 5. **Confirmation of the `class` partition time limit** (not documented in the
>    KB), and whether the 4-core / 32 GB per-job cap can be raised for two
>    projects late in the term.
> 6. **Post-migration verification**: the 2026.08 move to Ubuntu 24.04 broke
>    existing Python and Conda environments and moved CUDA to 13.3. Which
>    `gcc`, `cmake` and `python` modules should a course container target?

If (4) is refused, everything still works — you run `poll.sh` by hand on a
laptop with cluster access, or fall back to cloud-tier scoring only.

---

## 1 · GitHub setup

Create an organization, e.g. `gvsu-cis677`. Free for public repos; private
repos on the free tier are fine at this scale.

**Grader repo** — `gvsu-cis677/grader`, **private**. Holds this package,
`tasks/`, `data/` (both inputs), `results/`, and the roster. Enable Pages from
GitHub Actions.

**Template repo** — `gvsu-cis677/project-template`, marked *Template*. Contains
the student-facing scaffold plus the workflow from
`templates/project-repo/.github/workflows/submit.yml`. One fork per student per
project. That workflow deliberately does **not** live under the grader repo's
own `.github/workflows/`: GitHub runs everything it finds there, and the student
workflow fails immediately without a `GRADER_TOKEN` secret.

**Roster** — `roster.tsv` in the grader repo, tab-separated. This file is the
only place handles map to repos; the name mapping stays off GitHub entirely.

```
# handle        repo_url
bitshift        https://github.com/gvsu-cis677/p3-bitshift
cachelinehero   https://github.com/gvsu-cis677/p3-cachelinehero
```

**Tokens.** One fine-grained PAT with *read* on student repos and *write* on the
grader repo. Store it in the grader repo as `GRADER_TOKEN`, and on Clipper in
`~/.hpcbench.env` with `chmod 600`. Set repo variables `HANDLE`, `TASK_ID`, and
`GRADER_REPO` on each student repo.

> **FERPA.** The leaderboard shows handles only. A public ranking of students by
> performance with names attached is an education-record disclosure. Students
> pick a handle in Week 1; you hold the mapping; the Pages site stays private to
> the org. Get this right on day one rather than after someone asks.

---

## 1b · Publishing the leaderboard on GitHub Pages

The site is plain static HTML with no build step and no dependencies outside the
Python standard library. Build it exactly the way CI does:

```bash
./tools/build_site.sh          # writes _site/
python3 -m http.server -d _site 8000
```

That produces, per task, an authoritative HPC page at `<id>.html` and a
provisional cloud page at `<id>-cloud.html`, plus `index.html`, a `404.html`
and a `.nojekyll`. Every link is relative, so it works unchanged at a project
path like `https://gvsu-cis677.github.io/grader/`.

In the grader repo: **Settings → Pages → Source: GitHub Actions**. That is the
only click required; `.github/workflows/publish.yml` does the rest on every
push to `results/`, `tasks/` or `hpcbench/`, on a 07:00 ET schedule, and on
demand.

> **Read this before you enable it.** Pages built from a **private** repo is
> served **publicly** unless the org is on GitHub Enterprise Cloud. On a free or
> Team org, turning Pages on publishes the leaderboard to the open web. That is
> survivable here *only* because the page carries handles and never names — it
> is why the FERPA rule in §1 is a design constraint and not a preference. The
> handle-to-name mapping stays off GitHub entirely. Pages are also served with
> `noindex,nofollow`, which keeps them out of search results but does not make
> them private.
>
> If you would rather nothing be public, drop the `deploy` job and read the
> `_site` artifact off the Actions run, or run `./tools/build_site.sh` locally
> and put it behind Blackboard.

**Before the first Clipper run there are no HPC-tier results.** The HPC page
still renders: it falls back to the cloud tier and says so in a banner, so the
authoritative URL never quietly serves provisional numbers as if they were the
official score.

---

## 2 · Build the container

```bash
sudo apptainer build hpcbench.sif hpcbench.def
scp hpcbench.sif clipper.gvsu.edu:/mnt/projects/cis677/hpcbench/
```

**Build it once and do not rebuild during the term.** A compiler upgrade
mid-semester silently changes every timing on the leaderboard, and students
would rightly conclude the numbers are meaningless.

---

## 3 · Define a task

`tasks/<id>/task.yaml`. The fields that matter:

| Field | What it controls |
|---|---|
| `canon.sig_digits` | How much floating-point reordering is forgiven. See the table in README. |
| `canon.exact` | Bit-exact hashing, for integer/index outputs |
| `threads`, `mem_limit_mb` | Enforced on the child process |
| `metrics[].primary` | Which metric is scored; the rest are reported |
| `full_credit_at` | Speedup over baseline for full marks |

Then generate the reference:

```bash
python3 -m hpcbench.reference \
    --task tasks/p3-spmm/task.yaml \
    --reference reference-impl/ \
    --data-dir data/p3-spmm/
```

This writes `reference_digest` for both inputs and pins `baseline` to the
measured reference time. **Re-run it on the scoring node**, not your laptop —
the baseline must come from the same hardware the students are measured on.

### Generating the held-out input

Same generator, same distribution, different seed. Keep it out of any
student-visible repo until the deadline.

```python
gen("data/p3-spmm/public.bin",  seed=677)
gen("data/p3-spmm/holdout.bin", seed=1729)
```

---

## 4 · Wire up Clipper

```bash
ssh clipper.gvsu.edu
mkdir -p /mnt/projects/cis677/{hpcbench,scoring}
cat > ~/.hpcbench.env <<'EOF'
export GITHUB_TOKEN=github_pat_...
export GRADER_REPO=gvsu-cis677/grader
export ROSTER=/mnt/projects/cis677/hpcbench/roster.tsv
EOF
chmod 600 ~/.hpcbench.env

crontab -e
# nightly scoring on the public input, then publish
0 2 * * *  /mnt/projects/cis677/hpcbench/clipper/poll.sh p3-spmm public >> ~/hpcbench.log 2>&1
0 5 * * *  /mnt/projects/cis677/hpcbench/clipper/collect.sh          >> ~/hpcbench.log 2>&1
```

After a deadline, score the held-out input once:

```bash
./clipper/poll.sh p3-spmm holdout && sleep 1800 && ./clipper/collect.sh
```

`poll.sh` skips any `(handle, commit, input)` triple it has already scored, so
it is safe to run repeatedly.

---

## 5 · Verify before the students arrive

```bash
python3 tests/test_canon.py          # 6 tests; the reordering one is the important one
python3 -m hpcbench.run --task tasks/p3-spmm/task.yaml \
    --submission examples/naive-submission \
    --input-path data/p3-spmm/public.bin --handle smoke --out /tmp/smoke.json
```

Then deliberately break things and confirm each is caught:

| Break it | Expect |
|---|---|
| Change one output value by 1% | `wrong_answer` |
| Return an array of the wrong length | `wrong_answer` (length is in the digest) |
| Emit a NaN | `nonfinite` |
| Delete the result write | `no_result` |
| Infinite loop | `timeout` |
| Allocate 40 GB | `run_failed` (RLIMIT_AS) |
| Reorder a parallel sum | **`ok`** — this is the one that must pass |

That last row is the whole design. Test it explicitly.

---

## 6 · Running it during the term

**Weekly.** Nothing. The cron job runs; Pages rebuilds; you look at the
leaderboard in class.

**Per project.** Write `task.yaml`, generate the data, run `reference.py` on the
scoring node, create nine forks from the template, add nine rows to
`roster.tsv`. About an hour.

**After each deadline.** One `poll.sh ... holdout` run. The held-out scores are
what go in the gradebook.

---

## Failure modes worth knowing

**Everyone's IQR is above 10%.** The scoring node is contended. Get
`--exclusive` honoured, or raise `UNSTABLE_IQR_FRAC` in `measure.py` and say so
publicly — do not quietly score noisy runs.

**A submission passes on cloud and fails on Clipper.** Almost always
`-march=native` producing different FMA contraction on a different microarch.
If it recurs, drop `sig_digits` by one or two for that task; that is what the
knob is for.

**`perf` returns nothing.** `perf_event_paranoid` is restricted. Counters are
best-effort by design — their absence is never a failure, it just means those
columns are empty on that tier.

**A student's repo will not clone.** `poll.sh` logs and continues. Check the
token's repository access list.

**The container drifts from Clipper's modules.** Everything runs inside
`hpcbench.sif`, so the host modules only need to provide `apptainer` itself.
That is the point of the container.

---

## Cost

Zero. GitHub Actions is free for public repos and generous on private ones at
this scale; Pages is free; Clipper is your existing allocation. Nothing here
requires a cloud account, a credit card, or a service you do not already have.
