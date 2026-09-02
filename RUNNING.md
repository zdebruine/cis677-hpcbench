# Running the benchmark on your own machine

Everyone runs everyone's code. That is the point: a wall-clock time from a
laptop and one from a login node are not comparable, but **the ratio between two
submissions measured on the same machine is**. So every device runs the shipped
baseline alongside every submission and reports each one's speedup over *that
machine's* baseline. Those ratios are what the leaderboard combines.

You need Python 3.9+, CMake, and a C++17 compiler. Nothing else — hpcbench has
no dependencies outside the Python standard library.

---

## 1 · Get the code and the data

```bash
git clone https://github.com/zdebruine/cis677-hpcbench.git
cd cis677-hpcbench

# The raw 296 MB matrix is not in git; rebuild it from the packed matrix (4 MB).
python3 tools/make_p1_input.py --variant public --out data/p1-kernel/public.bin
```

## 2 · Collect the submissions

One directory per handle, each containing a `CMakeLists.txt`, `src/prepare.cpp`
and `src/solution.cpp`. The shipped baseline must be among them under the name
`baseline` — the runner refuses to produce a bundle without it, because without
it the numbers have no scale.

```bash
mkdir -p submissions
cp -r baselines/p1-kernel submissions/baseline
git clone https://github.com/gvsu-cis677/p1-bitshift submissions/bitshift
git clone https://github.com/gvsu-cis677/p1-nullptr  submissions/nullptr
```

## 3 · Run

```bash
python3 -m hpcbench.device \
    --task tasks/p1-kernel/task.yaml \
    --submissions submissions \
    --input-path data/p1-kernel/public.bin \
    --device-label "ThinkPad X1 / i7-1365U" \
    --device-kind laptop \
    --out results/devices
```

Add `--quick` for 3 runs after 1 warmup instead of the task's 7-after-2 while
you are still setting things up. Do not report a `--quick` bundle as a result.

It prints a fingerprint of the machine, runs everything, and writes
`results/devices/<task>/<device-id>/<timestamp>.json`.

## 4 · Send it back

```bash
git add results/devices && git commit -m "device run: ThinkPad X1" && git push
```

Open a pull request if you do not have write access. The leaderboard rebuilds on
push and your device appears on the "Across devices" plot.

---

## On a cluster (Slurm)

Two things differ on a shared machine: you must ask for the resources, and you
must not measure on a node someone else is also using.

```bash
sbatch clipper/run_all.sbatch p1-kernel
```

That script is in this repo. The parts that matter:

```bash
#SBATCH --exclusive              # a neighbouring job corrupts every timing
#SBATCH --constraint=cis677score # pin the node type, or you rank hardware
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
```

`--exclusive` is not optional if you intend the numbers to mean anything. A
run that shared a node with someone else's job is a measurement of the
scheduler, not of the code. The runner records `SLURM_JOB_ID`, the partition and
the node list in the bundle so a suspicious result can be traced back.

Interactively instead of batch:

```bash
salloc --partition=class --cpus-per-task=4 --mem=32G --exclusive --time=1:00:00
module load gcc cmake python
python3 -m hpcbench.device --task tasks/p1-kernel/task.yaml \
    --submissions submissions --input-path data/p1-kernel/public.bin \
    --device-kind hpc --out results/devices
```

`--device-kind hpc` is inferred automatically when Slurm variables are present.

---

## What gets recorded about your machine

The bundle describes the hardware, not you: CPU model, physical and logical core
counts, architecture, RAM, OS and kernel, the ISA extensions the CPU advertises
(AVX2, AVX-512, NEON…), and the compiler version. The device id is a hash of
those, so the same machine is recognised across runs. No hostname, username, MAC
address or IP is collected.

Give your device a `--device-label` you are happy to see in public — it appears
on the site.

---

## Which runs count

Appearing on the plot and counting toward the score are different things. Every
bundle shows up; only devices listed in `scoring/devices.json` enter the
combined figure. That allowlist is the instructor's.

The reason is not gatekeeping. A laptop that thermally throttles halfway through,
a login node running someone's build, a VM whose neighbour woke up — those are
real data about those machines and useless as a grade. Runs from them stay
visible, marked "not scored", which is more useful than deleting them: a
submission whose speedup collapses on one machine is telling you something.

---

## Reading the result

```
  handle                status        speedup vs baseline here
  baseline              ok                               1.00x
  nullptr               ok                               1.54x
  bitshift              ok                              11.68x
  cachelinehero         ok                              17.41x
```

`baseline` is 1.00× by construction — it is the denominator. If it is not
approximately 1.00 on a re-run, your machine is not measuring stably and nothing
else in the bundle should be believed either.
