#!/usr/bin/env bash
# Adversarial suite against p1-kernel. Each break must be caught, and the
# legitimate parallel/format rewrite must NOT be.
cd "$(dirname "$0")/.."
D=$(pwd)/data/p1-kernel
T=tasks/p1-kernel/task.yaml
TMP=$(mktemp -d); trap "rm -rf $TMP" EXIT
pass=0; fail=0

check () { # name expected_status patcher
  local name="$1" want="$2" patch="$3"
  rm -rf "$TMP/s"; cp -r examples/p1-good "$TMP/s"; rm -rf "$TMP/s/build" "$TMP/s/work"
  ( cd "$TMP/s" && eval "$patch" )
  got=$(python3 -m hpcbench.run --task "$T" --submission "$TMP/s" \
        --input-path "$D/public.bin" --handle test --out "$TMP/r.json" --quiet 2>/dev/null \
        >/dev/null; python3 -c "import json;print(json.load(open('$TMP/r.json'))['status'])" 2>/dev/null || echo crash)
  if [[ "$got" == "$want" ]]; then printf "  PASS  %-28s -> %s\n" "$name" "$got"; pass=$((pass+1))
  else printf "  FAIL  %-28s -> got '%s', wanted '%s'\n" "$name" "$got" "$want"; fail=$((fail+1)); fi
}

echo "=== hpcbench gate tests (p1-kernel) ==="
check "CSR + OpenMP rewrite"      ok           "true"
check "1% wrong values"           wrong_answer "sed -i 's|y\[c\] += a \* w\[c\];|y[c] += a * w[c] * 1.01;|' src/solution.cpp"
check "result one element short"  bad_result   "sed -i 's|hpcbench::write_result(argv\[2\], Y, {nc, k});|Y.resize(Y.size()-1); hpcbench::write_result(argv[2], Y, {nc, k});|' src/solution.cpp"
check "NaN in result"             nonfinite    "sed -i 's|hpcbench::write_result(argv\[2\], Y, {nc, k});|Y[0] = 0.0/0.0; hpcbench::write_result(argv[2], Y, {nc, k});|' src/solution.cpp"
check "no result written"         no_result    "sed -i 's|hpcbench::write_result(argv\[2\], Y, {nc, k});||' src/solution.cpp"
check "does not compile"          build_failed "sed -i '1i #error deliberate' src/solution.cpp"
check "prepare fails"             prepare_failed "sed -i 's|return o ? 0 : 1;|return 3;|' src/prepare.cpp"
check "committed stale result"    no_result    "printf 'HPCBENCH' > result.bin; sed -i 's|hpcbench::write_result(argv\[2\], Y, {nc, k});||' src/solution.cpp"
# Sanity ceiling: use a 5s ceiling so the test does not itself take two minutes.
python3 -c "
import json; t=json.load(open('$T')); t['sanity_timeout_s']=5
json.dump(t, open('$TMP/fast.yaml','w'))"
T_SAVE=$T; T=$TMP/fast.yaml
check "sleeps past sanity ceiling" too_slow    "sed -i 's|#include \"canon.hpp\"|#include \"canon.hpp\"\n#include <thread>\n#include <chrono>|; s|const std::vector<double> W = gen_W|std::this_thread::sleep_for(std::chrono::seconds(30)); const std::vector<double> W = gen_W|' src/solution.cpp"
T=$T_SAVE

echo
echo "  $pass passed, $fail failed"
exit $((fail>0))
