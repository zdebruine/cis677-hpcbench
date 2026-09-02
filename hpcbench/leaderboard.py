"""
Static leaderboard generator.

Reads every result JSON under a results directory and emits a single
self-contained HTML file. No server, no database, no JS framework — it is
published to GitHub Pages and rebuilt whenever the nightly scorer commits.

FERPA: this page shows HANDLES ONLY. A ranking of students by performance with
names attached is an education-record disclosure. The handle->name mapping
lives with the instructor and never enters this repository.

Palette is validated (dataviz six checks) for both modes:
    light  #9A6A18 brass (cloud tier) + #2a78d6 blue (hpc tier)
    dark   #B4863A brass              + #3987e5 blue
Series identity is carried by a legend AND a direct text label on every row,
never by color alone.
"""

from __future__ import annotations

import argparse
import math
import html
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .task import geometric_mean

STATUS_LABEL = {
    "ok": ("Scored", "good"),
    "wrong_answer": ("Checksum mismatch", "critical"),
    "build_failed": ("Build failed", "critical"),
    "run_failed": ("Crashed", "critical"),
    "timeout": ("Timed out", "serious"),
    "unstable": ("Too noisy to score", "warning"),
    "nonfinite": ("NaN or Inf in result", "critical"),
    "no_result": ("No result file", "critical"),
    "bad_result": ("Unreadable result", "critical"),
    "measure_failed": ("Measurement failed", "serious"),
    "error": ("Error", "critical"),
    "reference": ("Reference", "good"),
}


def load_results(results_dir: str) -> list[dict]:
    """Grader-run, per-submission records. Device bundles are a different shape
    and live under results/devices/; walking into them would feed multi-entry
    bundles to code that expects one submission per file."""
    out = []
    devices_root = os.path.join(os.path.abspath(results_dir), "devices")
    for root, dirs, files in os.walk(results_dir):
        if os.path.abspath(root) == devices_root:
            dirs[:] = []
            continue
        for fn in files:
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(root, fn)) as f:
                    rec = json.load(f)
            except Exception:
                continue
            if rec.get("schema", "").startswith("hpcbench/device-run"):
                continue
            out.append(rec)
    out.sort(key=lambda r: r.get("started_at", ""))
    return out


def load_device_bundles(results_dir: str, task_id: str) -> list[dict]:
    """The most recent bundle from each device that has run this task."""
    root = os.path.join(results_dir, "devices", task_id)
    latest: dict[str, dict] = {}
    if not os.path.isdir(root):
        return []
    for dev_id in sorted(os.listdir(root)):
        d = os.path.join(root, dev_id)
        if not os.path.isdir(d):
            continue
        best = None
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, name)) as f:
                    b = json.load(f)
            except (OSError, ValueError):
                continue
            if b.get("task") != task_id:
                continue
            if best is None or b.get("measured_at", "") > best.get("measured_at", ""):
                best = b
        if best:
            latest[dev_id] = best
    return list(latest.values())


def load_scoring_devices(path: str) -> tuple[set, dict]:
    """The admin allowlist. Absent or empty means nothing is officially scored."""
    try:
        with open(path) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return set(), {}
    return set(cfg.get("scoring_devices", [])), cfg.get("labels", {})


def cross_device(bundles: list[dict], scoring: set) -> tuple[list[dict], list[dict]]:
    """Per-handle speedups by device, and the combined figure over scoring devices.

    The combined number is a geometric mean of ratios, never of times. A ratio
    measured on a laptop and a ratio measured on a login node are the same kind
    of quantity; the milliseconds behind them are not.
    """
    devices = [{"id": b["device"]["id"], "label": b["device"]["label"],
                "kind": b["device"].get("kind", "unknown"),
                "runner": b["device"].get("runner", "native"),
                "cpu": b["device"].get("cpu", ""),
                "cores": f"{b['device'].get('cores_physical','?')}c/"
                         f"{b['device'].get('cores_logical','?')}t",
                "memory_gb": b["device"].get("memory_gb"),
                "os": b["device"].get("os", ""),
                "threads": b.get("threads"),
                "measured_at": b.get("measured_at", ""),
                "scored": b["device"]["id"] in scoring}
               for b in bundles]
    devices.sort(key=lambda d: (not d["scored"], d["label"]))

    by_handle: dict[str, dict] = {}
    for b in bundles:
        did = b["device"]["id"]
        for e in b.get("entries", []):
            if e.get("speedup") is None:
                continue
            h = by_handle.setdefault(e["handle"], {"handle": e["handle"], "per_device": {}})
            h["per_device"][did] = e["speedup"]

    rows = []
    for h in by_handle.values():
        vals = [v for d, v in h["per_device"].items() if d in scoring]
        h["combined"] = round(geometric_mean(vals), 3) if vals else None
        h["n_scoring"] = len(vals)
        h["n_devices"] = len(h["per_device"])
        allv = list(h["per_device"].values())
        h["spread"] = (round(min(allv), 2), round(max(allv), 2)) if allv else None
        rows.append(h)
    rows.sort(key=lambda r: (r["combined"] is None,
                             -(r["combined"] or 0),
                             -geometric_mean(list(r["per_device"].values()))))
    return rows, devices


def latest_per_handle(records: list[dict], task_id: str, tier: str) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for r in records:
        if r.get("task") != task_id or r.get("tier") != tier:
            continue
        h = r.get("handle", "anon")
        prev = best.get(h)
        if prev is None or r.get("started_at", "") > prev.get("started_at", ""):
            best[h] = r
    return best


def history(records: list[dict], task_id: str, tier: str) -> dict[str, list[float]]:
    hist: dict[str, list[float]] = defaultdict(list)
    for r in records:
        if r.get("task") != task_id or r.get("tier") != tier:
            continue
        if r.get("status") == "ok":
            hist[r.get("handle", "anon")].append(r["metrics"]["median_ms"])
    return dict(hist)


def _spark(values: list[float], w: int = 96, h: int = 22) -> str:
    """Best-so-far trajectory. Lower is better, so the line should fall."""
    if len(values) < 2:
        return f'<svg width="{w}" height="{h}" role="img" aria-label="no trend yet"></svg>'
    best, run = [], float("inf")
    for v in values:
        run = min(run, v)
        best.append(run)
    lo, hi = min(best), max(best)
    span = (hi - lo) or 1.0
    step = w / (len(best) - 1)
    # Literal encoding: y is time, so an improving series falls.
    pts = " ".join(
        f"{i * step:.1f},{3 + (h - 6) * (hi - v) / span:.1f}"
        for i, v in enumerate(best)
    )
    lx, ly = pts.split()[-1].split(",")
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="best time over {len(best)} submissions, {best[0]:.0f} to {best[-1]:.0f} ms">'
        f'<polyline points="{pts}" fill="none" stroke="var(--s1)" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{lx}" cy="{ly}" r="3" fill="var(--s1)" '
        f'stroke="var(--surface)" stroke-width="2"/></svg>'
    )


def _device_strip(rows: list[dict], devices: list[dict], target: float | None,
                  w: int = 560) -> str:
    """One row per submission; one dot per device, placed at its speedup.

    A dot plot, not a bar chart: the quantity of interest is the *spread* of a
    submission's speedup across machines. A bar of the mean would hide exactly
    the thing worth arguing about -- that a change worth 14x on one box is worth
    1.4x on another. The x scale is logarithmic because these are ratios.
    """
    rows = [r for r in rows if r["per_device"]]
    if not rows or not devices:
        return ""
    vals = [v for r in rows for v in r["per_device"].values() if v > 0]
    lo, hi = min(vals + [1.0]), max(vals + [(target or 1.0)])
    lo, hi = lo / 1.25, hi * 1.25
    llo, lhi = math.log10(lo), math.log10(hi)

    pad_l, pad_r, pad_t, row_h = 150, 20, 34, 26
    h = pad_t + row_h * len(rows) + 34

    def sx(v):
        v = max(v, lo)
        return pad_l + (w - pad_l - pad_r) * (math.log10(v) - llo) / (lhi - llo)

    g = [f'<svg width="100%" viewBox="0 0 {w} {h}" role="img" aria-label="speedup '
         f'over the local baseline for {len(rows)} submissions across '
         f'{len(devices)} devices">']

    # log ticks at 1, 2, 5, 10, 20 ... within range
    ticks, m = [], 10.0 ** math.floor(llo)
    while m <= hi * 10:
        for mult in (1, 2, 5):
            v = m * mult
            if lo <= v <= hi:
                ticks.append(v)
        m *= 10
    for v in ticks:
        x = sx(v)
        g.append(f'<line x1="{x:.1f}" y1="{pad_t-10}" x2="{x:.1f}" y2="{pad_t + row_h*len(rows) - 6:.1f}" '
                 f'stroke="var(--grid)" stroke-width="1"/>')
        lab = f"{v:g}x"
        g.append(f'<text x="{x:.1f}" y="{h-14}" class="ax" text-anchor="middle">{lab}</text>')

    if target and lo <= target <= hi:
        x = sx(target)
        g.append(f'<line x1="{x:.1f}" y1="{pad_t-16}" x2="{x:.1f}" '
                 f'y2="{pad_t + row_h*len(rows) - 6:.1f}" stroke="var(--warning)" '
                 f'stroke-width="2" stroke-dasharray="3 3"/>')
        g.append(f'<text x="{x:.1f}" y="{pad_t-20}" class="ax" text-anchor="middle" '
                 f'fill="var(--warning)">full credit {target:g}x</text>')

    for i, r in enumerate(rows):
        cy = pad_t + row_h * i + row_h / 2 - 4
        g.append(f'<text x="{pad_l-12}" y="{cy+4:.1f}" class="rowlab" '
                 f'text-anchor="end">{html.escape(r["handle"])}</text>')
        pts = sorted(((d["id"], r["per_device"].get(d["id"]), d) for d in devices
                      if d["id"] in r["per_device"]), key=lambda t: t[1])
        if len(pts) > 1:                       # connect the spread
            g.append(f'<line x1="{sx(pts[0][1]):.1f}" y1="{cy:.1f}" '
                     f'x2="{sx(pts[-1][1]):.1f}" y2="{cy:.1f}" '
                     f'stroke="var(--rule)" stroke-width="2"/>')
        for _id, v, d in pts:
            scored = d["scored"]
            g.append(
                f'<circle cx="{sx(v):.1f}" cy="{cy:.1f}" r="5.5" '
                f'fill="{"var(--s2)" if scored else "var(--surface)"}" '
                f'stroke="{"var(--surface)" if scored else "var(--muted-mark)"}" '
                f'stroke-width="2"><title>{html.escape(d["label"])}: {v:.2f}x'
                f'{"" if scored else " (not scored)"}</title></circle>')
        if r.get("combined"):
            g.append(f'<text x="{w-pad_r}" y="{cy+4:.1f}" class="ax" '
                     f'text-anchor="end" font-weight="600">{r["combined"]:.2f}x</text>')
    g.append("</svg>")
    return "".join(g)


def _nice_bounds(lo: float, hi: float, ticks: int = 4):
    """Round a domain outward to human numbers, and never below zero.

    Milliseconds and megabytes have a hard floor at 0. Padding the domain by a
    fraction of its range, as the obvious implementation does, pushes the axis
    negative whenever the smallest value is small relative to the spread -- and
    an axis labelled "-38 ms" tells the reader the chart cannot be trusted.
    """
    lo = min(lo, hi)
    span = (hi - lo) or abs(hi) or 1.0
    raw = span / ticks
    mag = 10.0 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag)
    nlo = max(0.0, math.floor(lo / step) * step)
    nhi = math.ceil(hi / step) * step
    if nhi <= nlo:
        nhi = nlo + step
    return nlo, nhi, step


def _pareto(rows: list[dict], w: int = 560, h: int = 300) -> str:
    """Time vs peak memory. Everyone on the frontier wins, which is the point."""
    pts = [
        (r["metrics"]["median_ms"], r["metrics"]["peak_rss_mb"], r["handle"])
        for r in rows if r.get("status") == "ok"
    ]
    if len(pts) < 2:
        return ""
    pad_l, pad_b, pad_t, pad_r = 56, 34, 26, 14
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    x0, x1, xstep = _nice_bounds(min(xs), max(xs))
    y0, y1, ystep = _nice_bounds(min(ys), max(ys))
    xr, yr = x1 - x0, y1 - y0

    def sx(v): return pad_l + (w - pad_l - pad_r) * (v - x0) / xr
    def sy(v): return pad_t + (h - pad_t - pad_b) * (1 - (v - y0) / yr)

    # Pareto frontier: no other point is better on both axes.
    front = [p for p in pts if not any(
        q[0] <= p[0] and q[1] <= p[1] and q != p for q in pts)]
    front.sort()

    g = [f'<svg width="100%" viewBox="0 0 {w} {h}" role="img" '
         f'aria-label="runtime against peak memory, {len(pts)} submissions, '
         f'{len(front)} on the Pareto frontier">']

    ny = int(round(yr / ystep))
    for i in range(ny + 1):                       # recessive grid, on the scale
        val = y0 + ystep * i
        gy = sy(val)
        g.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w-pad_r}" y2="{gy:.1f}" '
                 f'stroke="var(--grid)" stroke-width="1"/>')
        g.append(f'<text x="{pad_l-8}" y="{gy+3.5:.1f}" class="ax" '
                 f'text-anchor="end">{val:.0f}</text>')

    if len(front) > 1:
        fp = " ".join(f"{sx(p[0]):.1f},{sy(p[1]):.1f}" for p in front)
        g.append(f'<polyline points="{fp}" fill="none" stroke="var(--s1)" '
                 f'stroke-width="2" stroke-dasharray="4 3" opacity="0.65"/>')

    for t, m, hd in pts:
        on = (t, m, hd) in front
        g.append(
            f'<circle cx="{sx(t):.1f}" cy="{sy(m):.1f}" r="{5 if on else 4}" '
            f'fill="{"var(--s1)" if on else "var(--muted-mark)"}" '
            f'stroke="var(--surface)" stroke-width="2"><title>{html.escape(hd)}: '
            f'{t:.0f} ms, {m:.0f} MB{" — on frontier" if on else ""}</title></circle>')

    # Frontier labels, placed so they never overlap each other or leave the box.
    # Two fast submissions sit close together on both axes, so fixed offsets
    # overprint one handle on the next and neither can be read.
    CHW, LH = 6.1, 13.0
    placed: list[tuple[float, float, float, float]] = []
    for t, m, hd in sorted(front, key=lambda p: (p[0], p[1])):
        cx, cy = sx(t), sy(m)
        right = cx > pad_l + (w - pad_l - pad_r) * 0.62
        anchor = "end" if right else "start"
        tw = len(hd) * CHW
        lx = cx - 9 if right else cx + 9
        lx = min(max(lx, pad_l + (tw if right else 0)), w - pad_r - (0 if right else tw))
        ly = cy - 10
        box = lambda X, Y: ((X - tw, X) if right else (X, X + tw)) + (Y - 9, Y + 3)
        while True:
            bx0, bx1, by0, by1 = box(lx, ly)
            hit = any(not (bx1 < o[0] or bx0 > o[1] or by1 < o[2] or by0 > o[3])
                      for o in placed)
            if not hit and ly - 9 >= 2:
                break
            ly -= LH
            if ly - 9 < 2:                        # out of room above: go below
                ly = cy + 20
                while any(not (box(lx, ly)[1] < o[0] or box(lx, ly)[0] > o[1]
                               or box(lx, ly)[3] < o[2] or box(lx, ly)[2] > o[3])
                          for o in placed) and ly < h - pad_b:
                    ly += LH
                break
        placed.append(box(lx, ly))
        if abs(ly - (cy - 10)) > 4:               # bumped: draw a leader
            g.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx:.1f}" '
                     f'y2="{ly+3:.1f}" stroke="var(--s1)" stroke-width="1" '
                     f'opacity="0.45"/>')
        g.append(f'<text x="{lx:.1f}" y="{ly:.1f}" class="pt-lab" '
                 f'text-anchor="{anchor}">{html.escape(hd)}</text>')

    nx = int(round(xr / xstep))
    for i in range(nx + 1):
        val = x0 + xstep * i
        g.append(f'<text x="{sx(val):.1f}" y="{h-10}" class="ax" '
                 f'text-anchor="middle">{val:.0f}</text>')
    g.append(f'<text x="{w-pad_r}" y="{pad_t-12}" class="ax" text-anchor="end">ms &rarr;</text>')
    g.append(f'<text x="6" y="{pad_t-12}" class="ax">MB</text>')
    g.append("</svg>")
    return "".join(g)


CSS = """
:root{
  --surface:#FBFCFC; --sunk:#EFF3F4; --ink:#0F1F2C; --ink2:#3B5162; --ink3:#67808F;
  --rule:#CFD9DE; --rule-soft:#E1E8EB; --grid:#E3EAED; --muted-mark:#A9BDC7;
  --s1:#9A6A18; --s2:#2a78d6; --link:#1F5FA8;
  --good:#1C5E3A; --good-bg:#DCEBE1;
  --warning:#8A5A12; --warning-bg:#F6E8CE;
  --serious:#8A4A12; --serious-bg:#F6E0CE;
  --critical:#963333; --critical-bg:#F6DEDE;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --surface:#101E28; --sunk:#16262F; --ink:#DFE8EC; --ink2:#A9BDC7; --ink3:#7A94A1;
  --rule:#263B47; --rule-soft:#1B2C36; --grid:#1F3038; --muted-mark:#4E6976;
  --s1:#B4863A; --s2:#3987e5; --link:#7FB6EE;
  --good:#79C295; --good-bg:#152A1E;
  --warning:#D9A85C; --warning-bg:#2C2317;
  --serious:#D98C5C; --serious-bg:#2C1E17;
  --critical:#DE8B8B; --critical-bg:#2E1A1A;
}}
.rowlab{font:600 12.5px ui-monospace,SFMono-Regular,Menlo,monospace;fill:var(--ink2)}
.dot-filled{background:var(--s2);border-radius:50%}
.dot-hollow{background:transparent;border:2px solid var(--muted-mark);border-radius:50%}
.sub2{font-size:.82rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink3);
 margin:24px 0 8px;font-weight:600}
a{color:var(--link)}
a:hover{text-decoration:none}
a:focus-visible{outline:2px solid var(--link);outline-offset:2px;border-radius:2px}
.note-warn{border:1px solid var(--warning);background:var(--warning-bg);
 color:var(--ink2);border-radius:3px;padding:10px 14px;margin:16px 0 6px;font-size:.9rem}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--ink);
 font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:36px 24px 80px}
h1{font-size:1.85rem;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--ink3);font-size:.92rem;margin-bottom:24px}
.mono{font-variant-numeric:tabular-nums;
 font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
 gap:12px;margin-bottom:26px}
.tile{background:var(--sunk);border:1px solid var(--rule);border-radius:3px;padding:14px 16px}
.tile .k{font-size:.68rem;letter-spacing:.11em;text-transform:uppercase;color:var(--ink3)}
.tile .v{font-size:1.5rem;font-weight:600;margin-top:3px;
 font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.tile .n{font-size:.78rem;color:var(--ink3);margin-top:1px}
h2{font-size:1.05rem;margin:30px 0 10px;letter-spacing:-.01em}
.legend{display:flex;gap:16px;align-items:center;font-size:.82rem;
 color:var(--ink2);margin-bottom:10px;flex-wrap:wrap}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;
 margin-right:6px;vertical-align:-1px}
.scroll{overflow-x:auto;border:1px solid var(--rule);border-radius:3px}
table{border-collapse:collapse;width:100%;min-width:900px;font-size:.88rem}
th,td{text-align:left;padding:9px 11px;border-bottom:1px solid var(--rule-soft);
 vertical-align:middle;white-space:nowrap}
thead th{font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;
 color:var(--ink3);background:var(--sunk);border-bottom:1px solid var(--rule);font-weight:600}
tbody tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums;
 font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
td.h{font-weight:600}
.pill{display:inline-flex;align-items:center;gap:5px;font-size:.7rem;
 padding:2px 8px;border-radius:2px;font-weight:600;letter-spacing:.03em}
.pill.good{background:var(--good-bg);color:var(--good)}
.pill.warning{background:var(--warning-bg);color:var(--warning)}
.pill.serious{background:var(--serious-bg);color:var(--serious)}
.pill.critical{background:var(--critical-bg);color:var(--critical)}
.bar{position:relative;height:16px;background:var(--sunk);border-radius:2px;
 min-width:110px;overflow:hidden}
.bar>i{position:absolute;inset:0 auto 0 0;background:var(--s1);border-radius:2px}
.bar.t2>i{background:var(--s2)}
.pt-lab{font:10px ui-monospace,monospace;fill:var(--ink2)}
.ax{font:10px ui-monospace,monospace;fill:var(--ink3)}
.card{background:var(--sunk);border:1px solid var(--rule);border-radius:3px;padding:16px}
.note{font-size:.85rem;color:var(--ink2);max-width:74ch;line-height:1.6}
.note+.note{margin-top:8px}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--rule);
 color:var(--ink3);font-size:.8rem;line-height:1.6}
code{font-family:ui-monospace,monospace;font-size:.85em;background:var(--sunk);
 padding:1px 5px;border-radius:2px}
"""


def render(task: dict, records: list[dict], *, tier: str = "hpc",
           bundles: list[dict] | None = None, scoring: set | None = None) -> str:
    tid = task["id"]
    requested = tier                       # drives the file naming, always
    rows_map = latest_per_handle(records, tid, tier)
    fell_back = False
    if not rows_map:  # fall back to whatever tier has data
        for alt in ("cloud", "hpc"):
            if alt == tier:
                continue
            alt_map = latest_per_handle(records, tid, alt)
            if alt_map:
                rows_map, tier, fell_back = alt_map, alt, True
                break
    hist = history(records, tid, tier)
    rows = list(rows_map.values())

    scored = [r for r in rows if r.get("status") == "ok"]
    scored.sort(key=lambda r: r["metrics"]["median_ms"])
    others = [r for r in rows if r.get("status") != "ok"]

    pm = next((m for m in task["metrics"] if m.get("primary")), task["metrics"][0])
    baseline = pm.get("baseline")
    target = pm.get("full_credit_at")
    slowest = max((r["metrics"]["median_ms"] for r in scored), default=1.0)
    best = min((r["metrics"]["median_ms"] for r in scored), default=None)

    # Report the figure that is actually scored. For a swept task that is the
    # geometric mean of the per-k speedups, which is NOT baseline-mean over
    # median-mean -- quoting the latter here put 17.92x on the tile while the
    # table beside it said 14.62x for the same submission, which is precisely
    # the kind of two-numbers-one-claim this course tells students not to ship.
    best_speedup = max((r["speedup"] for r in scored if r.get("speedup")), default=None)
    swept = bool(task.get("sweep_values"))
    tiles = [
        ("Submissions", str(len(rows)), "distinct handles"),
        ("Passing checksum", f"{len(scored)}/{len(rows)}", "cleared the gate"),
        ("Best speedup", f"{best_speedup:.2f}x" if best_speedup else "—",
         ("geometric mean over "
          f"{task['sweep_arg']} = {', '.join(str(v) for v in task['sweep_values'])}")
         if swept else "over the shipped baseline"),
        ("Baseline", f"{baseline:.1f} ms" if baseline else "—",
         (f"mean over the sweep · full credit at {target}x" if swept and target
          else f"full credit at {target}x" if target else "")),
    ]
    tile_html = "".join(
        f'<div class="tile"><div class="k">{html.escape(k)}</div>'
        f'<div class="v">{html.escape(v)}</div>'
        f'<div class="n">{html.escape(n)}</div></div>'
        for k, v, n in tiles
    )

    body = []
    for i, r in enumerate(scored, 1):
        m = r["metrics"]
        frac = m["median_ms"] / slowest if slowest else 0
        sp = r.get("speedup")
        sp_cell = f'<td class="num">{sp:.2f}x</td>' if sp else '<td class="num">&mdash;</td>'
        t2 = " t2" if r.get("tier") == "hpc" else ""
        body.append(
            f'<tr><td class="num">{i}</td>'
            f'<td class="h">{html.escape(r["handle"])}</td>'
            f'<td><span class="pill good">&#10003; scored</span></td>'
            f'<td class="num">{m["median_ms"]:.1f}</td>'
            f'<td><div class="bar{t2}"><i style="width:{max(frac*100,2):.1f}%"></i></div></td>'
            + sp_cell +
            f'<td class="num">&plusmn;{m["iqr_ms"]:.1f}</td>'
            f'<td class="num">{m["peak_rss_mb"]:.0f}</td>'
            f'<td class="num">{m.get("cpu_efficiency",0):.2f}</td>'
            f'<td>{_spark(hist.get(r["handle"], []))}</td>'
            f'<td class="mono" style="color:var(--ink3)">{html.escape(r.get("tier",""))}'
            f' &middot; {html.escape(r.get("commit_short",""))}</td></tr>'
        )

    for r in others:
        label, sev = STATUS_LABEL.get(r.get("status", "error"), ("Error", "critical"))
        body.append(
            f'<tr><td class="num" style="color:var(--ink3)">—</td>'
            f'<td class="h">{html.escape(r.get("handle","?"))}</td>'
            f'<td><span class="pill {sev}">{html.escape(label)}</span></td>'
            f'<td colspan="7" style="color:var(--ink3);font-size:.84rem;'
            f'white-space:normal">{html.escape((r.get("error") or "")[:180])}</td>'
            f'<td class="mono" style="color:var(--ink3)">{html.escape(r.get("commit_short",""))}</td></tr>'
        )

    pareto = _pareto(scored)
    pareto_block = (
        f'<h2>Runtime against peak memory</h2>'
        f'<div class="legend"><span>Filled &amp; labelled points are on the Pareto '
        f'frontier &mdash; nothing beats them on both axes at once.</span></div>'
        f'<div class="card">{pareto}</div>' if pareto else ""
    )

    # ---- cross-device -------------------------------------------------------
    bundles = bundles or []
    scoring = scoring or set()
    dev_rows, dev_list = cross_device(bundles, scoring) if bundles else ([], [])
    if dev_rows:
        n_scored = sum(1 for d in dev_list if d["scored"])
        strip = _device_strip(dev_rows, dev_list, target)
        drow_parts = []
        for r in dev_rows:
            comb = f'{r["combined"]:.2f}x' if r.get("combined") else "&mdash;"
            if r.get("spread"):
                sp = f'{r["spread"][0]:.2f}&ndash;{r["spread"][1]:.2f}x'
            else:
                sp = "&mdash;"
            drow_parts.append(
                "<tr><td><strong>" + html.escape(r["handle"]) + "</strong></td>"
                + '<td class="num">' + comb + "</td>"
                + '<td class="num">' + f'{r["n_scoring"]}/{r["n_devices"]}' + "</td>"
                + '<td class="num">' + sp + "</td></tr>")
        drows = "".join(drow_parts)

        dlist_parts = []
        for d in dev_list:
            marker = "&#9679;" if d["scored"] else "&#9675;"
            mem = f'{d["memory_gb"]} GB' if d["memory_gb"] else "&mdash;"
            thr = str(d["threads"]) if d["threads"] else "&mdash;"
            dlist_parts.append(
                "<tr><td>" + marker + " <strong>" + html.escape(d["label"])
                + '</strong><div class="n">' + html.escape(d["cpu"]) + "</div></td>"
                + "<td>" + html.escape(d["kind"]) + "</td>"
                + '<td class="num">' + html.escape(d["cores"]) + "</td>"
                + '<td class="num">' + mem + "</td>"
                + '<td class="n">' + html.escape(d["os"]) + "</td>"
                + '<td class="num">' + thr + "</td>"
                + '<td class="mono n">' + html.escape(d["id"]) + "</td></tr>")
        dlist = "".join(dlist_parts)

        warn = "" if n_scored else (
            '<div class="note-warn">No devices are in the scoring allowlist yet, so '
            'there is no combined figure. Add device ids to '
            '<code>scoring/devices.json</code> to make their runs count.</div>')
        cross_block = f"""
<h2>Across devices</h2>
<div class="legend">
  <span>Speedup over the baseline <em>measured on that same machine</em>. Ratios are
  comparable across hardware; the milliseconds behind them are not.</span>
</div>
<div class="legend">
  <span><i class="dot-filled"></i>counts toward the score</span>
  <span><i class="dot-hollow"></i>ran it, not scored</span>
  <span>{len(dev_list)} device{"" if len(dev_list) == 1 else "s"},
  {n_scored} scoring</span>
</div>
{warn}
<div class="card">{strip}</div>
<div class="scroll" style="margin-top:14px"><table>
<thead><tr><th>Handle</th><th class="num">Combined</th>
<th class="num">Scoring / all</th><th class="num">Range across devices</th></tr></thead>
<tbody>{drows}</tbody></table></div>
<h3 class="sub2">Devices</h3>
<div class="scroll"><table>
<thead><tr><th>Device</th><th>Kind</th><th class="num">Cores</th><th class="num">RAM</th>
<th>OS</th><th class="num">Threads</th><th>ID</th></tr></thead>
<tbody>{dlist}</tbody></table></div>
"""
    else:
        cross_block = ""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # The HPC tier is authoritative and owns the plain "<id>.html" path; the
    # cloud tier lives beside it. Each page links to the other so nobody has to
    # know that convention.
    # Naming follows the tier that was REQUESTED, not the one that happened to
    # have data. Before the first Clipper run there are no hpc results, and the
    # old code quietly relabelled p1-kernel.html -- the URL everyone treats as
    # the official score -- as a cloud page. Provisional numbers must never
    # occupy the authoritative path without saying so.
    other_tier = "cloud" if requested == "hpc" else "HPC"
    other_href = f"{tid}-cloud.html" if requested == "hpc" else f"{tid}.html"
    fallback_note = (
        f'<div class="note-warn">No <strong>{html.escape(requested)}</strong>-tier '
        f'results for this project yet. Showing the <strong>{html.escape(tier)}</strong> '
        f'tier instead &mdash; these are provisional and are <strong>not</strong> the '
        f'official score.</div>' if fell_back else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(task['title'])} &middot; CIS 677</title>
<style>{CSS}</style></head><body><div class="wrap">

<div class="sub"><a href="./">&larr; all projects</a></div>
<h1>{html.escape(task['title'])}</h1>
<div class="sub">CIS 677 &middot; scored on the <strong>{html.escape(tier)}</strong> tier
&middot; updated {now} &middot; <a href="{other_href}">see the {other_tier} tier</a></div>

{fallback_note}
<div class="tiles">{tile_html}</div>

<h2>Standings</h2>
<div class="legend">
  <span><i style="background:var(--s1)"></i>cloud tier</span>
  <span><i style="background:var(--s2)"></i>hpc tier</span>
  <span style="color:var(--ink3)">Tier is also named in the last column &mdash;
  identity is never carried by colour alone.</span>
</div>
<div class="scroll"><table>
<thead><tr>
<th>#</th><th>Handle</th><th>Status</th><th style="text-align:right">Median (ms)</th>
<th></th><th style="text-align:right">Speedup</th><th style="text-align:right">IQR</th>
<th style="text-align:right">RSS (MB)</th><th style="text-align:right">CPU eff</th>
<th>Best so far</th><th>Run</th>
</tr></thead>
<tbody>{''.join(body) or '<tr><td colspan="11" style="color:var(--ink3)">No submissions yet.</td></tr>'}</tbody>
</table></div>

{pareto_block}
{cross_block}

<h2>How this is scored</h2>
<div class="card">
<p class="note"><strong>Correctness is a gate.</strong> Your result is quantized to
{task['canon'].get('sig_digits', 9)} significant digits and hashed. A submission whose
digest does not match the reference scores zero on the benchmark, at any speed.
Quantization is what lets you vectorize and thread freely &mdash; a reordered
floating-point sum still hashes identically.</p>
<p class="note"><strong>Rank is not the grade.</strong> Full benchmark credit is earned at
{target}x over the shipped baseline, not by placing first. Everyone can earn all
the available points.</p>
<p class="note"><strong>A noisy run is not a result.</strong> Any submission whose IQR
exceeds 10&percnt; of its median is rejected rather than scored. Re-run it.</p>
<p class="note"><strong>Your grade uses a held-out input</strong> of the same distribution,
released after the deadline. A solution tuned to this specific matrix will not transfer.</p>
</div>

<footer>
Handles only &mdash; no student names appear on this page or in this repository.<br>
Cloud-tier and HPC-tier timings are produced by identical code on different hardware
and are <strong>not comparable to each other</strong>; compare within a tier.<br>
Hardware counters (IPC, cache-miss rate) appear on HPC-tier rows only, where
<code>perf</code> is available.
</footer>
</div></body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hpcbench-leaderboard")
    ap.add_argument("--task", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tier", default="hpc")
    ap.add_argument("--scoring", default="scoring/devices.json",
                    help="admin allowlist of devices whose runs count")
    a = ap.parse_args(argv)

    with open(a.task) as f:
        task = json.load(f)
    recs = load_results(a.results)
    bundles = load_device_bundles(a.results, task["id"])
    scoring, _labels = load_scoring_devices(a.scoring)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        f.write(render(task, recs, tier=a.tier, bundles=bundles, scoring=scoring))
    # Count what actually lands on the page, not everything on disk -- the
    # results directory holds every task, and "12 records" on a page showing
    # none of them is a confusing thing to print during a deploy.
    shown = len(latest_per_handle(recs, task["id"], a.tier))
    print(f"wrote {a.out} ({shown} on {a.tier} tier, {len(recs)} result files, "
          f"{len(bundles)} device bundle(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
