#!/usr/bin/env python3
"""
Build the P3/P4/P5 corpora from CZI CELLxGENE.

Downloads a set of human PBMC / blood datasets from the CELLxGENE Census,
restricts them to pbmc3k's gene space so every project sees the same feature
axis, and writes the raw dense format the baselines read.

    pip install cellxgene-census tiledbsoma
    python3 tools/fetch_cellxgene.py --out data/p5-atlas/public.bin \
        --cells 2000000 --seed 677

Sizes used by the course (raw dense fp64, cells x 13,714 genes):
    P1/P2   pbmc3k proper                2,638 cells        289 MB
    P3      laptop tier                 ~180,000 cells       ~20 GB
    P4      16x pbmc3k                   ~42,000 cells      ~4.6 GB
    P5      atlas                     ~1,100,000 cells      ~120 GB

Run this ONCE per corpus on the cluster, into /mnt/projects/cis677/data/.
Nothing about it is on any student's clock.
"""
import argparse, struct, sys

GENE_SPACE = "pbmc3k"   # 13,714 features; see tools/gene_list.txt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cells", type=int, required=True)
    ap.add_argument("--seed", type=int, default=677)
    ap.add_argument("--census-version", default="stable")
    ap.add_argument("--tissue", default="blood")
    a = ap.parse_args()

    try:
        import cellxgene_census
        import numpy as np
    except ImportError:
        sys.exit("pip install cellxgene-census tiledbsoma numpy")

    genes = [g.strip() for g in open("tools/gene_list.txt") if g.strip()]
    rng = np.random.default_rng(a.seed)

    with cellxgene_census.open_soma(census_version=a.census_version) as census:
        adata = cellxgene_census.get_anndata(
            census, organism="Homo sapiens",
            obs_value_filter=f"tissue_general == '{a.tissue}' and is_primary_data == True",
            var_value_filter=f"feature_name in {genes!r}",
            column_names={"obs": ["soma_joinid"]},
        )
    X = adata.X
    n = min(a.cells, X.shape[0])
    idx = np.sort(rng.choice(X.shape[0], size=n, replace=False))

    with open(a.out, "wb") as f:
        f.write(struct.pack("<QQ", n, len(genes)))
        for start in range(0, n, 4096):
            block = X[idx[start:start + 4096]].toarray().astype(np.float64)
            f.write(block.tobytes())
            print(f"\r  {min(start + 4096, n)}/{n} cells", end="", file=sys.stderr)
    print(f"\nwrote {a.out}: {n} x {len(genes)}", file=sys.stderr)

if __name__ == "__main__":
    main()
