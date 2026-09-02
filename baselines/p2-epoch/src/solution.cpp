// P2 solution -- TIMED. One epoch of autoencoder training.
//
//   ./solution <workdir> <result.bin>
//
//   genes -> 256 -> 32 -> 256 -> genes,  ReLU on hidden layers, linear output,
//   MSE reconstruction loss, Adam, fixed batch order, fixed initialization.
//
// The result written for checksumming is the LATENT EMBEDDING of every cell
// after the epoch: n_cells x 32. That is a strong fingerprint of the whole
// training trajectory -- a wrong gradient anywhere shows up in it.
//
// Architecture, hyperparameters, initialization and batch order are FIXED.
// You are optimizing the implementation, not the model. Do not change:
//   H1, H2, BATCH, LR, BETA1, BETA2, EPS, init_weights(), or the batch order.
#include "canon.hpp"
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

namespace {

constexpr std::uint64_t H1 = 256, H2 = 32, BATCH = 128;
constexpr double LR = 1e-3, BETA1 = 0.9, BETA2 = 0.999, EPS = 1e-8;

// Deterministic init. Identical for every submission. DO NOT MODIFY.
void init_weights(std::vector<double>& w, std::uint64_t fan_in, std::uint64_t seed) {
  std::uint64_t s = 0x9E3779B97F4A7C15ull ^ (seed * 0xBF58476D1CE4E5B9ull);
  const double scale = std::sqrt(2.0 / double(fan_in));
  for (std::uint64_t i = 0; i < w.size(); ++i) {
    s ^= s >> 30; s *= 0xBF58476D1CE4E5B9ull;
    s ^= s >> 27; s *= 0x94D049BB133111EBull;
    s ^= s >> 31;
    double u = double(s >> 11) * (1.0 / 9007199254740992.0);
    w[i] = (u * 2.0 - 1.0) * scale;
  }
}

// Adam state for one parameter tensor. Note the layout -- three quantities
// per parameter, interleaved into one struct. This is a choice, and it is
// not a good one.
struct AdamSlot { double w, m, v; };

struct Layer {
  std::uint64_t in, out;
  std::vector<AdamSlot> p;      // (in * out) weights
  std::vector<AdamSlot> b;      // (out) biases
  Layer(std::uint64_t i, std::uint64_t o, std::uint64_t seed) : in(i), out(o) {
    std::vector<double> w(i * o);
    init_weights(w, i, seed);
    p.resize(i * o);
    for (std::uint64_t t = 0; t < w.size(); ++t) p[t] = {w[t], 0.0, 0.0};
    b.assign(o, {0.0, 0.0, 0.0});
  }
};

void adam_step(std::vector<AdamSlot>& s, const std::vector<double>& g, std::uint64_t t) {
  const double bc1 = 1.0 - std::pow(BETA1, double(t));
  const double bc2 = 1.0 - std::pow(BETA2, double(t));
  for (std::size_t i = 0; i < s.size(); ++i) {
    s[i].m = BETA1 * s[i].m + (1.0 - BETA1) * g[i];
    s[i].v = BETA2 * s[i].v + (1.0 - BETA2) * g[i] * g[i];
    s[i].w -= LR * (s[i].m / bc1) / (std::sqrt(s[i].v / bc2) + EPS);
  }
}

// Dense forward: out = act(in * W + b).  Allocates its output every call.
std::vector<double> forward(const std::vector<double>& x, std::uint64_t n,
                            const Layer& L, bool relu) {
  std::vector<double> y(n * L.out);
  for (std::uint64_t r = 0; r < n; ++r)
    for (std::uint64_t o = 0; o < L.out; ++o) {
      double acc = L.b[o].w;
      for (std::uint64_t i = 0; i < L.in; ++i)
        acc += x[r * L.in + i] * L.p[i * L.out + o].w;
      y[r * L.out + o] = relu ? (acc > 0.0 ? acc : 0.0) : acc;
    }
  return y;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) { std::fprintf(stderr, "usage: solution <workdir> <result.bin>\n"); return 2; }

  std::ifstream in(std::string(argv[1]) + "/matrix.bin", std::ios::binary);
  if (!in) { std::fprintf(stderr, "cannot open workdir matrix\n"); return 1; }
  std::uint64_t nc = 0, ng = 0;
  in.read(reinterpret_cast<char*>(&nc), 8);
  in.read(reinterpret_cast<char*>(&ng), 8);
  std::vector<double> X(nc * ng);
  in.read(reinterpret_cast<char*>(X.data()), std::streamsize(X.size() * 8));
  if (!in) { std::fprintf(stderr, "truncated workdir matrix\n"); return 1; }

  Layer e1(ng, H1, 1), e2(H1, H2, 2), d1(H2, H1, 3), d2(H1, ng, 4);
  std::uint64_t step = 0;

  for (std::uint64_t s0 = 0; s0 < nc; s0 += BATCH) {
    const std::uint64_t n = (s0 + BATCH <= nc) ? BATCH : (nc - s0);
    ++step;

    // ---- forward ----
    std::vector<double> xb(X.begin() + std::ptrdiff_t(s0 * ng),
                           X.begin() + std::ptrdiff_t((s0 + n) * ng));
    std::vector<double> h1 = forward(xb, n, e1, true);
    std::vector<double> z  = forward(h1, n, e2, true);
    std::vector<double> h2 = forward(z,  n, d1, true);
    std::vector<double> xr = forward(h2, n, d2, false);

    // ---- backward: MSE ----
    const double sc = 2.0 / double(n * ng);
    std::vector<double> gxr(n * ng);
    for (std::uint64_t i = 0; i < gxr.size(); ++i) gxr[i] = sc * (xr[i] - xb[i]);

    auto backward = [&](const std::vector<double>& gout, const std::vector<double>& xin,
                        Layer& L, const std::vector<double>& pre, bool relu) {
      std::vector<double> gw(L.in * L.out, 0.0), gb(L.out, 0.0), gin(n * L.in, 0.0);
      for (std::uint64_t r = 0; r < n; ++r)
        for (std::uint64_t o = 0; o < L.out; ++o) {
          double g = gout[r * L.out + o];
          if (relu && pre[r * L.out + o] <= 0.0) g = 0.0;
          gb[o] += g;
          for (std::uint64_t i = 0; i < L.in; ++i) {
            gw[i * L.out + o] += xin[r * L.in + i] * g;
            gin[r * L.in + i] += L.p[i * L.out + o].w * g;
          }
        }
      adam_step(L.p, gw, step);
      adam_step(L.b, gb, step);
      return gin;
    };

    std::vector<double> g3 = backward(gxr, h2, d2, xr, false);
    std::vector<double> g2 = backward(g3,  z,  d1, h2, true);
    std::vector<double> g1 = backward(g2,  h1, e2, z,  true);
    (void)backward(g1, xb, e1, h1, true);
  }

  // ---- latent embedding of every cell: the fingerprint ----
  std::vector<double> Z(nc * H2);
  for (std::uint64_t s0 = 0; s0 < nc; s0 += BATCH) {
    const std::uint64_t n = (s0 + BATCH <= nc) ? BATCH : (nc - s0);
    std::vector<double> xb(X.begin() + std::ptrdiff_t(s0 * ng),
                           X.begin() + std::ptrdiff_t((s0 + n) * ng));
    std::vector<double> h1 = forward(xb, n, e1, true);
    std::vector<double> z  = forward(h1, n, e2, true);
    std::copy(z.begin(), z.end(), Z.begin() + std::ptrdiff_t(s0 * H2));
  }

  hpcbench::write_result(argv[2], Z, {nc, H2});
  return 0;
}
