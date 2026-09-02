// Student prepare: write CSR, 32-bit indices, values as float.
// None of this is timed, so the only question is what makes solution fast.
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

int main(int argc, char** argv) {
  if (argc < 3) return 2;
  std::ifstream in(argv[1], std::ios::binary);
  if (!in) return 1;
  std::uint64_t nc = 0, ng = 0;
  in.read(reinterpret_cast<char*>(&nc), 8);
  in.read(reinterpret_cast<char*>(&ng), 8);
  std::vector<double> X(nc * ng);
  in.read(reinterpret_cast<char*>(X.data()), std::streamsize(X.size() * 8));
  if (!in) return 1;

  std::vector<std::uint32_t> rowptr(nc + 1, 0), colidx;
  std::vector<float> vals;
  colidx.reserve(X.size() / 8); vals.reserve(X.size() / 8);
  for (std::uint64_t i = 0; i < nc; ++i) {
    for (std::uint64_t g = 0; g < ng; ++g) {
      double v = X[i * ng + g];
      if (v != 0.0) { colidx.push_back(std::uint32_t(g)); vals.push_back(float(v)); }
    }
    rowptr[i + 1] = std::uint32_t(vals.size());
  }
  std::uint64_t nnz = vals.size();
  std::ofstream o(std::string(argv[2]) + "/csr.bin", std::ios::binary);
  o.write(reinterpret_cast<const char*>(&nc), 8);
  o.write(reinterpret_cast<const char*>(&ng), 8);
  o.write(reinterpret_cast<const char*>(&nnz), 8);
  o.write(reinterpret_cast<const char*>(rowptr.data()), std::streamsize((nc + 1) * 4));
  o.write(reinterpret_cast<const char*>(colidx.data()), std::streamsize(nnz * 4));
  o.write(reinterpret_cast<const char*>(vals.data()), std::streamsize(nnz * 4));
  std::fprintf(stderr, "prepare: CSR %llu nnz, %.1f MB (dense was %.1f MB)\n",
               (unsigned long long)nnz,
               (8.0 * (nc + 1) + 8.0 * nnz) / 1e6, X.size() * 8.0 / 1e6);
  return o ? 0 : 1;
}
