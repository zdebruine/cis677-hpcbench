#!/usr/bin/env python3
"""
Parity between the Python canonicalizer and the JavaScript one.

Two implementations now compute the correctness oracle: hpcbench/canon.py, used
by the grader and the local runner, and harness/canon.mjs, used by the web
platform's verify endpoint. If they ever disagree, the site tells students their
correct answers are wrong. That is the most damaging failure this project has,
so it gets a test that actively hunts for disagreement rather than checking a
couple of round numbers.

The interesting case is the rounding tie. Python's round() is round-half-to-even;
JavaScript's Math.round breaks ties toward +Infinity. Ties are reachable -- about
two per three million uniform doubles at nine significant digits -- so this test
constructs them deliberately as well as sampling for them.

Requires node (>= 18).
"""
from __future__ import annotations

import json
import math
import os
import random
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hpcbench.canon import (MAX_EXACT_POW10, CanonSpec,  # noqa: E402
                            OutOfDomainError, digest, quantize)

MJS = os.path.join(ROOT, "harness", "canon.mjs")

DRIVER = """
import { readFileSync } from "node:fs";
import { quantize, digest } from %s;
const input = JSON.parse(readFileSync(process.env.HPCBENCH_PARITY_PAYLOAD, "utf8"));
const out = { quantized: [], digests: [] };
for (const c of input.quantize) out.quantized.push(quantize(c.x, c.sig));
for (const c of input.digest) out.digests.push(await digest(c.values, c.sig, c.dims));
process.stdout.write(JSON.stringify(out));
"""


def run_js(payload: dict) -> dict:
    """The payload goes through a file, not argv -- thousands of cases blow past
    the argument-length limit, and a parity test that silently shrinks its own
    sample to fit is not a parity test."""
    import tempfile
    src = DRIVER % json.dumps(MJS)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name
    try:
        env = dict(os.environ, HPCBENCH_PARITY_PAYLOAD=path)
        p = subprocess.run(["node", "--input-type=module", "-e", src],
                           capture_output=True, text=True, env=env)
        if p.returncode != 0:
            raise SystemExit(f"node failed:\n{p.stderr}")
        return json.loads(p.stdout)
    finally:
        os.unlink(path)


ERR_DRIVER = """
import { readFileSync } from "node:fs";
import { quantize } from %s;
const input = JSON.parse(readFileSync(process.env.HPCBENCH_PARITY_PAYLOAD, "utf8"));
const out = [];
for (const c of input.quantize) {
  try { quantize(c.x, c.sig); out.push(false); } catch (e) { out.push(true); }
}
process.stdout.write(JSON.stringify(out));
"""


def run_js_expect_errors(payload: dict) -> list:
    import tempfile
    src = ERR_DRIVER % json.dumps(MJS)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name
    try:
        env = dict(os.environ, HPCBENCH_PARITY_PAYLOAD=path)
        p = subprocess.run(["node", "--input-type=module", "-e", src],
                           capture_output=True, text=True, env=env)
        if p.returncode != 0:
            raise SystemExit(f"node failed:\n{p.stderr}")
        return json.loads(p.stdout)
    finally:
        os.unlink(path)


def exact_ties(sig: int, want: int) -> list[float]:
    """Values where x * 10^(sig-1-e) lands exactly on .5 -- the only place the
    two rounding conventions can disagree."""
    found, m = [], 1
    while len(found) < want and m < 5_000_000:
        x = float(m)
        e = math.floor(math.log10(abs(x)))
        y = x * (10.0 ** (sig - 1 - e))
        if y == math.floor(y) + 0.5:
            found.append(x)
            found.append(-x)
        m += 1
    return found[:want]


def main() -> int:
    rng = random.Random(677)
    cases: list[tuple[float, int]] = []

    # 1. deliberately constructed rounding ties, both signs
    for sig in (3, 6, 9):
        for x in exact_ties(sig, 40):
            cases.append((x, sig))
    n_ties = len(cases)

    # 2. wide random sample across the supported domain. |sig-1-exponent| must
    #    stay within MAX_EXACT_POW10; outside it both implementations refuse,
    #    which is checked separately below.
    while len(cases) < n_ties + 6000:
        sig = rng.choice([3, 5, 7, 9, 12])
        mag = rng.uniform(-20, 20)
        x = rng.uniform(-1, 1) * (10.0 ** mag)
        if not math.isfinite(x) or x == 0.0:
            continue
        if abs(sig - 1 - math.floor(math.log10(abs(x)))) > MAX_EXACT_POW10:
            continue
        cases.append((x, sig))

    # 3. awkward specifics that stay inside the domain
    for sig in (3, 9, 15):
        for x in (0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 1e-300, -1e-300, 5e-324,
                  1 / 3, -2 / 3, 9.99999999999e0, 1e15, -1e-15):
            if x == 0.0 or abs(x) < 1e-300 or abs(
                    sig - 1 - math.floor(math.log10(abs(x)))) <= MAX_EXACT_POW10:
                cases.append((x, sig))

    payload = {"quantize": [{"x": x, "sig": s} for x, s in cases],
               "digest": []}

    # 4. whole-array digests, including a reordering triple
    xs = [rng.uniform(-1e3, 1e3) for _ in range(500)]
    fwd, bwd = 0.0, 0.0
    for v in xs:
        fwd += v
    for v in reversed(xs):
        bwd += v
    arrays = [
        (xs, 9, [500]),
        ([fwd], 9, [1]),
        ([bwd], 9, [1]),
        ([1.0, -2.5, 0.0, 3.14159265358979, 1e-12, -0.0], 9, [3, 2]),
        ([1.23456789012e-8, 1.23456789012e8, 9.99999999949], 9, [3]),
        ([], 9, []),
    ]
    payload["digest"] = [{"values": a, "sig": s, "dims": d} for a, s, d in arrays]

    js = run_js(payload)

    fails = 0
    for (x, sig), got in zip(cases, js["quantized"]):
        want = quantize(x, CanonSpec(sig_digits=sig))
        if struct.pack("<d", want) != struct.pack("<d", got):
            fails += 1
            if fails <= 5:
                print(f"  QUANTIZE MISMATCH sig={sig} x={x!r}: "
                      f"python={want!r} js={got!r}", file=sys.stderr)
    print(f"  {'PASS' if not fails else 'FAIL'}  quantize parity          "
          f"{len(cases)} values ({n_ties} constructed ties), {fails} mismatched")

    dfails = 0
    for (vals, sig, dims), got in zip(arrays, js["digests"]):
        want = digest(vals, CanonSpec(sig_digits=sig), shape=dims)
        if want != got:
            dfails += 1
            print(f"  DIGEST MISMATCH sig={sig} dims={dims} n={len(vals)}\n"
                  f"    python={want}\n    js    ={got}", file=sys.stderr)
    print(f"  {'PASS' if not dfails else 'FAIL'}  digest parity            "
          f"{len(arrays)} arrays, {dfails} mismatched")

    # 5. both implementations must refuse the same out-of-domain inputs, so a
    #    number they would round apart is never silently hashed by either.
    oob = [(1e40, 9), (-1e40, 9), (4.6e-276, 9), (1e300, 3), (1e-200, 12)]
    oob_payload = {"quantize": [{"x": x, "sig": s_} for x, s_ in oob], "digest": []}
    oob_js = run_js_expect_errors(oob_payload)
    ofails = 0
    for (x, s_), js_err in zip(oob, oob_js):
        try:
            quantize(x, CanonSpec(sig_digits=s_))
            py_err = False
        except OutOfDomainError:
            py_err = True
        if py_err != js_err:
            ofails += 1
            print(f"  OUT-OF-DOMAIN DISAGREEMENT x={x!r} sig={s_}: "
                  f"python_rejects={py_err} js_rejects={js_err}", file=sys.stderr)
    print(f"  {'PASS' if not ofails else 'FAIL'}  out-of-domain agreement  "
          f"{len(oob)} values, {ofails} disagreed")

    same = js["digests"][1] == js["digests"][2]
    print(f"  {'PASS' if same else 'FAIL'}  reordered sum, JS side   "
          f"forward and backward summation -> one digest")

    total = fails + dfails + ofails + (0 if same else 1)
    print(f"\n{'parity holds' if not total else str(total) + ' PARITY FAILURE(S)'}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
