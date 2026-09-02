# Example submissions

Four points on the same problem, shipped so they can be read, run and argued
with. Every one of them is a real submission: they build, they pass the
checksum, and the numbers on the leaderboard came from running them.

| Directory | What it changes | Geomean speedup* |
|---|---|---|
| `../baselines/p1-kernel` | nothing — the shipped starting point | 1.00× |
| `p1-dense-omp` | adds `#pragma omp parallel for` to the dense loop | ~1.4× |
| `p1-csr-scalar` | converts to CSR in `prepare`, single-threaded solve | ~10× |
| `p1-good` | CSR + 32-bit indices + fp32 values + dynamic scheduling | ~15× |

\* on a 2-core cloud sandbox. Your numbers will differ; the *ordering* is the
part that travels.

Read `p1-dense-omp` against `p1-csr-scalar`. The first one works hard on the
loop it was handed and buys 1.4×. The second changes what the loop reads and
does not thread at all, and buys 10×. That comparison is the entire point of
P1, and it is why full credit sits at 8× — a threshold you cannot reach by
optimising the wrong representation.
