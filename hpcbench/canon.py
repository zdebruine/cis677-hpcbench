"""
Canonical result hashing.

THE CENTRAL DESIGN PROBLEM
--------------------------
"Same checksum for everyone" and "students may vectorize and thread" are in
direct tension. Floating-point addition is not associative, so

    (a + b) + c  !=  a + (b + c)

which means an OpenMP reduction, an AVX-512 horizontal sum, and a plain scalar
loop will produce *bit-different* results from identical inputs. Hashing raw
IEEE-754 bytes would therefore fail every correct parallel submission, which
would gut the course.

The fix is a canonical form: quantize to a declared number of significant
decimal digits, serialize deterministically, then hash. Two results hash
identically iff they agree to the declared precision.

Choose `sig_digits` per task from the numerical conditioning of the problem,
not from taste. Guidance:

    sig_digits   survives                              typical use
    ----------   -----------------------------------   ---------------------
    12           reordered fp64 sums, FMA contraction   well-conditioned fp64
    9            fp64 with mild cancellation            most dense linear algebra
    7            fp32 accumulation                      mixed-precision kernels
    5            fp16/bf16 accumulation                 ML forward passes
    3            aggressive quantization                inference, embeddings

A task may also declare `exact: true` for integer or index outputs (counts,
permutations, sort orders, sparsity patterns), where bit-exactness is the
correct requirement and quantization would be wrong.

The same canonicalization is implemented in `harness/canon.hpp` so a C++
submission can emit its own digest without a Python round-trip. The two
implementations are checked against each other by `tests/test_canon_parity.py`.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Iterable, Sequence

CANON_VERSION = 1  # bump if the wire format ever changes; invalidates old digests


class NonFiniteError(ValueError):
    """A result contained NaN or Inf. Never hashable, always a failure."""


@dataclass(frozen=True)
class CanonSpec:
    """How a task's output is reduced to a checksum."""

    sig_digits: int = 9
    exact: bool = False
    # Values whose magnitude is below this are canonicalized to +0.0. Prevents
    # denormal noise and signed-zero disagreement from changing the digest.
    zero_floor: float = 1e-300

    def __post_init__(self) -> None:
        if not self.exact and not (1 <= self.sig_digits <= 15):
            raise ValueError("sig_digits must be in [1, 15] (fp64 carries ~15.9)")


def quantize(x: float, spec: CanonSpec) -> float:
    """Round x to `sig_digits` significant decimal digits.

    Significant digits, not decimal places: a task whose outputs span many
    orders of magnitude must not have its small values quantized into oblivion
    while its large values keep full precision.
    """
    if not math.isfinite(x):
        raise NonFiniteError(f"non-finite value in result: {x!r}")
    if x == 0.0 or abs(x) < spec.zero_floor:
        return 0.0  # collapses -0.0 and denormals
    exponent = math.floor(math.log10(abs(x)))
    factor = 10.0 ** (spec.sig_digits - 1 - exponent)
    q = round(x * factor) / factor
    return 0.0 if q == 0.0 else q


def _pack(values: Iterable[float], spec: CanonSpec) -> Iterable[bytes]:
    if spec.exact:
        for v in values:
            if not math.isfinite(v):
                raise NonFiniteError(f"non-finite value in result: {v!r}")
            if v != int(v):
                raise ValueError(
                    f"task declares exact=true but result contains {v!r}, "
                    "which is not integral"
                )
            yield struct.pack("<q", int(v))
    else:
        for v in values:
            yield struct.pack("<d", quantize(v, spec))


def digest(values: Sequence[float], spec: CanonSpec, *, shape: Sequence[int] = ()) -> str:
    """Canonical SHA-256 of a numeric result.

    The digest covers the canon version, the spec, the shape, and the element
    count *before* any element bytes. Two results of different shape can
    therefore never collide, and a truncated result can never accidentally
    match a prefix of a correct one.
    """
    h = hashlib.sha256()
    h.update(b"hpcbench-canon-v%d\0" % CANON_VERSION)
    h.update(b"exact\0" if spec.exact else b"sig%d\0" % spec.sig_digits)
    h.update(b"shape:" + b",".join(b"%d" % d for d in shape) + b"\0")
    h.update(b"n:%d\0" % len(values))
    for chunk in _pack(values, spec):
        h.update(chunk)
    return h.hexdigest()


def digest_file(path: str, spec: CanonSpec) -> tuple[str, int, tuple[int, ...]]:
    """Digest a result file written by `harness/canon.hpp`.

    Wire format, all little-endian:
        magic   8 bytes   b"HPCBENCH"
        version u32
        ndim    u32
        dims    u64 * ndim
        n       u64            (product of dims; checked)
        data    f64 * n
    """
    with open(path, "rb") as f:
        magic = f.read(8)
        if magic != b"HPCBENCH":
            raise ValueError(f"{path}: not an hpcbench result file (magic={magic!r})")
        version, ndim = struct.unpack("<II", f.read(8))
        if version != CANON_VERSION:
            raise ValueError(
                f"{path}: canon version {version}, this runner expects {CANON_VERSION}"
            )
        dims = struct.unpack(f"<{ndim}Q", f.read(8 * ndim)) if ndim else ()
        (n,) = struct.unpack("<Q", f.read(8))
        expected = 1
        for d in dims:
            expected *= d
        if dims and expected != n:
            raise ValueError(f"{path}: dims {dims} imply {expected} elements, header says {n}")
        raw = f.read(8 * n)
        if len(raw) != 8 * n:
            raise ValueError(
                f"{path}: truncated — expected {8 * n} bytes of data, got {len(raw)}"
            )
        if f.read(1):
            raise ValueError(f"{path}: trailing bytes after {n} elements")
    values = struct.unpack(f"<{n}d", raw)
    return digest(values, spec, shape=dims), n, dims


def compare(got: str, want: str) -> bool:
    """Constant-time-ish digest comparison. Not security-critical, but cheap."""
    return hashlib.sha256(got.encode()).digest() == hashlib.sha256(want.encode()).digest()
