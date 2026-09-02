"""
The student-facing competition site.

Shaped like a competition platform rather than a report: a header with the
things a competitor checks first, tabs, a ranked board with medals, and one
obvious way to submit.

What the site cannot do, and does not pretend to: authorise anybody. GitHub
Pages serves static files from a CDN. There is no server, no session, no
password check. So "sign in" here sets a handle in your own browser to
highlight your rows, and it says so. Ownership is asserted in every result
file and enforced in CI by tools/validate_submissions.py, which compares the
declared owner against the GitHub account that pushed it. That check is real
because it runs somewhere that can see both.
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import math
import os
from datetime import datetime, timezone

from .leaderboard import (cross_device, load_device_bundles, load_results,
                          load_scoring_devices, latest_per_handle, _device_strip)
from .theme import CSS, HEAD

AV_HUES = [198, 172, 22, 268, 340, 44, 145, 300]


def av_color(handle: str) -> str:
    h = sum(ord(c) * (i + 7) for i, c in enumerate(handle)) % len(AV_HUES)
    return f"hsl({AV_HUES[h]} 52% 38%)"


def avatar(handle: str, size: int = 26) -> str:
    initial = (handle or "?")[0].upper()
    return (f'<span class="av" style="background:{av_color(handle)};'
            f'width:{size}px;height:{size}px;font-size:{size*0.44:.0f}px">'
            f'{html.escape(initial)}</span>')


def medal(rank: int) -> str:
    if rank == 1:
        return '<span class="medal m1">1</span>'
    if rank == 2:
        return '<span class="medal m2">2</span>'
    if rank == 3:
        return '<span class="medal m3">3</span>'
    return f'<span class="rank">{rank}</span>'


def codeblock(text: str, label: str = "Copy") -> str:
    esc = html.escape(text)
    return (f'<div class="codeblock"><button class="copy" type="button" '
            f'data-copy>{label}</button><pre><code>{esc}</code></pre></div>')


def owner_of(handle: str, roster: dict, results_owner: dict) -> dict:
    """Who a leaderboard row belongs to. Unowned rows are not shown as people."""
    h = results_owner.get(handle)
    if h and h in roster:
        return roster[h]
    return {"handle": h or "unclaimed", "display_name": h or "Unclaimed",
            "github": "", "role": "student"}


# --------------------------------------------------------------- competition

def render_competition(task: dict, records: list, bundles: list, scoring: set,
                       roster: dict, cfg: dict, *, tier: str = "cloud") -> str:
    tid = task["id"]
    pm = next((m for m in task["metrics"] if m.get("primary")), task["metrics"][0])
    target = pm.get("full_credit_at")

    rows_map = latest_per_handle(records, tid, tier)
    rows = list(rows_map.values())
    owners = {r["handle"]: r.get("owner") for r in rows}
    for b in bundles:
        for e in b.get("entries", []):
            owners.setdefault(e["handle"], b.get("owner"))

    scored = [r for r in rows if r.get("status") == "ok"]
    scored.sort(key=lambda r: -(r.get("speedup") or 0))
    dev_rows, dev_list = cross_device(bundles, scoring) if bundles else ([], [])
    participants = sorted({o for o in owners.values() if o})

    # ---- leaderboard rows
    lb = []
    best = max((r.get("speedup") or 0) for r in scored) if scored else 1.0
    for i, r in enumerate(scored, 1):
        o = owner_of(r["handle"], roster, owners)
        sp = r.get("speedup") or 0
        frac = min(sp / best, 1.0) if best else 0
        hit = "p-ok" if target and sp >= target else "p-warn"
        badge = ("Full credit" if target and sp >= target
                 else f"{100 * sp / target:.0f}% of target" if target else "scored")
        lb.append(
            '<tr data-owner="' + html.escape(o["handle"]) + '">'
            + '<td class="rank">' + medal(i) + '</td>'
            + '<td><div class="who">' + avatar(o["handle"])
            + '<div><div class="n">' + html.escape(r["handle"]) + '</div>'
            + '<div class="sub">' + html.escape(o["display_name"]) + '</div></div></div></td>'
            + '<td class="num" style="font-weight:700">' + f'{sp:.2f}&times;' + '</td>'
            + '<td><div class="bar"><i style="width:' + f'{frac*100:.0f}%' + '"></i></div></td>'
            + '<td><span class="pill ' + hit + '">' + badge + '</span></td>'
            + '<td class="num">' + f'{r["metrics"]["median_ms"]:.0f}' + '</td>'
            + '<td class="num">' + f'{r["metrics"]["peak_rss_mb"]:.0f}' + '</td>'
            + '<td class="mono" style="font-size:12px;color:var(--ink3)">'
            + html.escape((r.get("commit_short") or "")[:7]) + '</td>'
            + '</tr>')
    for r in [x for x in rows if x.get("status") != "ok"]:
        o = owner_of(r["handle"], roster, owners)
        lb.append(
            '<tr data-owner="' + html.escape(o["handle"]) + '">'
            + '<td class="rank">&mdash;</td>'
            + '<td><div class="who">' + avatar(o["handle"])
            + '<div><div class="n">' + html.escape(r["handle"]) + '</div>'
            + '<div class="sub">' + html.escape(o["display_name"]) + '</div></div></div></td>'
            + '<td class="num">&mdash;</td><td></td>'
            + '<td><span class="pill p-bad">' + html.escape(r.get("status", "")) + '</span></td>'
            + '<td class="num">&mdash;</td><td class="num">&mdash;</td><td></td></tr>')
    lb_html = "".join(lb) or (
        '<tr><td colspan="8"><div class="empty"><div class="big">&#9675;</div>'
        'No submissions yet. Yours would be first.</div></td></tr>')

    # ---- devices
    dev_html = ""
    if dev_rows:
        strip = _device_strip(dev_rows, dev_list, target)
        n_scored = sum(1 for d in dev_list if d["scored"])
        parts = []
        for r in dev_rows:
            comb = f'{r["combined"]:.2f}&times;' if r.get("combined") else "&mdash;"
            spread = (f'{r["spread"][0]:.2f}&ndash;{r["spread"][1]:.2f}&times;'
                      if r.get("spread") else "&mdash;")
            chips = "".join(
                '<span class="chip ' + ("scored" if d["scored"] else "")
                + '"><span class="d"></span>' + html.escape(d["label"][:26]) + ' '
                + f'{r["per_device"][d["id"]]:.1f}&times;</span>'
                for d in dev_list if d["id"] in r["per_device"])
            parts.append(
                '<tr><td><strong>' + html.escape(r["handle"]) + '</strong></td>'
                + '<td class="num" style="font-weight:700">' + comb + '</td>'
                + '<td class="num">' + f'{r["n_scoring"]}/{r["n_devices"]}' + '</td>'
                + '<td class="num">' + spread + '</td>'
                + '<td>' + chips + '</td></tr>')
        warn = "" if n_scored else (
            '<div class="note warn"><strong>No device is in the scoring allowlist '
            'yet,</strong> so there is no official combined figure. Everything below '
            'is real measurement and none of it is a grade.</div>')
        dev_cards = "".join(
            '<tr><td><div class="who">' + avatar(d["id"][:1] + d["label"])
            + '<div><div class="n">' + html.escape(d["label"]) + '</div>'
            + '<div class="sub">' + html.escape(d["cpu"]) + '</div></div></div></td>'
            + '<td><span class="pill p-mut">' + html.escape(d["kind"]) + '</span></td>'
            + '<td class="num">' + html.escape(d["cores"]) + '</td>'
            + '<td class="num">' + (f'{d["memory_gb"]} GB' if d["memory_gb"] else "&mdash;") + '</td>'
            + '<td style="font-size:12.5px;color:var(--ink3)">' + html.escape(d["os"]) + '</td>'
            + '<td>' + ('<span class="pill p-ok">scoring</span>' if d["scored"]
                        else '<span class="pill p-mut">not scored</span>') + '</td>'
            + '<td class="mono" style="font-size:12px;color:var(--ink3)">'
            + html.escape(d["id"]) + '</td></tr>' for d in dev_list)
        dev_html = f"""
{warn}
<h2 class="sec">Speedup by device</h2>
<p class="lede">Every device runs the shipped baseline alongside every submission and
reports each one's speedup over <em>its own</em> baseline. Ratios travel between a
laptop, a login node and a cluster; milliseconds do not.</p>
<div class="legend">
  <span><span class="chip scored"><span class="d"></span>counts</span> in the official figure</span>
  <span><span class="chip"><span class="d"></span>ran it</span> shown, not scored</span>
</div>
<div class="card">{strip}</div>
<div class="tablecard" style="margin-top:14px"><div class="scroll"><table>
<thead><tr><th>Submission</th><th class="num">Combined</th><th class="num">Scoring / all</th>
<th class="num">Range</th><th>Per device</th></tr></thead>
<tbody>{"".join(parts)}</tbody></table></div></div>
<h2 class="sec">Machines</h2>
<p class="lede">What each device is, so a surprising number can be argued with rather
than guessed at. The fingerprint describes the hardware, never the person.</p>
<div class="tablecard"><div class="scroll"><table>
<thead><tr><th>Device</th><th>Kind</th><th class="num">Cores</th><th class="num">RAM</th>
<th>OS</th><th>Status</th><th>ID</th></tr></thead>
<tbody>{dev_cards}</tbody></table></div></div>
"""
    else:
        dev_html = ('<div class="empty"><div class="big">&#9675;</div>'
                    'No device runs yet. Run one from the <strong>Submit</strong> tab.</div>')

    # ---- people
    people = "".join(
        '<tr><td><div class="who">' + avatar(h)
        + '<div><div class="n">' + html.escape(roster.get(h, {}).get("display_name", h))
        + '</div><div class="sub">@' + html.escape(roster.get(h, {}).get("github", h))
        + '</div></div></div></td>'
        + '<td><span class="pill ' + ("p-ok" if roster.get(h, {}).get("role") == "admin"
                                      else "p-mut") + '">'
        + html.escape(roster.get(h, {}).get("role", "student")) + '</span></td>'
        + '<td class="num">' + str(sum(1 for k, v in owners.items() if v == h)) + '</td>'
        + '<td class="num">' + str(sum(1 for b in bundles if b.get("owner") == h)) + '</td>'
        + '</tr>' for h in participants) or (
        '<tr><td colspan="4"><div class="empty">Nobody has entered yet.</div></td></tr>')

    repo = cfg.get("repo", "zdebruine/cis677-hpcbench")
    admin = cfg.get("admin_email", "")
    notes = task.get("notes", "")
    sweep = task.get("sweep_values")
    sweep_txt = (", ".join(str(v) for v in sweep)) if sweep else "&mdash;"

    cli = f"""# 1. get the runner (one command, nothing to install)
curl -fsSL https://raw.githubusercontent.com/{repo}/main/tools/hpcbench-submit -o hpcbench-submit
chmod +x hpcbench-submit

# 2. run every submission on your machine and open a PR with the result
./hpcbench-submit --task {tid} --owner YOUR_HANDLE --label "my laptop" --kind laptop"""

    now = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    return f"""<!doctype html>
<html lang="en"><head>{HEAD}
<title>{html.escape(task['title'])} &middot; hpcbench</title>
<style>{CSS}</style></head><body>
<header class="appbar"><div class="in">
  <a class="brand" href="./"><span class="mk">hb</span>hpcbench<span class="course">CIS 677</span></a>
  <nav class="appnav">
    <a href="./" aria-current="page">Competitions</a>
    <a href="./#docs">Docs</a>
    <a href="https://github.com/{repo}">Code</a>
  </nav>
  <span class="spacer"></span>
  <button class="idchip" id="idbtn" type="button">
    <span class="av" id="idav" style="background:var(--muted-mark)">?</span>
    <span id="idname">Sign in</span>
  </button>
</div></header>

<div class="hero"><div class="in">
  <div class="crumbs"><a href="./">Competitions</a> &rsaquo; {html.escape(tid)}</div>
  <h1>{html.escape(task['title'])}</h1>
  <p class="tagline">{html.escape(notes)}</p>
  <div class="metarow">
    <div class="meta"><span class="k">Metric</span><span class="v">Geometric-mean speedup</span></div>
    <div class="meta"><span class="k">Full credit at</span><span class="v">{target}&times;</span></div>
    <div class="meta"><span class="k">Entries</span><span class="v">{len(rows)}</span></div>
    <div class="meta"><span class="k">Competitors</span><span class="v">{len(participants)}</span></div>
    <div class="meta"><span class="k">Devices</span><span class="v">{len(dev_list)}</span></div>
  </div>
  <div class="cta">
    <button class="btn btn-primary" id="runbtn" type="button">&#9654;&nbsp; Run in my browser</button>
    <a class="btn btn-ghost" href="#submit">Submit from the command line</a>
  </div>
  <div class="tabs" role="tablist">
    <button role="tab" data-tab="leaderboard" aria-selected="true">Leaderboard</button>
    <button role="tab" data-tab="overview" aria-selected="false">Overview</button>
    <button role="tab" data-tab="data" aria-selected="false">Data</button>
    <button role="tab" data-tab="devices" aria-selected="false">Devices</button>
    <button role="tab" data-tab="submit" aria-selected="false">Submit</button>
    <button role="tab" data-tab="people" aria-selected="false">People</button>
    <button role="tab" data-tab="rules" aria-selected="false">Rules</button>
  </div>
</div></div>

<div class="wrap">

<section class="panel" data-panel="leaderboard" data-open="true">
  <div id="runpanel"></div>
  <h2 class="sec">Public leaderboard</h2>
  <p class="lede">Ranked by geometric-mean speedup over the shipped baseline across
  {sweep_txt}. Rank is not the grade &mdash; full benchmark credit is earned at
  {target}&times;, and everyone can earn all of it.</p>
  <div class="tablecard"><div class="scroll"><table>
    <thead><tr><th style="width:52px">#</th><th>Submission</th><th class="num">Speedup</th>
    <th style="width:110px"></th><th>Status</th><th class="num">Median ms</th>
    <th class="num">Peak MB</th><th>Commit</th></tr></thead>
    <tbody id="lbbody">{lb_html}</tbody></table></div></div>
  <div class="note">Timings on this board come from the <strong>{html.escape(tier)}</strong>
  tier. Cloud-tier and HPC-tier numbers are produced by identical code on different
  hardware and are not comparable to each other &mdash; compare within a tier, or use
  the <a href="#devices" data-goto="devices">Devices</a> tab, where everything is a
  ratio.</div>
</section>

<section class="panel" data-panel="overview">
  <h2 class="sec">The problem</h2>
  <p class="lede">{html.escape(notes)}</p>
  <div class="grid2">
    <div class="card"><h3>What you change</h3>
      <p>Everything except the answer. The repository ships a working but deliberately
      naive C++ baseline, a correctness oracle and a fixed harness. Make it fast.</p>
      <p>Two phases, and only one is timed. <code>prepare</code> reads the raw corpus
      once and writes whatever on-disk representation you like &mdash; format, sorting,
      compression, quantisation, all free. <code>solution</code> is on the clock, end to
      end: load your representation, compute, write the result.</p></div>
    <div class="card"><h3>How it is judged</h3>
      <p><strong>Correctness is a gate.</strong> A submission that fails the oracle
      scores zero on the benchmark no matter how fast it is.</p>
      <p>Your result is quantised to {task['canon'].get('sig_digits', 9)} significant
      digits and hashed, so you may reorder, vectorise and thread freely &mdash; a
      reordered floating-point sum still hashes identically. Changing the answer does not.</p>
      <p>The leaderboard is 25 of 100 points. The other 75 are for explaining which
      change bought which gain, and why.</p></div>
  </div>
  <div class="note warn">A noisy run is not a result. Any submission whose IQR exceeds
  10% of its median is rejected rather than scored &mdash; re-run it on a quiet machine.</div>
</section>

<section class="panel" data-panel="data">
  <h2 class="sec">The corpus</h2>
  <p class="lede">pbmc3k, exactly as the <code>singlet</code> R package ships it
  (<code>singlet::get_pbmc3k_data</code>) &mdash; peripheral blood mononuclear cells from
  10x Genomics, the dataset behind the Seurat clustering tutorial.</p>
  <div class="tablecard"><div class="scroll"><table>
    <tbody>
      <tr><td>Genes</td><td class="num">13,714</td></tr>
      <tr><td>Cells</td><td class="num">2,700</td></tr>
      <tr><td>Non-zeros</td><td class="num">2,282,976</td></tr>
      <tr><td>Density</td><td class="num">6.166%</td></tr>
      <tr><td>Dense fp64, as handed to you</td><td class="num">296.2 MB</td></tr>
      <tr><td>CSR with 32-bit indices</td><td class="num">~27 MB</td></tr>
    </tbody></table></div></div>
  <p class="lede" style="margin-top:16px">The raw matrix is not in git &mdash; 296 MB has no
  business in a repository. It is rebuilt deterministically from a 4.4 MB packed copy:</p>
  {codeblock("python3 tools/make_p1_input.py --variant public --out data/" + tid + "/public.bin")}
  <div class="note"><strong>You are ranked on the public input and graded on a held-out
  one</strong> of the same distribution, released after the deadline. The held-out matrix
  is the same corpus with counts binomially thinned and rows and columns permuted, so a
  solution memorised against this specific matrix transfers nothing.</div>
</section>

<section class="panel" data-panel="devices">{dev_html}</section>

<section class="panel" data-panel="submit">
  <h2 class="sec">Run it on your machine</h2>
  <p class="lede">Everyone runs everyone's code. Your machine runs the shipped baseline
  alongside every submission and reports each one's speedup over the baseline measured
  right there, then opens a pull request with the result. You need Python 3.9+ and a
  C++17 compiler &mdash; CMake is optional.</p>

  <div class="step"><div class="no">1</div><div class="bd">
    <h4>Get on the roster</h4>
    <p>Every result belongs to somebody. Open a pull request adding yourself to
    <code>users/users.json</code>, or ask the instructor to add you. The runner refuses
    to produce a bundle for a handle it does not recognise, and CI rejects one pushed by
    an account that does not match its owner.</p></div></div>

  <div class="step"><div class="no">2</div><div class="bd">
    <h4>Fetch the runner and go</h4>
    <p>One script. It clones the repo if needed, rebuilds the corpus, collects the
    submissions, runs them all, and opens the pull request that puts your numbers on
    this page.</p>
    {codeblock(cli)}</div></div>

  <div class="step"><div class="no">3</div><div class="bd">
    <h4>On a cluster, ask for the node first</h4>
    <p>A run that shared a node with somebody else's job is a measurement of the
    scheduler, not of the code.</p>
    {codeblock("sbatch clipper/run_all.sbatch " + tid)}
    <p style="margin-top:10px">That script sets <code>--exclusive</code> and pins the node
    type with <code>--constraint</code>. Both matter. The bundle records the Slurm job id,
    partition and node list so a suspicious result can be traced.</p></div></div>

  <div class="note"><strong>What "submit" means here.</strong> This site is static files on
  a CDN &mdash; there is no server to post to. Results reach the board as commits: the
  script opens a pull request, CI checks that the owner is on the roster and matches the
  GitHub account that pushed, and the site rebuilds. That is the whole pipeline, and you
  can read every step of it.</p></div>
</section>

<section class="panel" data-panel="people">
  <h2 class="sec">Competitors</h2>
  <div class="tablecard"><div class="scroll"><table>
    <thead><tr><th>Who</th><th>Role</th><th class="num">Submissions</th>
    <th class="num">Device runs</th></tr></thead>
    <tbody>{people}</tbody></table></div></div>
  <div class="note">Administered by <strong>{html.escape(admin)}</strong>. Admin controls
  &mdash; which devices count toward the official score, who is on the roster, when the
  held-out input is released &mdash; are repository settings owned by that account and
  enforced by GitHub permissions, not by anything on this page.</div>
</section>

<section class="panel" data-panel="rules">
  <h2 class="sec">Rules</h2>
  <div class="grid2">
    <div class="card"><h3>Use any tool you like</h3><p>Agents, assistants, libraries,
      forums, each other. None of it is restricted and none of it needs disclosing. The
      presentation and the in-class assessments measure what you understand, and no tool
      can sit those for you.</p></div>
    <div class="card"><h3>Report what you measured</h3><p>Fabricating, selectively
      reporting or misattributing a performance result is the one thing this field cannot
      tolerate. If a number is uncertain, say so. If an experiment failed, present the
      failure &mdash; there are points for exactly that.</p></div>
    <div class="card"><h3>Every result has an owner</h3><p>Runs are submitted under your
      handle from your GitHub account. Submitting under someone else's is academic
      misconduct, and it is trivially visible in the commit history.</p></div>
    <div class="card"><h3>Share the cluster</h3><p>Clipper is used by researchers across
      the university. Requesting far more than you need, or leaving jobs running, takes
      resources from someone else's work.</p></div>
  </div>
</section>

<footer class="site"><div>Updated {now} &middot; handles and display names only
&middot; <a href="https://github.com/{repo}">source</a></div></footer>
</div>

<script>
const ROSTER = {json.dumps({k: {"display_name": v.get("display_name", k), "github": v.get("github", "")} for k, v in roster.items()})};
const TASK = {json.dumps(tid)};

/* ---- tabs ---- */
const tabs = [...document.querySelectorAll('[role=tab]')];
const panels = [...document.querySelectorAll('.panel')];
function show(name, push){{
  if(!panels.some(p=>p.dataset.panel===name)) name='leaderboard';
  tabs.forEach(t=>t.setAttribute('aria-selected', String(t.dataset.tab===name)));
  panels.forEach(p=>p.dataset.open = String(p.dataset.panel===name));
  if(push) history.replaceState(null,'','#'+name);
  window.scrollTo({{top:0,behavior:'instant'}});
}}
tabs.forEach(t=>t.addEventListener('click',()=>show(t.dataset.tab,true)));
document.addEventListener('click',e=>{{
  const g=e.target.closest('[data-goto]'); if(g){{e.preventDefault();show(g.dataset.goto,true);}}
}});
show((location.hash||'#leaderboard').slice(1), false);

/* ---- copy buttons ---- */
document.addEventListener('click',async e=>{{
  const b=e.target.closest('[data-copy]'); if(!b) return;
  const code=b.parentElement.querySelector('code');
  try{{ await navigator.clipboard.writeText(code.innerText); b.textContent='Copied';
        setTimeout(()=>b.textContent='Copy',1400); }}
  catch(_){{ b.textContent='Select & copy'; }}
}});

/* ---- identity (display personalisation only; see the note in People) ---- */
const KEY='hpcbench.handle';
function hue(h){{let s=0;for(let i=0;i<h.length;i++)s+=h.charCodeAt(i)*(i+7);
  return [198,172,22,268,340,44,145,300][s%8];}}
function paint(h){{
  const av=document.getElementById('idav'), nm=document.getElementById('idname');
  if(h && ROSTER[h]){{ av.textContent=h[0].toUpperCase();
    av.style.background='hsl('+hue(h)+' 52% 38%)'; nm.textContent=ROSTER[h].display_name; }}
  else {{ av.textContent='?'; av.style.background='var(--muted-mark)'; nm.textContent='Sign in'; }}
  document.querySelectorAll('#lbbody tr').forEach(tr=>
    tr.classList.toggle('me', !!h && tr.dataset.owner===h));
}}
document.getElementById('idbtn').addEventListener('click',()=>{{
  const known=Object.keys(ROSTER);
  const cur=localStorage.getItem(KEY)||'';
  const pick=prompt(
    'Enter your handle to highlight your rows on this page.\\n\\n'+
    'This is display personalisation stored in this browser only. It grants nothing:\\n'+
    'a static site cannot authorise anyone. Ownership is enforced in CI against the\\n'+
    'GitHub account that pushes a result.\\n\\n'+
    'On the roster: '+(known.join(', ')||'(nobody yet)'), cur);
  if(pick===null) return;
  if(pick==='') {{ localStorage.removeItem(KEY); paint(null); return; }}
  if(!ROSTER[pick]) {{ alert('"'+pick+'" is not on the roster. Open a pull request adding '+
    'yourself to users/users.json.'); return; }}
  localStorage.setItem(KEY,pick); paint(pick);
}});
try{{ paint(localStorage.getItem(KEY)); }}catch(_){{ paint(null); }}

/* ---- run in browser ---- */
const runbtn=document.getElementById('runbtn'), runpanel=document.getElementById('runpanel');
runbtn.addEventListener('click', async ()=>{{
  show('leaderboard', true);
  runpanel.innerHTML='<div class="card"><h3>Checking for browser builds&hellip;</h3></div>';
  let man=null;
  try{{ const r=await fetch('wasm/'+TASK+'/manifest.json',{{cache:'no-store'}});
        if(r.ok) man=await r.json(); }}catch(_){{}}
  if(!man || !man.entries || !man.entries.length){{
    runpanel.innerHTML='<div class="card"><h3>Browser runs are not built for this '+
      'competition yet</h3><p>Running a submission here means compiling it to '+
      'WebAssembly, which happens in CI. When the build lands, this button runs every '+
      'submission in your browser and shows where your machine puts them &mdash; no '+
      'install, no clone.</p><p><strong>Note the ceiling.</strong> GitHub Pages cannot '+
      'send the COOP/COEP headers WebAssembly threads require, so a browser run is '+
      'single-threaded. It compares data-structure and algorithm choices honestly and '+
      'tells you nothing about threading. For the full picture use the command-line '+
      'runner on the <a href="#submit" data-goto="submit">Submit</a> tab.</p></div>';
    return;
  }}
  const {{runAll}} = await import('./wasm/runner.mjs');
  await runAll(man, runpanel, TASK);
}});
</script>
</body></html>"""


# --------------------------------------------------------------------- index

def render_index(tasks: list[dict], roster: dict, cfg: dict, stats: dict) -> str:
    repo = cfg.get("repo", "zdebruine/cis677-hpcbench")
    cards = []
    for t in tasks:
        pm = next((m for m in t["metrics"] if m.get("primary")), t["metrics"][0])
        st = stats.get(t["id"], {})
        cards.append(f"""
<a class="card" href="{html.escape(t['id'])}.html" style="display:block;text-decoration:none;color:inherit">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
    <span class="pill p-mut mono">{html.escape(t['id'])}</span>
    {'<span class="pill p-ok">open</span>' if st.get('entries') else '<span class="pill p-mut">not started</span>'}
  </div>
  <h3 style="font-size:17px">{html.escape(t['title'])}</h3>
  <p style="color:var(--ink2);font-size:13.8px;margin:6px 0 12px">{html.escape(t.get('notes','')[:190])}</p>
  <div class="metarow" style="margin:0">
    <div class="meta"><span class="k">Full credit</span><span class="v">{pm.get('full_credit_at','&mdash;')}&times;</span></div>
    <div class="meta"><span class="k">Entries</span><span class="v">{st.get('entries',0)}</span></div>
    <div class="meta"><span class="k">Devices</span><span class="v">{st.get('devices',0)}</span></div>
  </div>
</a>""")
    now = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head>{HEAD}
<title>hpcbench &middot; CIS 677 competitions</title>
<style>{CSS}</style></head><body>
<header class="appbar"><div class="in">
  <a class="brand" href="./"><span class="mk">hb</span>hpcbench<span class="course">CIS 677</span></a>
  <nav class="appnav"><a href="./" aria-current="page">Competitions</a>
  <a href="#docs">Docs</a><a href="https://github.com/{repo}">Code</a></nav>
  <span class="spacer"></span>
</div></header>
<div class="hero"><div class="in">
  <h1>High-Performance Computing competitions</h1>
  <p class="tagline">Five problems, one dataset, seen from a different altitude each
  time. Every one ships a working but deliberately naive C++ baseline. Your job is to
  make it fast, know precisely which change bought which gain, and defend it.</p>
</div></div>
<div class="wrap" style="padding-top:26px">
  <div class="grid2">{"".join(cards)}</div>

  <h2 class="sec" id="docs">How this works</h2>
  <div class="grid2">
    <div class="card"><h3>Ratios, not milliseconds</h3><p>A time from a laptop and a time
      from a login node are not comparable. So every device runs the shipped baseline
      alongside every submission and reports speedups over <em>its own</em> baseline.
      Those ratios are what gets combined.</p></div>
    <div class="card"><h3>Everyone runs everyone's code</h3><p>Pull the runner, run the
      whole field on your machine, open a pull request. Your device joins the board with
      its specifications recorded, and you can see which wins survive a change of
      hardware and which evaporate.</p></div>
    <div class="card"><h3>Correctness is a gate</h3><p>Results are quantised and hashed,
      so you can thread and vectorise freely &mdash; a reordered floating-point sum hashes
      identically. A wrong answer scores zero at any speed.</p></div>
    <div class="card"><h3>Every result has an owner</h3><p>Submissions are made under a
      handle on the roster, from the matching GitHub account. CI refuses anything else.
      There are no anonymous numbers on this board.</p></div>
  </div>
</div>
<footer class="site"><div class="wrap" style="padding-bottom:0">Updated {now}
&middot; administered by {html.escape(cfg.get('admin_email',''))}
&middot; <a href="https://github.com/{repo}">source</a></div></footer>
</body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hpcbench-site")
    ap.add_argument("--tasks", default="tasks")
    ap.add_argument("--results", default="results")
    ap.add_argument("--scoring", default="scoring/devices.json")
    ap.add_argument("--roster", default="users/users.json")
    ap.add_argument("--out", default="_site")
    ap.add_argument("--tier", default="cloud")
    a = ap.parse_args(argv)

    with open(a.roster) as f:
        rcfg = json.load(f)
    roster = rcfg.get("users", {})
    cfg = {"admin_email": rcfg.get("admin_email", ""),
           "repo": os.environ.get("HPCBENCH_REPO", "zdebruine/cis677-hpcbench")}

    scoring, _ = load_scoring_devices(a.scoring)
    records = load_results(a.results)
    os.makedirs(a.out, exist_ok=True)

    tasks, stats = [], {}
    for path in sorted(glob.glob(os.path.join(a.tasks, "*", "task.yaml"))):
        with open(path) as f:
            task = json.load(f)
        tasks.append(task)
        bundles = load_device_bundles(a.results, task["id"])
        n = len(latest_per_handle(records, task["id"], a.tier))
        stats[task["id"]] = {"entries": n, "devices": len(bundles)}
        page = render_competition(task, records, bundles, scoring, roster, cfg,
                                  tier=a.tier)
        with open(os.path.join(a.out, task["id"] + ".html"), "w") as f:
            f.write(page)
        print(f"  {task['id']}.html  ({n} entries, {len(bundles)} device bundles)")

    idx = render_index(tasks, roster, cfg, stats)
    with open(os.path.join(a.out, "index.html"), "w") as f:
        f.write(idx)
    with open(os.path.join(a.out, "404.html"), "w") as f:
        f.write(idx)
    open(os.path.join(a.out, ".nojekyll"), "w").close()
    print(f"wrote {a.out}/ ({len(tasks)} competitions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
