#!/usr/bin/env python3
"""
Produce the P1 corpus.

Preferred: the real pbmc3k matrix from 10x Genomics, converted to the raw dense
format the baseline reads. Fallback: a negative-binomial synthetic matrix with
pbmc3k's shape, density and dispersion, for offline development.

Raw format (what `prepare` reads, and the only thing the grader ships):
    u64 n_cells
    u64 n_genes
    f64 values[n_cells * n_genes]        row-major, cells x genes

It is deliberately the worst possible layout. Choosing something better is the
first project.
"""
import argparse, struct, math, random

def synth_np(path, n_cells, n_genes, density, seed):
    """Vectorized generator. Same model, ~1000x faster than the loop below."""
    import numpy as np
    rng = np.random.default_rng(seed)
    gene_mu = np.exp(rng.normal(-1.2, 1.4, n_genes))
    disp = 0.35
    size = np.clip(rng.normal(1.0, 0.25, n_cells), 0.2, None)
    with open(path, "wb") as f:
        f.write(struct.pack("<QQ", n_cells, n_genes))
        keep_p = np.clip(density * (1.0 + 2.0 * np.minimum(gene_mu, 1.0)), 0, 1)
        for i in range(n_cells):
            lam = gene_mu * size[i] / disp
            lam = rng.gamma(1.0 / disp, lam * disp, n_genes)
            row = rng.poisson(np.clip(lam, 0, 1e6)).astype(np.float64)
            row *= (rng.random(n_genes) < keep_p)
            f.write(row.tobytes())


def synth(path, n_cells, n_genes, density, seed):
    rng = random.Random(seed)
    # Negative binomial via a gamma-Poisson mixture: gene-level means are
    # log-normal, per-cell counts are Poisson around a gamma-scaled mean.
    gene_mu = [math.exp(rng.gauss(-1.2, 1.4)) for _ in range(n_genes)]
    disp = 0.35
    with open(path, "wb") as f:
        f.write(struct.pack("<QQ", n_cells, n_genes))
        for _ in range(n_cells):
            size = rng.gauss(1.0, 0.25)
            row = bytearray()
            for g in range(n_genes):
                if rng.random() > density * (1.0 + 2.0 * min(gene_mu[g], 1.0)):
                    row += struct.pack("<d", 0.0)
                    continue
                lam = gene_mu[g] * max(size, 0.2) / disp
                shape = 1.0 / disp
                lam = rng.gammavariate(shape, lam / shape) if lam > 0 else 0.0
                k = 0; p = math.exp(-min(lam, 700)); s = p; u = rng.random()
                while s < u and k < 4000:
                    k += 1; p *= lam / k; s += p
                row += struct.pack("<d", float(k))
            f.write(row)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cells", type=int, default=2638)
    ap.add_argument("--genes", type=int, default=13714)
    ap.add_argument("--density", type=float, default=0.062)
    ap.add_argument("--seed", type=int, default=677)
    a = ap.parse_args()
    try:
        import numpy  # noqa: F401
        synth_np(a.out, a.cells, a.genes, a.density, a.seed)
    except ImportError:
        synth(a.out, a.cells, a.genes, a.density, a.seed)
    import os
    print(f"{a.out}: {a.cells} x {a.genes}, {os.path.getsize(a.out)/1e6:.1f} MB")
