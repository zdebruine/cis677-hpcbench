// Student solution: read CSR, thread across rows, skip the 93% that are zero.
#include "canon.hpp"
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>
#ifdef _OPENMP
#include <omp.h>
#endif

namespace {
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
  if (argc < 4) return 2;
  const std::uint64_t k = std::strtoull(argv[3], nullptr, 10);

  std::ifstream in(std::string(argv[1]) + "/csr.bin", std::ios::binary);
  if (!in) return 1;
  std::uint64_t nc = 0, ng = 0, nnz = 0;
  in.read(reinterpret_cast<char*>(&nc), 8);
  in.read(reinterpret_cast<char*>(&ng), 8);
  in.read(reinterpret_cast<char*>(&nnz), 8);
  std::vector<std::uint32_t> rowptr(nc + 1), colidx(nnz);
  std::vector<float> vals(nnz);
  in.read(reinterpret_cast<char*>(rowptr.data()), std::streamsize((nc + 1) * 4));
  in.read(reinterpret_cast<char*>(colidx.data()), std::streamsize(nnz * 4));
  in.read(reinterpret_cast<char*>(vals.data()), std::streamsize(nnz * 4));
  if (!in) return 1;

  const std::vector<double> W = gen_W(ng, k);
  std::vector<double> Y(nc * k, 0.0);


  for (std::int64_t i = 0; i < std::int64_t(nc); ++i) {
    double* y = &Y[std::uint64_t(i) * k];
    for (std::uint32_t p = rowptr[i]; p < rowptr[i + 1]; ++p) {
      const double a = double(vals[p]);
      const double* w = &W[std::uint64_t(colidx[p]) * k];
      for (std::uint64_t c = 0; c < k; ++c) y[c] += a * w[c];
    }
  }
  hpcbench::write_result(argv[2], Y, {nc, k});
  return 0;
}
