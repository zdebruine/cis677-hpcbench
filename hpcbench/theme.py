"""Visual system for the competition site. One place, so pages cannot drift."""

CSS = """
:root{
  --ground:#F4F7F9; --surface:#FFFFFF; --sunk:#EDF1F4; --raise:#FFFFFF;
  --ink:#0E1A22; --ink2:#41566A; --ink3:#6C8398; --ink4:#93A7B7;
  --rule:#DDE5EA; --rule-soft:#EAEFF3; --grid:#E6ECF0;
  --primary:#0E8FA8; --primary-ink:#0A6C80; --primary-wash:#E2F2F6;
  --gold:#9C7A16; --gold-bg:#FBF1D6;
  --silver:#69798A; --silver-bg:#EDF0F3;
  --bronze:#96552B; --bronze-bg:#F8E9DF;
  --good:#1B6B46; --good-bg:#DFF0E7;
  --warn:#8A5A12; --warn-bg:#FAEEDA;
  --crit:#993844; --crit-bg:#FADEE1;
  --muted-mark:#A9BCC9;
  --shadow:0 1px 2px rgba(14,26,34,.06), 0 6px 18px -12px rgba(14,26,34,.28);
  --ui:"Public Sans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono:"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --ground:#0B1318; --surface:#111C23; --sunk:#16232B; --raise:#182831;
  --ink:#E4EDF2; --ink2:#AFC2CE; --ink3:#7F97A6; --ink4:#5E7383;
  --rule:#22333D; --rule-soft:#1A2A33; --grid:#1E2E37;
  --primary:#3FBBD6; --primary-ink:#7FD4E7; --primary-wash:#102E37;
  --gold:#D6AC4A; --gold-bg:#2B2413;
  --silver:#9FB1BF; --silver-bg:#1E272E;
  --bronze:#C9855A; --bronze-bg:#2A1D15;
  --good:#63C295; --good-bg:#12281E;
  --warn:#D9A85C; --warn-bg:#2A2216;
  --crit:#E08A94; --crit-bg:#2C171A;
  --muted-mark:#4A6272;
  --shadow:0 1px 2px rgba(0,0,0,.5), 0 8px 24px -16px rgba(0,0,0,.9);
}}
:root[data-theme=dark]{
  --ground:#0B1318; --surface:#111C23; --sunk:#16232B; --raise:#182831;
  --ink:#E4EDF2; --ink2:#AFC2CE; --ink3:#7F97A6; --ink4:#5E7383;
  --rule:#22333D; --rule-soft:#1A2A33; --grid:#1E2E37;
  --primary:#3FBBD6; --primary-ink:#7FD4E7; --primary-wash:#102E37;
  --gold:#D6AC4A; --gold-bg:#2B2413;
  --silver:#9FB1BF; --silver-bg:#1E272E;
  --bronze:#C9855A; --bronze-bg:#2A1D15;
  --good:#63C295; --good-bg:#12281E;
  --warn:#D9A85C; --warn-bg:#2A2216;
  --crit:#E08A94; --crit-bg:#2C171A;
  --muted-mark:#4A6272;
  --shadow:0 1px 2px rgba(0,0,0,.5), 0 8px 24px -16px rgba(0,0,0,.9);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--ui);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:var(--primary-ink);text-decoration:none}
a:hover{text-decoration:underline}
a:focus-visible,button:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:4px}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.num{text-align:right;font-variant-numeric:tabular-nums;font-family:var(--mono)}

/* ---------- app bar ---------- */
.appbar{position:sticky;top:0;z-index:50;background:var(--surface);
  border-bottom:1px solid var(--rule)}
.appbar .in{max-width:1180px;margin:0 auto;padding:0 22px;height:56px;
  display:flex;align-items:center;gap:22px}
.brand{display:flex;align-items:center;gap:9px;font-weight:800;letter-spacing:-.02em;
  font-size:17px;color:var(--ink)}
.brand:hover{text-decoration:none}
.brand .mk{width:24px;height:24px;border-radius:6px;background:var(--primary);
  display:grid;place-items:center;color:#fff;font-size:12px;font-weight:800;
  font-family:var(--mono)}
.brand .course{font-weight:500;font-size:12.5px;color:var(--ink3);
  border-left:1px solid var(--rule);padding-left:10px;margin-left:2px;letter-spacing:0}
.appnav{display:flex;gap:2px;margin-left:6px}
.appnav a{padding:6px 11px;border-radius:6px;font-size:13.5px;font-weight:600;
  color:var(--ink2)}
.appnav a:hover{background:var(--sunk);text-decoration:none}
.appnav a[aria-current=page]{color:var(--primary-ink);background:var(--primary-wash)}
.spacer{flex:1}
.idchip{display:flex;align-items:center;gap:8px;border:1px solid var(--rule);
  background:var(--surface);border-radius:999px;padding:4px 6px 4px 4px;
  font-size:13px;font-weight:600;color:var(--ink2);cursor:pointer}
.idchip:hover{border-color:var(--primary)}
.av{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;
  font-family:var(--mono);font-size:11.5px;font-weight:700;color:#fff;flex:none}

/* ---------- page ---------- */
.wrap{max-width:1180px;margin:0 auto;padding:0 22px 90px}
.hero{background:var(--surface);border-bottom:1px solid var(--rule);
  padding:26px 0 0;margin-bottom:0}
.hero .in{max-width:1180px;margin:0 auto;padding:0 22px}
.crumbs{font-size:12.5px;color:var(--ink3);margin-bottom:10px}
h1{font-size:29px;font-weight:800;letter-spacing:-.025em;margin:0 0 6px;text-wrap:balance}
.tagline{color:var(--ink2);font-size:15px;max-width:70ch;margin:0 0 16px}
.metarow{display:flex;flex-wrap:wrap;gap:0 30px;margin:0 0 18px}
.meta{display:flex;flex-direction:column;gap:1px}
.meta .k{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3);
  font-weight:700}
.meta .v{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
.cta{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 20px}
.btn{display:inline-flex;align-items:center;gap:8px;border-radius:7px;padding:9px 16px;
  font-size:14px;font-weight:700;border:1px solid transparent;cursor:pointer;
  font-family:var(--ui)}
.btn-primary{background:var(--primary);color:#fff}
.btn-primary:hover{background:var(--primary-ink);text-decoration:none}
.btn-ghost{background:var(--surface);border-color:var(--rule);color:var(--ink)}
.btn-ghost:hover{border-color:var(--primary);color:var(--primary-ink);text-decoration:none}
.btn[disabled]{opacity:.5;cursor:not-allowed}

/* ---------- tabs ---------- */
.tabs{display:flex;gap:4px;overflow-x:auto;border-bottom:1px solid transparent}
.tabs button{background:none;border:0;border-bottom:2.5px solid transparent;
  padding:11px 13px;font-size:14px;font-weight:700;color:var(--ink3);cursor:pointer;
  font-family:var(--ui);white-space:nowrap}
.tabs button:hover{color:var(--ink)}
.tabs button[aria-selected=true]{color:var(--primary-ink);border-bottom-color:var(--primary)}
.panel{display:none;padding-top:26px}
.panel[data-open=true]{display:block}

/* ---------- cards & tables ---------- */
.card{background:var(--surface);border:1px solid var(--rule);border-radius:10px;
  padding:18px 20px;box-shadow:var(--shadow)}
.card+.card{margin-top:14px}
.card h3{margin:0 0 8px;font-size:16px;font-weight:700;letter-spacing:-.01em}
.card p:last-child{margin-bottom:0}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.tablecard{background:var(--surface);border:1px solid var(--rule);border-radius:10px;
  overflow:hidden;box-shadow:var(--shadow)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
thead th{text-align:left;padding:10px 14px;background:var(--sunk);
  font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink3);
  font-weight:700;border-bottom:1px solid var(--rule);white-space:nowrap}
tbody td{padding:11px 14px;border-bottom:1px solid var(--rule-soft);vertical-align:middle}
tbody tr:last-child td{border-bottom:0}
tbody tr.me{background:var(--primary-wash)}
tbody tr:hover{background:var(--sunk)}
tbody tr.me:hover{background:var(--primary-wash)}
.rank{font-family:var(--mono);font-weight:700;color:var(--ink3);width:52px}
.medal{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;
  font-size:11.5px;font-weight:800;font-family:var(--mono)}
.m1{background:var(--gold-bg);color:var(--gold)}
.m2{background:var(--silver-bg);color:var(--silver)}
.m3{background:var(--bronze-bg);color:var(--bronze)}
.who{display:flex;align-items:center;gap:10px}
.who .n{font-weight:700}
.who .sub{font-size:12px;color:var(--ink3);font-weight:500}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11.5px;
  font-weight:700;letter-spacing:.01em}
.p-ok{background:var(--good-bg);color:var(--good)}
.p-warn{background:var(--warn-bg);color:var(--warn)}
.p-bad{background:var(--crit-bg);color:var(--crit)}
.p-mut{background:var(--sunk);color:var(--ink3)}
.chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--rule);
  border-radius:999px;padding:2px 9px;font-size:11.5px;font-weight:600;color:var(--ink2);
  margin:2px 3px 2px 0;font-family:var(--mono)}
.chip .d{width:7px;height:7px;border-radius:50%;background:var(--muted-mark)}
.chip.scored .d{background:var(--primary)}
.bar{height:6px;border-radius:3px;background:var(--sunk);overflow:hidden;min-width:70px}
.bar i{display:block;height:100%;background:var(--primary);border-radius:3px}

/* ---------- code ---------- */
pre{margin:0;padding:14px 16px;background:var(--sunk);border:1px solid var(--rule);
  border-radius:8px;overflow-x:auto;font-family:var(--mono);font-size:12.8px;
  line-height:1.65;color:var(--ink)}
code{font-family:var(--mono);font-size:.9em;background:var(--sunk);padding:.1em .35em;
  border-radius:4px}
pre code{background:none;padding:0;font-size:1em}
.codeblock{position:relative}
.copy{position:absolute;top:8px;right:8px;background:var(--surface);
  border:1px solid var(--rule);border-radius:6px;padding:4px 9px;font-size:11.5px;
  font-weight:700;color:var(--ink2);cursor:pointer;font-family:var(--ui)}
.copy:hover{border-color:var(--primary);color:var(--primary-ink)}
.step{display:flex;gap:14px;margin-bottom:20px}
.step .no{flex:none;width:26px;height:26px;border-radius:50%;background:var(--primary-wash);
  color:var(--primary-ink);display:grid;place-items:center;font-weight:800;font-size:13px;
  font-family:var(--mono)}
.step .bd{flex:1;min-width:0}
.step h4{margin:2px 0 8px;font-size:15px;font-weight:700}

.note{border-left:3px solid var(--primary);background:var(--primary-wash);
  border-radius:0 8px 8px 0;padding:12px 16px;margin:14px 0;font-size:13.8px;color:var(--ink2)}
.note.warn{border-left-color:var(--warn);background:var(--warn-bg)}
.note strong{color:var(--ink)}
.empty{text-align:center;padding:44px 20px;color:var(--ink3)}
.empty .big{font-size:30px;margin-bottom:8px;opacity:.5}
h2.sec{font-size:19px;font-weight:800;letter-spacing:-.015em;margin:28px 0 12px}
h2.sec:first-child{margin-top:0}
.lede{color:var(--ink2);max-width:72ch;margin:0 0 16px}
.legend{display:flex;gap:16px;flex-wrap:wrap;align-items:center;font-size:12.5px;
  color:var(--ink2);margin:0 0 10px}
.rowlab{font:700 12.5px var(--mono);fill:var(--ink2)}
.ax{font:11.5px var(--mono);fill:var(--ink3)}
footer.site{border-top:1px solid var(--rule);margin-top:44px;padding:22px 0;
  font-size:12.5px;color:var(--ink3)}
@media (max-width:760px){
  .appbar .in{gap:12px}.appnav{display:none}
  h1{font-size:23px}.metarow{gap:0 18px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

HEAD = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
"""
