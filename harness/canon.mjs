// ============================================================================
// hpcbench canonical result hashing -- JavaScript/TypeScript reference.
//
// This is a port of hpcbench/canon.py and it must stay bit-identical to it.
// Any divergence means the correctness oracle rejects correct submissions,
// which is the worst bug this project can have. tests/test_canon_parity.py
// checks the two against each other over fixed vectors, random doubles, and
// deliberately-constructed rounding ties; run it after touching either file.
//
// Works unchanged in Node 18+, Deno and the browser: it uses only Web Crypto.
// ============================================================================

export const CANON_VERSION = 1;
export const ZERO_FLOOR = 1e-300;

// 10**22 is the largest power of ten exactly representable as a float64. Past
// that, Math.pow(10, k) and Python's 10.0**k disagree by an ulp because they
// come from different libm implementations -- and an ulp there changes the
// quantized value, the digest, and therefore the verdict on a submission.
// Both implementations refuse this range rather than quietly disagreeing.
export const MAX_EXACT_POW10 = 22;

export class OutOfDomainError extends Error {}

/**
 * Round half to even -- what Python's round() does, and therefore what the
 * grader does.
 *
 * This is NOT Math.round. Math.round breaks ties toward +Infinity, so it
 * disagrees on any value landing exactly on .5 after scaling. Those are rare
 * but entirely reachable: about two in three million uniformly random doubles
 * at nine significant digits, which over a result of ~700,000 elements means a
 * real fraction of submissions would hit one. A submission that hits one and is
 * judged by Math.round is marked wrong while being right.
 */
export function roundHalfEven(y) {
  const f = Math.floor(y);
  const d = y - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;   // exact tie: take the even neighbour
}

/** Round to `sigDigits` significant decimal digits. Significant, not decimal
 *  places: results spanning many orders of magnitude must not have their small
 *  values quantized into oblivion while the large ones keep full precision. */
export function quantize(x, sigDigits) {
  if (!Number.isFinite(x)) throw new Error(`non-finite value in result: ${x}`);
  if (x === 0 || Math.abs(x) < ZERO_FLOOR) return 0;
  const exponent = Math.floor(Math.log10(Math.abs(x)));
  const k = sigDigits - 1 - exponent;
  if (Math.abs(k) > MAX_EXACT_POW10) {
    throw new OutOfDomainError(
      `cannot canonicalize ${x} at ${sigDigits} significant digits: the scaling ` +
      `factor 10**${k} is outside the exactly representable range ` +
      `(|k| <= ${MAX_EXACT_POW10}), where implementations disagree`);
  }
  // Only ever touch an EXACT power of ten. 10**0 .. 10**22 are exactly
  // representable in float64; 10**-1 and friends are not, and Math.pow and
  // Python's ** round them differently. So for k < 0 divide by 10**(-k)
  // instead of multiplying by the inexact 10**k.
  //
  // |x * 10**k| < 10**sigDigits <= 10**15 < 2**53, so roundHalfEven is exact
  // and matches Python's round(), which is also half-to-even.
  let q;
  if (k >= 0) {
    const factor = Math.pow(10, k);
    q = roundHalfEven(x * factor) / factor;
  } else {
    const inv = Math.pow(10, -k);
    q = roundHalfEven(x / inv) * inv;
  }
  return q === 0 ? 0 : q;           // also collapses -0
}

function ascii(s) {
  const a = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i) & 0xff;
  return a;
}

/** The exact byte sequence that gets hashed. Header first, so a truncated
 *  result can never match a prefix of a correct one and two results of
 *  different shape can never collide. */
export function canonicalBytes(values, sigDigits, dims = []) {
  const head = [
    ascii(`hpcbench-canon-v${CANON_VERSION}\0`),
    ascii(`sig${sigDigits}\0`),
    ascii(`shape:${dims.join(",")}\0`),
    ascii(`n:${values.length}\0`),
  ];
  let headLen = 0;
  for (const h of head) headLen += h.length;

  const out = new Uint8Array(headLen + values.length * 8);
  let off = 0;
  for (const h of head) { out.set(h, off); off += h.length; }

  const dv = new DataView(out.buffer, out.byteOffset + off, values.length * 8);
  for (let i = 0; i < values.length; i++) {
    dv.setFloat64(i * 8, quantize(values[i], sigDigits), true);  // little-endian
  }
  return out;
}

export async function digest(values, sigDigits, dims = []) {
  const bytes = canonicalBytes(values, sigDigits, dims);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)]
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Parse a result file written by harness/canon.hpp.
 *
 *   magic   8 bytes  "HPCBENCH"
 *   version u32      must be 1
 *   ndim    u32
 *   dims    u64 * ndim
 *   n       u64      must equal the product of dims
 *   data    f64 * n  and nothing after it
 */
export function parseResultFile(buffer) {
  const u8 = new Uint8Array(buffer);
  if (u8.length < 24) throw new Error("not an hpcbench result file: too short");
  const magic = String.fromCharCode(...u8.slice(0, 8));
  if (magic !== "HPCBENCH")
    throw new Error(`not an hpcbench result file (magic="${magic}")`);

  const dv = new DataView(buffer);
  const version = dv.getUint32(8, true);
  if (version !== CANON_VERSION)
    throw new Error(`canon version ${version}, this reader expects ${CANON_VERSION}`);
  const ndim = dv.getUint32(12, true);

  let off = 16;
  const dims = [];
  for (let i = 0; i < ndim; i++) {
    dims.push(Number(dv.getBigUint64(off, true)));
    off += 8;
  }
  const n = Number(dv.getBigUint64(off, true));
  off += 8;

  if (dims.length) {
    const expected = dims.reduce((a, b) => a * b, 1);
    if (expected !== n)
      throw new Error(`dims [${dims}] imply ${expected} elements, header says ${n}`);
  }
  const need = n * 8;
  if (u8.length - off < need)
    throw new Error(`truncated: expected ${need} bytes of data, got ${u8.length - off}`);
  if (u8.length - off > need)
    throw new Error(`trailing bytes after ${n} elements`);

  const values = new Float64Array(n);
  for (let i = 0; i < n; i++) values[i] = dv.getFloat64(off + i * 8, true);
  return { values, n, dims };
}

/** Digest a result file. Throws with a readable message on any malformation. */
export async function digestResultFile(buffer, sigDigits) {
  const { values, n, dims } = parseResultFile(buffer);
  return { digest: await digest(values, sigDigits, dims), n, dims };
}
