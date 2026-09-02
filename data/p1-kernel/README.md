# P1 corpus — provenance

The matrix is **pbmc3k**, taken from the `singlet` R package
(<https://github.com/zdebruine/singlet>), which ships the Satija lab's
tutorial dataset because `SeuratData` is not on CRAN.

`pbmc3k.npz` was produced by reconstructing the matrix exactly as
`singlet::get_pbmc3k_data()` does, minus the Seurat wrapper:

```r
library(Matrix)
load("singlet/data/pbmc3k.RData")
A <- new("dgCMatrix", i = pbmc3k$i, p = pbmc3k$p, Dim = pbmc3k$Dim,
         Dimnames = pbmc3k$Dimnames, x = as.numeric(inverse.rle(pbmc3k$x)))
```

then packed by `tools/pack_pbmc3k.py`. Counts are small integers (max 419), so
they are stored as `uint16`; the whole matrix is 4.4 MB and lives in git.

|                     |                        |
|---------------------|------------------------|
| genes               | 13,714                 |
| cells               | 2,700                  |
| nonzeros            | 2,282,976              |
| density             | 6.166%                 |
| dense fp64          | 296.2 MB               |
| CSR (i32 idx, f32 v)| ~27 MB                 |

Note this is the **raw** 2,700 cells, not the 2,638 that survive the Seurat
tutorial's QC filter. It is what `singlet` returns.

## Regenerating the raw inputs

The `.bin` files are 296 MB each and are **not** in git. Build them:

```bash
python3 tools/make_p1_input.py --variant public  --out data/p1-kernel/public.bin
python3 tools/make_p1_input.py --variant holdout --out data/p1-kernel/holdout.bin
```

`public` is the matrix as shipped. `holdout` is the same matrix with counts
binomially thinned at p=0.9 and rows and columns permuted, seed 1729 — a
thinned negative-binomial count is still negative-binomial, so the holdout has
the same shape, density regime and dispersion but different bytes. Keep it out
of any student-visible repository until the deadline.
