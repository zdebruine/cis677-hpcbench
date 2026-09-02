import math, struct, subprocess, sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hpcbench.canon import CanonSpec, digest, digest_file, quantize, NonFiniteError

def test_quantize_significant_digits():
    s = CanonSpec(sig_digits=6)
    assert quantize(1234.5678901, s) == 1234.57
    assert quantize(0.00012345678, s) == 0.000123457
    assert quantize(-0.0, s) == 0.0
    assert quantize(1e-320, s) == 0.0   # denormal -> zero

def test_reordering_is_invisible():
    """The whole point: a reordered fp sum must hash identically."""
    import random
    random.seed(1)
    xs = [random.uniform(-1e3, 1e3) for _ in range(5000)]
    fwd = sum(xs)
    bwd = sum(reversed(xs))
    # pairwise (numpy-style) summation
    def pairwise(v):
        if len(v) <= 8: return sum(v)
        m = len(v)//2
        return pairwise(v[:m]) + pairwise(v[m:])
    pw = pairwise(xs)
    assert not (fwd == bwd == pw), "test is vacuous if all three agree bitwise"
    s = CanonSpec(sig_digits=9)
    d = {digest([fwd], s), digest([bwd], s), digest([pw], s)}
    assert len(d) == 1, f"reordering changed the digest: {d}"

def test_precision_boundary():
    """Differences at the declared precision are caught; below it, invisible.

    Both halves matter. The first is correctness: a wrong answer must fail.
    The second is the design: reordering noise must NOT fail.
    """
    s = CanonSpec(sig_digits=9)
    # 9th significant digit differs -> different digest
    assert digest([1.00000001], s) != digest([1.00000002], s)
    # 12th significant digit differs -> same digest (this is intended)
    assert digest([1.00000000001], s) == digest([1.00000000002], s)

def test_shape_and_length_in_digest():
    s = CanonSpec(sig_digits=9)
    assert digest([1.0,2.0], s, shape=(2,)) != digest([1.0,2.0], s, shape=(1,2))
    assert digest([1.0,2.0], s) != digest([1.0,2.0,0.0], s)

def test_exact_mode():
    s = CanonSpec(exact=True)
    assert digest([1.0,2.0,3.0], s) == digest([1.0,2.0,3.0], s)
    try:
        digest([1.5], s); assert False, "should reject non-integral"
    except ValueError: pass

def test_nonfinite_rejected():
    s = CanonSpec(sig_digits=9)
    for bad in (float("nan"), float("inf"), float("-inf")):
        try:
            digest([bad], s); assert False, f"should reject {bad}"
        except NonFiniteError: pass

if __name__ == "__main__":
    fns = [v for k,v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  PASS  {fn.__name__}")
    print(f"\n{len(fns)} passed")
