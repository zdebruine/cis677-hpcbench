# CIS 677 task definitions

Five tasks. Every one ships a working, deliberately naive C++ baseline split
into two binaries, and that split is the design:

| | timed? | what it does |
|---|---|---|
| `prepare <raw> <work>` | **no** | Reads the raw corpus once and writes whatever on-disk representation you chose. Sort, compress, quantize, shard, index — none of it is on the clock. |
| `solution <work> <result> [k]` | **yes** | Loads your representation, computes, writes the result. Process wall clock, start to finish. |
| checksum | **no** | The harness digests `result.bin` afterwards. |

That structure is what makes "students may choose their own data representation"
enforceable rather than a promise. It also makes the format decision the first
real optimization in the course.

---

## Status

| Task | Baseline | Reference generated | Notes |
|---|---|---|---|
| `p1-kernel` | builds, tested | ✅ on dev corpus | Swept over k = 8,16,32,64,128,256 |
| `p2-epoch`  | builds, tested | ✅ on dev corpus | |
| `p3-loader` | builds, tested | ✅ on dev corpus | 16 GB cap, mandated shuffle order |
| `p4-device` | builds (CPU path) | ⏳ **needs an H100** | CUDA is optional at configure time |
| `p5-atlas`  | builds | ⏳ **needs the cluster** | |

**Regenerate every reference on the scoring node before the term.** The digests
currently in `tasks/*/task.yaml` were produced on a development container
against small synthetic corpora. Baselines especially must be re-measured on
the hardware students are scored on — a baseline from the wrong machine makes
every speedup meaningless.

```bash
for t in p1-kernel p2-epoch p3-loader p4-device p5-atlas; do
  python3 -m hpcbench.reference --task tasks/$t/task.yaml \
      --reference baselines/$t --data-dir data/$t
done
```

---

## P1 · The Kernel

`Y = X·W`. X is pbmc3k counts handed over dense at 6.2% occupancy.

- **Swept over k = 8, 16, 32, 64, 128, 256.** Every value must be correct, and
  the score is the **geometric mean** of the six speedups. A kernel tuned to one
  operand width wins nothing; an arithmetic mean would have let one enormous win
  at a single k paper over five mediocre ones.
- `W` is generated deterministically from `k` inside the solution, so every
  submission multiplies by identical weights. `gen_W` must not change.
- Sanity ceiling 120 s per k. Full credit at **8× geometric mean**.
- Canon: 9 significant digits. Verified: a CSR + OpenMP rewrite with a
  completely different accumulation order hashes identically to the dense
  reference, and scores 11.1×.

## P2 · The Epoch

genes → 256 → 32 → 256 → genes. ReLU, Adam, MSE, one epoch, fixed batch order.

- The result digested is the **latent embedding of every cell** after the epoch
  (n × 32) — a fingerprint of the entire training trajectory, so a wrong
  gradient anywhere shows up.
- Architecture, hyperparameters, initialization and batch order are fixed.
- Canon: **6 significant digits**, chosen empirically. A blocked 4-way
  reduction — a realistic vectorization rewrite — drifts 9e-12 relative after a
  full epoch of Adam, i.e. 11 digits of agreement. Six leaves five digits of
  margin while still failing anything meaningfully wrong. It also means
  fp32-everywhere will fail and selective reduced precision will pass, which
  makes precision a tunable students must reason about.
- Verified: SoA Adam state + transposed weights + threaded gradients gives
  **6.4×** and still matches.

## P3 · The Loader

One epoch on a corpus larger than memory, 16 GB cap, laptop-class hardware.

- Cells must be visited in a **mandated shuffled order** (`perm()`, Fisher-Yates
  with splitmix64, seed 677). Sequential reads are easy and wrong. Delivering a
  random permutation from disk without random-reading the disk is the project.
- Because the order is fixed, the trajectory is deterministic and the latent
  checksum still works — students cannot buy speed by shuffling less.
- Scored on the **cloud tier**: 4 vCPU / 16 GB, cold page cache.

## P4 · The Device

Port the epoch to an H100. Full GPU nodes, not shards.

- The shipped baseline is the fixed 4-thread CPU reference. Score is speedup
  over it at 16× pbmc3k scale.
- CUDA is detected at configure time; the CPU path always builds, which is what
  lets the reference digest be generated on any machine.
- Canon: **3 significant digits**, because TF32 and fp16 accumulation are
  legitimate answers here and the checksum must not forbid the technique the
  project exists to teach.
- The **crossover plot** is a required deliverable, assessed in the
  presentation rather than by the harness.

## P5 · The Atlas

Cold disk to trained model on a CELLxGENE corpus far larger than the
allocation, with a Slurm job array for the sweep.

- **Queue wait is not counted.** Every submission gets identical resources, so
  wait time measures the queue rather than the student.
- Reuse your own P1–P4, or the provided reference for any stage.
- Canon: 3 significant digits.

---

## Corpora

`tools/fetch_cellxgene.py` builds P3/P4/P5 from the CZI CELLxGENE Census,
restricted to pbmc3k's 13,714-gene feature space so every project shares one
feature axis. `tools/make_pbmc3k.py` generates a negative-binomial synthetic
stand-in with the same shape and dispersion, for offline development.

| Corpus | Cells | Raw dense size |
|---|---|---|
| P1 / P2 | 2,638 (pbmc3k proper) | 289 MB |
| P3 | ~180,000 | ~20 GB |
| P4 | ~42,000 (16× pbmc3k) | ~4.6 GB |
| P5 | ~1,100,000 | ~120 GB |

Build each once on the cluster into `/mnt/projects/cis677/data/`.
