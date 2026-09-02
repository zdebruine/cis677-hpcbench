// P1 solution -- TIMED, end to end.
//
//   ./solution <workdir> <result.bin> <k>
//
// The clock starts when this process starts and stops when it exits. That
// covers reading your representation from the workdir, computing Y = X * W,
// and writing the result. It does NOT cover building the file (that was
// prepare) or computing the checksum (the harness does that afterwards).
//
// W is generated deterministically from k so every submission multiplies by
// exactly the same weights. Do not change gen_W.
#include "canon.hpp"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

namespace {

// Deterministic weights. Identical for every submission. DO NOT MODIFY.
std::vector<double> gen_W(std::uint64_t n_genes, std::uint64_t k) {
  std::vector<double> W(n_genes * k);
  std::uint64_t s = 0x9E3779B97F4A7C15ull ^ (k * 0xBF58476D1CE4E5B9ull);
  for (std::uint64_t i = 0; i < W.size(); ++i) {
    s ^= s >> 30; s *= 0xBF58476D1CE4E5B9ull;
    s ^= s >> 27; s *= 0x94D049BB133111EBull;
    s ^= s >> 31;
    W[i] = (double(s >> 11) * (1.0 / 9007199254740992.0)) * 2.0 - 1.0;
  }
  return W;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 4) {
    std::fprintf(stderr, "usage: solution <workdir> <result.bin> <k>\n");
    return 2;
  }
  const std::uint64_t k = std::strtoull(argv[3], nullptr, 10);

  // ---- load whatever prepare wrote --------------------------------------
  std::ifstream in(std::string(argv[1]) + "/matrix.bin", std::ios::binary);
  if (!in) { std::fprintf(stderr, "cannot open workdir matrix\n"); return 1; }
  std::uint64_t n_cells = 0, n_genes = 0;
  in.read(reinterpret_cast<char*>(&n_cells), 8);
  in.read(reinterpret_cast<char*>(&n_genes), 8);
  std::vector<double> X(n_cells * n_genes);
  in.read(reinterpret_cast<char*>(X.data()), std::streamsize(X.size() * 8));
  if (!in) { std::fprintf(stderr, "truncated workdir matrix\n"); return 1; }

  const std::vector<double> W = gen_W(n_genes, k);

  // ---- Y = X * W --------------------------------------------------------
  std::vector<double> Y(n_cells * k, 0.0);
  for (std::uint64_t i = 0; i < n_cells; ++i)
    for (std::uint64_t g = 0; g < n_genes; ++g)
      for (std::uint64_t c = 0; c < k; ++c)
        Y[i * k + c] += X[i * n_genes + g] * W[g * k + c];

  hpcbench::write_result(argv[2], Y, {n_cells, k});
  return 0;
}
