// P1 prepare -- UNTIMED.
//
// Reads the raw corpus once and writes whatever on-disk representation you
// want into the workdir. Nothing here is on the clock: sort it, compress it,
// quantize it, split it into shards, build an index. Whatever you write here
// is what solution.cpp has to read, and that decision is most of the project.
//
// The baseline copies the dense matrix through unchanged, which is the worst
// possible answer and is the point.
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

int main(int argc, char** argv) {
  if (argc < 3) { std::fprintf(stderr, "usage: prepare <raw_input> <workdir>\n"); return 2; }

  std::ifstream in(argv[1], std::ios::binary);
  if (!in) { std::fprintf(stderr, "cannot open %s\n", argv[1]); return 1; }

  std::uint64_t n_cells = 0, n_genes = 0;
  in.read(reinterpret_cast<char*>(&n_cells), 8);
  in.read(reinterpret_cast<char*>(&n_genes), 8);
  std::vector<double> X(n_cells * n_genes);
  in.read(reinterpret_cast<char*>(X.data()), std::streamsize(X.size() * 8));
  if (!in) { std::fprintf(stderr, "truncated input\n"); return 1; }

  // Baseline: write it straight back out, dense. Change this.
  const std::string out = std::string(argv[2]) + "/matrix.bin";
  std::ofstream o(out, std::ios::binary);
  o.write(reinterpret_cast<const char*>(&n_cells), 8);
  o.write(reinterpret_cast<const char*>(&n_genes), 8);
  o.write(reinterpret_cast<const char*>(X.data()), std::streamsize(X.size() * 8));
  if (!o) { std::fprintf(stderr, "write failed\n"); return 1; }

  std::uint64_t nnz = 0;
  for (double v : X) if (v != 0.0) ++nnz;
  std::fprintf(stderr, "prepare: %llu x %llu, %llu nonzeros (%.2f%% dense)\n",
               (unsigned long long)n_cells, (unsigned long long)n_genes,
               (unsigned long long)nnz, 100.0 * double(nnz) / double(X.size()));
  return 0;
}
