#!/bin/sh
# Build prepare and solution.
#
# CMake when it is there, a direct compiler call when it is not. A student
# laptop or a cluster login node without a modern CMake should not be shut out
# of running the benchmark -- "everyone runs everyone's code" fails the moment
# the build needs a tool half the devices do not have.
set -e

if command -v cmake >/dev/null 2>&1; then
  cmake -B build -DCMAKE_BUILD_TYPE=Release
  cmake --build build -j"$(nproc 2>/dev/null || echo 4)"
  exit 0
fi

mkdir -p build
CXX="${CXX:-c++}"
FLAGS="-O3 -std=c++17 -DNDEBUG -Iinclude"

# Probe rather than assume: -march=native is rejected on Apple silicon clang
# and on some cross-toolchains, and -fopenmp is absent from stock macOS clang.
probe() { echo 'int main(){}' | $CXX "$1" -x c++ - -o /dev/null 2>/dev/null; }
probe -march=native && FLAGS="$FLAGS -march=native"
OMP=""
probe -fopenmp && OMP="-fopenmp"

$CXX $FLAGS $OMP src/prepare.cpp  -o build/prepare
$CXX $FLAGS $OMP src/solution.cpp -o build/solution
