"""Shared visual system for the two generated surfaces (dashboard + EOD report).

Both used to carry their own near-duplicate stylesheet, which is how they drifted
apart. Everything visual now lives here: tokens, base CSS, the equity chart, and
the number formatters.

Design constraints this file encodes:
  * every colour is an OKLCH custom property — no inline hex anywhere downstream
  * a 4pt spacing scale, referenced by name
  * two faces: Instrument Serif for identity (masthead, section heads only),
    JetBrains Mono for every number and label. The hero figure stays in the mono
    face — a serif hero reads as decoration on a page whose subject is numbers.
  * light and dark are separately chosen steps, not an inverted flip
  * charts: 2px line, 10% area wash, solid hairline rules, labels only on the
    points that carry the story (last, peak, cost basis)
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# fonts
# --------------------------------------------------------------------------

def font_face(base: str) -> str:
    """@font-face block. `base` is the URL prefix to dashboard/fonts/.

    Returns "" when base is None — the fragment build (claude.ai Artifact) has a
    CSP that blocks any subresource, so it falls through to the system stack.
    """
    if not base:
        return ""
    return f"""
@font-face {{ font-family:"Instrument Serif"; src:url("{base}instrument-serif-400.woff2") format("woff2");
  font-weight:400; font-style:normal; font-display:swap; }}
@font-face {{ font-family:"JetBrains Mono"; src:url("{base}jetbrains-mono-400.woff2") format("woff2");
  font-weight:400; font-style:normal; font-display:swap; }}
@font-face {{ font-family:"JetBrains Mono"; src:url("{base}jetbrains-mono-500.woff2") format("woff2");
  font-weight:500; font-style:normal; font-display:swap; }}
@font-face {{ font-family:"JetBrains Mono"; src:url("{base}jetbrains-mono-700.woff2") format("woff2");
  font-weight:700; font-style:normal; font-display:swap; }}
"""


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------

_LIGHT = """
  --page:      oklch(0.977 0.007 92);
  --card:      oklch(1 0 0);
  --sunk:      oklch(0.955 0.008 92);
  --ink-1:     oklch(0.245 0.018 250);
  --ink-2:     oklch(0.395 0.016 250);
  --ink-3:     oklch(0.480 0.014 250);
  --rule:      oklch(0.895 0.008 250);
  --rule-soft: oklch(0.935 0.006 250);
  --accent:    oklch(0.545 0.125 58);
  --accent-w:  oklch(0.925 0.038 70);
  --gain:      oklch(0.505 0.125 156);
  --gain-w:    oklch(0.930 0.045 156);
  --loss:      oklch(0.520 0.170 27);
  --loss-w:    oklch(0.930 0.050 27);
  --warn:      oklch(0.600 0.125 76);
"""

_DARK = """
  --page:      oklch(0.168 0.012 250);
  --card:      oklch(0.212 0.014 250);
  --sunk:      oklch(0.188 0.013 250);
  --ink-1:     oklch(0.930 0.008 250);
  --ink-2:     oklch(0.775 0.012 250);
  --ink-3:     oklch(0.605 0.015 250);
  --rule:      oklch(0.310 0.016 250);
  --rule-soft: oklch(0.258 0.014 250);
  --accent:    oklch(0.790 0.115 68);
  --accent-w:  oklch(0.268 0.030 68);
  --gain:      oklch(0.760 0.135 157);
  --gain-w:    oklch(0.310 0.055 157);
  --loss:      oklch(0.688 0.155 25);
  --loss-w:    oklch(0.300 0.058 25);
  --warn:      oklch(0.790 0.115 80);
"""

_PRINT = """
  --page:#fff; --card:#fff; --sunk:#fff;
  --ink-1:#14181c; --ink-2:#4a5157; --ink-3:#6b7278;
  --rule:#c6cbd0; --rule-soft:#e2e6e9;
  --accent:oklch(0.480 0.125 58);  --accent-w:oklch(0.900 0.040 70);
  --gain:oklch(0.470 0.125 156);   --gain-w:oklch(0.915 0.048 156);
  --loss:oklch(0.480 0.170 27);    --loss-w:oklch(0.915 0.052 27);
  --warn:oklch(0.560 0.125 76);
"""

TOKENS = f"""
:root {{
{_LIGHT}
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
  --s7:48px; --s8:72px;
  --r-sm:6px; --r-md:10px; --r-lg:14px;
  --mono:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --display:"Instrument Serif",Georgia,"Times New Roman",serif;
  --ease-out:cubic-bezier(.22,.61,.36,1);
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{{_DARK}}} }}
:root[data-theme="dark"] {{{_DARK}}}
:root[data-theme="light"] {{{_LIGHT}}}
@media print {{ :root {{{_PRINT}}} }}
"""


# --------------------------------------------------------------------------
# base stylesheet
# --------------------------------------------------------------------------

BASE = """
*,*::before,*::after { box-sizing:border-box; }
html,body { overflow-x:clip; }
body {
  margin:0; background:var(--page); color:var(--ink-1);
  font:400 14px/1.55 var(--mono);
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
.wrap { max-width:860px; margin:0 auto; padding:var(--s6) var(--s4) var(--s8); }

/* ---- masthead ---------------------------------------------------------- */
.mast { display:flex; align-items:flex-end; justify-content:space-between;
  gap:var(--s4); flex-wrap:wrap; }
.mast .name { font:400 34px/1 var(--display); letter-spacing:.005em;
  margin:0; color:var(--ink-1); }
.mast .name em { font-style:normal; color:var(--accent); }
.mast .meta { font-size:11px; color:var(--ink-3); letter-spacing:.06em;
  text-transform:uppercase; display:flex; gap:var(--s3); align-items:center;
  flex-wrap:wrap; }
.rule { height:1px; background:var(--ink-1); margin:var(--s3) 0 var(--s2); }
.rule.thin { background:var(--rule); }
.kicker { font-size:10.5px; letter-spacing:.22em; text-transform:uppercase;
  color:var(--ink-3); }

a { color:var(--ink-2); text-decoration:none;
  border-bottom:1px solid var(--rule); padding-bottom:1px;
  transition:color .16s var(--ease-out), border-color .16s var(--ease-out); }
a:hover { color:var(--accent); border-bottom-color:var(--accent); }
a:active { color:var(--accent); opacity:.75; }
a:focus-visible { outline:2px solid var(--accent); outline-offset:3px;
  border-radius:2px; border-bottom-color:transparent; }

/* ---- hero -------------------------------------------------------------- */
.hero { margin:var(--s6) 0 var(--s5); }
.hero .fig { font:700 clamp(46px,10vw,76px)/1 var(--mono);
  letter-spacing:-.045em; display:block; margin:var(--s2) 0 var(--s4); }
.deltas { display:flex; gap:var(--s2); flex-wrap:wrap; align-items:center; }
.pill { display:inline-flex; align-items:center; gap:var(--s2);
  font-size:12.5px; font-weight:500; padding:5px 11px 5px 9px;
  border-radius:999px; white-space:nowrap; }
.pill .arw { font-size:10px; line-height:1; }
.pill.up   { background:var(--gain-w); color:var(--gain); }
.pill.down { background:var(--loss-w); color:var(--loss); }
.pill .per { color:inherit; opacity:.72; }
.hero .line { margin-top:var(--s4); font-size:12.5px; color:var(--ink-2); }
.hero .line b { color:var(--ink-1); font-weight:500; }

/* ---- drawdown meter ---------------------------------------------------- */
.meter { margin-top:var(--s5); max-width:520px; }
.meter .track { height:6px; border-radius:999px; background:var(--accent-w);
  position:relative; overflow:hidden; }
.meter .fill { position:absolute; inset:0 auto 0 0; border-radius:999px; }
.meter .cap { display:flex; justify-content:space-between; gap:var(--s3);
  font-size:11px; color:var(--ink-3); margin-top:var(--s2);
  letter-spacing:.04em; }
.meter .cap b { color:var(--ink-2); font-weight:500; }

/* ---- stat tiles -------------------------------------------------------- */
.tiles { display:grid; gap:var(--s3); margin-top:var(--s5);
  grid-template-columns:repeat(3,minmax(0,1fr)); }
@media (max-width:560px) { .tiles { grid-template-columns:minmax(0,1fr); } }
.tile { background:var(--sunk); border:1px solid var(--rule-soft);
  border-radius:var(--r-sm); padding:var(--s3) var(--s4) var(--s4); }
.tile .l { font-size:10px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-3); }
.tile .v { font:500 24px/1.15 var(--mono); letter-spacing:-.03em;
  margin-top:var(--s2); }
.tile .s { font-size:11px; color:var(--ink-3); margin-top:var(--s1); }
.tile .v.up { color:var(--gain); } .tile .v.down { color:var(--loss); }

/* ---- layout ------------------------------------------------------------ */
.grid { display:grid; gap:var(--s4); margin-top:var(--s6);
  grid-template-columns:repeat(2,minmax(0,1fr)); }
.grid .full { grid-column:1 / -1; }
@media (max-width:720px) { .grid { grid-template-columns:minmax(0,1fr); } }

.card { background:var(--card); border:1px solid var(--rule-soft);
  border-radius:var(--r-md); padding:var(--s5) var(--s5) var(--s4); }
.card > h2 { font:400 17px/1.2 var(--display); margin:0 0 var(--s4);
  color:var(--ink-1); letter-spacing:.01em; }
.card > h2 .n { font:500 10.5px/1 var(--mono); color:var(--ink-3);
  letter-spacing:.16em; text-transform:uppercase; margin-left:var(--s2);
  vertical-align:.28em; }

/* ---- tables ------------------------------------------------------------ */
.scroll { overflow-x:auto; margin:0 calc(var(--s5) * -1); padding:0 var(--s5); }
table { width:100%; border-collapse:collapse; font-size:13px;
  font-variant-numeric:tabular-nums; }
th { text-align:left; font-weight:500; font-size:10px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--ink-3); padding:0 var(--s3) var(--s2) 0;
  white-space:nowrap; }
td { padding:var(--s2) var(--s3) var(--s2) 0; border-top:1px solid var(--rule-soft);
  white-space:nowrap; }
th.n, td.n { text-align:right; padding-right:0; }
tr:last-child td { padding-bottom:0; }
.sym { font-weight:700; letter-spacing:.01em; }
.muted td { color:var(--ink-3); }
.side-buy  { color:var(--gain); font-weight:500; }
.side-sell { color:var(--loss); font-weight:500; }
.empty { color:var(--ink-3); text-align:center; padding:var(--s5) 0;
  white-space:normal; }

/* ---- chart ------------------------------------------------------------- */
.chart { display:block; width:100%; height:auto; overflow:visible; }
.chart .axis   { stroke:var(--rule); stroke-width:1; }
.chart .basis  { stroke:var(--ink-3); stroke-width:1; }
.chart .lbl    { fill:var(--ink-3); font:400 10px var(--mono); letter-spacing:.04em; }
.chart .val    { fill:var(--ink-1); font:500 11.5px var(--mono); }
.chart .series { fill:none; stroke:var(--accent); stroke-width:2;
  stroke-linejoin:round; stroke-linecap:round; }
.chart .wash   { fill:var(--accent); opacity:.10; }
.chart .dot    { fill:var(--accent); stroke:var(--card); stroke-width:2; }
.chart .hit    { fill:transparent; }
.chart .hit:hover + .peek, .chart .hit:focus-visible + .peek { opacity:1; }
.chart .peek   { opacity:0; transition:opacity .12s var(--ease-out); }
.chart .peek circle { fill:var(--accent); stroke:var(--card); stroke-width:2; }
.chart .hit:focus-visible { outline:none; }
@media (prefers-reduced-motion: reduce) {
  * { transition-duration:.01ms !important; animation-duration:.01ms !important; }
}

details.table-twin { margin-top:var(--s4); }
details.table-twin summary { font-size:11px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--ink-3); cursor:pointer;
  list-style:none; display:inline-block; border-bottom:1px solid var(--rule);
  padding-bottom:2px; }
details.table-twin summary::-webkit-details-marker { display:none; }
details.table-twin summary:hover { color:var(--accent); border-color:var(--accent); }
details.table-twin summary:focus-visible { outline:2px solid var(--accent);
  outline-offset:3px; }
details.table-twin table { margin-top:var(--s3); }

/* ---- desk chips -------------------------------------------------------- */
.chips { display:flex; flex-wrap:wrap; gap:var(--s2); }
.chip { display:inline-flex; align-items:center; gap:var(--s2); font-size:12px;
  border:1px solid var(--rule); border-radius:999px; padding:5px 12px 5px 10px;
  color:var(--ink-2); }
.chip b { color:var(--ink-1); font-weight:500; }
.dot-i { width:7px; height:7px; border-radius:50%; flex:none; }
.dot-i.live { background:var(--gain);
  box-shadow:0 0 0 3px color-mix(in oklab, var(--gain) 20%, transparent); }
.dot-i.halt { background:var(--loss); }
.dot-i.idle { background:var(--ink-3); }

/* ---- notes / footer ---------------------------------------------------- */
ul.notes { margin:0; padding-left:1.15em; font-size:13px; color:var(--ink-2); }
ul.notes li { margin-bottom:var(--s1); }
ul.notes li::marker { color:var(--ink-3); }
footer { margin-top:var(--s7); padding-top:var(--s4);
  border-top:1px solid var(--rule); font-size:11.5px; line-height:1.7;
  color:var(--ink-3); max-width:68ch; }
footer b { color:var(--ink-2); font-weight:500; }
@media print { .card { border-color:var(--rule); break-inside:avoid; }
  .wrap { padding:0; max-width:none; } a { border-bottom:none; } }
"""


def page_css(font_base: str | None) -> str:
    return font_face(font_base) + TOKENS + BASE


# --------------------------------------------------------------------------
# formatters
# --------------------------------------------------------------------------

def money(x: float, sign: bool = False) -> str:
    s = f"{abs(x):,.2f}"
    if sign:
        return ("+$" if x >= 0 else "−$") + s
    return "$" + s


def pct(x: float, dp: int = 2) -> str:
    return f"{'+' if x >= 0 else '−'}{abs(x) * 100:.{dp}f}%"


def dircls(x: float) -> str:
    return "up" if x >= 0 else "down"


def delta_pill(amount: float, share: float, label: str) -> str:
    """Signed money + its percentage, against a named period."""
    c = dircls(amount)
    arrow = "▲" if amount >= 0 else "▼"
    return (f'<span class="pill {c}"><span class="arw">{arrow}</span>'
            f'{money(amount, True)} <span class="per">{pct(share)} {label}</span></span>')


# --------------------------------------------------------------------------
# equity chart
# --------------------------------------------------------------------------

def equity_chart(hist, cost_basis: float, width: int = 760, height: int = 250,
                 uid: str = "eq") -> str:
    """Single-series equity curve.

    One series, so no legend — the card heading names what is plotted. Labels
    ride only the points that carry the story: the last mark, the peak (when it
    is not the last mark), and the cost-basis rule. Everything else is reachable
    from the hover peek and the table twin the caller renders beneath.
    """
    pts = [(ts[:10], float(v)) for ts, v in hist] or [("", cost_basis)]
    if len(pts) == 1:
        pts = pts * 2

    vals = [v for _, v in pts] + [cost_basis]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.18 or max(1.0, hi * 0.02)
    lo, hi = lo - pad, hi + pad
    span = hi - lo

    L, R, T, B = 46, 92, 22, 30          # right pad holds the end label
    pw, ph = width - L - R, height - T - B
    step = pw / (len(pts) - 1)

    def X(i):
        return round(L + i * step, 2)

    def Y(v):
        return round(T + (hi - v) / span * ph, 2)

    coords = [(X(i), Y(v)) for i, (_, v) in enumerate(pts)]
    line = " ".join(f"{x},{y}" for x, y in coords)
    base_y = round(T + ph, 2)
    area = f"{coords[0][0]},{base_y} " + line + f" {coords[-1][0]},{base_y}"

    ex, ey = coords[-1]
    last_v = pts[-1][1]
    peak_i = max(range(len(pts)), key=lambda i: pts[i][1])
    peak_v = pts[peak_i][1]

    # peak marker only when it isn't already the labelled endpoint
    peak_svg = ""
    if peak_i != len(pts) - 1 and peak_v > last_v:
        px, py = coords[peak_i]
        anchor = "middle" if L + 40 < px < L + pw - 40 else ("start" if px <= L + 40 else "end")
        peak_svg = (f'<circle cx="{px}" cy="{py}" r="3" fill="var(--accent)"/>'
                    f'<text class="lbl" x="{px}" y="{py - 10:.2f}" '
                    f'text-anchor="{anchor}">peak {money(peak_v)}</text>')

    by = Y(cost_basis)
    hits = ""
    for i, ((d, v), (x, y)) in enumerate(zip(pts, coords)):
        hits += (
            f'<g><rect class="hit" x="{x - step/2:.2f}" y="{T}" '
            f'width="{step:.2f}" height="{ph:.2f}" tabindex="0" role="img" '
            f'aria-label="{d}: {money(v)}"><title>{d} · {money(v)}</title></rect>'
            f'<g class="peek"><circle cx="{x}" cy="{y}" r="4.5"/></g></g>')

    return f"""<svg class="chart" viewBox="0 0 {width} {height}"
  role="img" aria-label="Equity history, {pts[0][0]} to {pts[-1][0]}">
  <polygon class="wash" points="{area}"/>
  <line class="axis" x1="{L}" y1="{base_y}" x2="{L + pw:.2f}" y2="{base_y}"/>
  <line class="basis" x1="{L}" y1="{by}" x2="{L + pw:.2f}" y2="{by}"/>
  <text class="lbl" x="{L - 6}" y="{by + 3.5:.2f}" text-anchor="end">{money(cost_basis)}</text>
  <text class="lbl" x="{L - 6}" y="{by + 15:.2f}" text-anchor="end">basis</text>
  <polyline class="series" points="{line}"/>
  {peak_svg}
  <circle class="dot" cx="{ex}" cy="{ey}" r="4.5"/>
  <text class="val" x="{ex + 12:.2f}" y="{ey + 4:.2f}">{money(last_v)}</text>
  <text class="lbl" x="{L}" y="{height - 10}">{pts[0][0]}</text>
  <text class="lbl" x="{L + pw:.2f}" y="{height - 10}" text-anchor="end">{pts[-1][0]}</text>
  {hits}
</svg>"""


def equity_table(hist, cost_basis: float) -> str:
    rows = "".join(
        f'<tr><td>{ts[:10]}</td><td class="n">{money(float(v))}</td>'
        f'<td class="n">{pct(float(v) / cost_basis - 1)}</td></tr>'
        for ts, v in hist)
    return (f'<details class="table-twin"><summary>data table</summary>'
            f'<table><tr><th>mark date</th><th class="n">book value</th>'
            f'<th class="n">vs basis</th></tr>{rows}</table></details>')
