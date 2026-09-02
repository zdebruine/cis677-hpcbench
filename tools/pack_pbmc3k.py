#!/usr/bin/env python3
"""
Pack the pbmc3k CSC triplet dumped from R into a small, git-friendly archive.

Source of truth is singlet's shipped dataset:

    library(Matrix)
    load("singlet/data/pbmc3k.RData")
    A <- new("dgCMatrix", i=pbmc3k$i, p=pbmc3k$p, Dim=pbmc3k$Dim,
             Dimnames=pbmc3k$Dimnames, x=as.numeric(inverse.rle(pbmc3k$x)))

which is exactly what singlet::get_pbmc3k_data() builds before wrapping it in a
Seurat object. Counts are small integers (max 419 here), so they are stored as
uint16 and the whole matrix fits in a few MB.
"""
import numpy as np, struct, sys

src, out = sys.argv[1], sys.argv[2]
with open(src, "rb") as f:
    ngenes, ncells, nnz = struct.unpack("<iii", f.read(12))
    i = np.frombuffer(f.read(4 * nnz), dtype="<i4")
    p = np.frombuffer(f.read(4 * (ncells + 1)), dtype="<i4")
    x = np.frombuffer(f.read(8 * nnz), dtype="<f8")

assert x.min() >= 0 and (x == np.floor(x)).all(), "counts must be non-negative integers"
assert x.max() < 65536, f"counts exceed uint16: {x.max()}"

np.savez_compressed(out, shape=np.array([ngenes, ncells], dtype="<i4"),
                    indices=i.astype("<i4"), indptr=p.astype("<i4"),
                    data=x.astype("<u2"))
import os
print(f"{out}: {ngenes} genes x {ncells} cells, {nnz} nnz, "
      f"{100*nnz/(ngenes*ncells):.3f}% dense, {os.path.getsize(out)/1e6:.2f} MB")
