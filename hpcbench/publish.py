"""
Post a device bundle to an hpcbench platform instance.

The on-disk bundle and the platform's wire format are deliberately not the same
shape. The file is the archival record and is what the static leaderboard reads;
the wire format is what the server needs in order to *grade* the run rather than
take the runner's word for it. This module is the one place that translation
lives, so neither side has to know about the other.

The important difference: the wire format carries a digest per sweep value.
The server compares those against its own reference digests and decides
correctness itself. A `checksum_ok: true` asserted by the client is worth
nothing, and the server is right to ignore it.

    python3 -m hpcbench.publish --bundle results/devices/p1-kernel/<id>/<ts>.json \
        --api https://example.lovable.app/api/public
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

WIRE_FORMAT = "hpcbench/device-run/1"


def to_wire(bundle: dict) -> tuple[dict, list[str]]:
    """Translate an on-disk bundle into the platform's payload.

    Returns the payload and the handles that were dropped. An entry that never
    produced a timed run -- a build failure, a run that blew the sanity ceiling
    -- has nothing per-sweep to send and is reported rather than posted as if it
    had measurements.
    """
    dev = bundle["device"]
    results, skipped = [], []
    for e in bundle.get("entries", []):
        per, digests = e.get("per_sweep") or {}, e.get("digests") or {}
        points = []
        for key, v in per.items():
            d = digests.get(key)
            if not d or not v.get("median_ms"):
                continue
            points.append({"key": str(key), "median_ms": v["median_ms"], "digest": d})
        if not points:
            skipped.append(f"{e['handle']} ({e.get('status', 'no data')})")
            continue
        results.append({
            "submission": e["handle"],
            "status": e.get("status", "ok"),
            "per_sweep": points,
            "peak_rss_mb": e.get("peak_rss_mb"),
            "cpu_efficiency": e.get("cpu_efficiency"),
        })

    payload = {
        "format": WIRE_FORMAT,
        "task": bundle["task"],
        "owner": bundle.get("owner"),
        "device": {
            "fingerprint_id": dev["id"],
            "label": dev["label"],
            "kind": dev.get("kind", "desktop"),
            "cpu": dev.get("cpu"),
            "arch": dev.get("arch"),
            "os": dev.get("os"),
            "compiler": dev.get("compiler"),
            "cores_physical": dev.get("cores_physical"),
            "cores_logical": dev.get("cores_logical"),
            "memory_gb": dev.get("memory_gb"),
            "isa": dev.get("isa", []),
        },
        "session": {
            "tier": bundle.get("tier"),
            "runs": bundle.get("runs"),
            "warmup": bundle.get("warmup"),
            "runner_version": "hpcbench/device.py",
        },
        "results": results,
    }
    return payload, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hpcbench-publish")
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--api", default=os.environ.get("HPCBENCH_API"),
                    help="base URL, e.g. https://<host>/api/public")
    ap.add_argument("--token", default=os.environ.get("HPCBENCH_TOKEN"))
    ap.add_argument("--dry-run", action="store_true",
                    help="print the payload instead of posting it")
    a = ap.parse_args(argv)

    with open(a.bundle) as f:
        bundle = json.load(f)
    payload, skipped = to_wire(bundle)

    for s in skipped:
        print(f"  not posted (no timed measurements): {s}", file=sys.stderr)
    if not payload["results"]:
        print("nothing to post: no entry produced a timed run", file=sys.stderr)
        return 1

    if a.dry_run:
        print(json.dumps(payload, indent=2))
        return 0
    if not a.api:
        print("no --api given (or HPCBENCH_API unset)", file=sys.stderr)
        return 2
    if not a.token:
        print("no --token given (or HPCBENCH_TOKEN unset). Get one from Settings.",
              file=sys.stderr)
        return 2

    req = urllib.request.Request(
        a.api.rstrip("/") + "/ingest",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {a.token}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read().decode())
            print(json.dumps(body, indent=2))
            for run in body.get("runs", []):
                sp = f"{run['speedup']:.2f}x" if run.get("speedup") else "-"
                print(f"  {run['submission']:<20} {run['status']:<14} {sp:>9}",
                      file=sys.stderr)
            return 0
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        print(f"HTTP {e.code}\n{detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"could not reach {a.api}: {e.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
