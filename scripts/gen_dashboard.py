"""Render the firm dashboard HTML from committed state. Run by the daily
execution session after mark-to-market; output is published as a claude.ai
artifact (same path -> same URL every day).

Usage: python scripts/gen_dashboard.py > /path/to/quantfirm-dashboard.html
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")


def load(path, default):
    try:
        with open(os.path.join(ROOT, path)) as f:
            return json.load(f)
    except Exception:
        return default


def main() -> None:
    eq = load("state/equity_state.json", {})
    eq_cfg = load("config/equity_live.json", {})
    cr_cfg = load("config/live.json", {})
    kill_eq = os.path.exists(os.path.join(ROOT, "state/KILL_SWITCH_EQ"))
    kill_cr = os.path.exists(os.path.join(ROOT, "state/KILL_SWITCH"))

    hist = eq.get("equity_history", [])
    equity = hist[-1][1] if hist else 0.0
    peak = eq.get("peak_equity", equity) or equity
    dd = equity / peak - 1 if peak else 0.0
    kill_line = float(eq_cfg.get("risk", {}).get("kill_drawdown", 0.5))
    dd_used = min(1.0, abs(dd) / kill_line) if kill_line else 0
    start = 250.0
    total_pl = equity - start
    day_base = next((v for ts, v in reversed(hist[:-1])
                     if ts[:10] != hist[-1][0][:10]), start) if len(hist) > 1 else start
    day_pl = equity - day_base

    positions = eq.get("positions", {})
    trades = []
    try:
        with open(os.path.join(ROOT, "state/equity_trade_log.csv")) as f:
            trades = list(csv.DictReader(f))[-8:][::-1]
    except Exception:
        pass
    # last marked prices from trade log fallback: use avg prices per symbol
    last_px = {}
    for t in trades[::-1]:
        last_px[t["symbol"]] = float(t["price"])

    def money(x, sign=False):
        s = f"{abs(x):,.2f}"
        if sign:
            return ("+$" if x >= 0 else "−$") + s
        return "$" + s

    def cls(x):
        return "up" if x >= 0 else "down"

    # sparkline from equity history
    pts = [v for _, v in hist] or [start]
    if len(pts) == 1:
        pts = pts * 2
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1.0
    W, H = 320, 64
    step = W / (len(pts) - 1)
    coords = [(round(i * step, 1), round(H - 6 - (v - lo) / rng * (H - 12), 1))
              for i, v in enumerate(pts)]
    line = " ".join(f"{x},{y}" for x, y in coords)
    area = f"0,{H} " + line + f" {W},{H}"
    end_x, end_y = coords[-1]

    pos_rows = ""
    total_pos = 0.0
    for sym, qty in sorted(positions.items(), key=lambda kv: -kv[1] * last_px.get(kv[0], 0)):
        px = last_px.get(sym, 0.0)
        val = qty * px
        total_pos += val
        pos_rows += (f'<tr><td class="sym">{sym}</td><td>{qty:.6f}</td>'
                     f'<td>{money(px)}</td><td class="num">{money(val)}</td></tr>')
    cash = eq.get("settled_cash", 0.0) + eq.get("unsettled_cash", 0.0)
    pos_rows += (f'<tr class="cashrow"><td class="sym">CASH</td><td>—</td><td>—</td>'
                 f'<td class="num">{money(cash)}</td></tr>')

    trade_rows = "".join(
        f'<tr><td>{t["ts"][5:16].replace("T", " ")}</td><td class="sym">{t["symbol"]}</td>'
        f'<td class="{ "buy" if t["side"]=="buy" else "sell"}">{t["side"].upper()}</td>'
        f'<td class="num">{money(float(t["dollars"]))}</td><td>{float(t["price"]):,.2f}</td></tr>'
        for t in trades) or '<tr><td colspan="5" class="empty">no trades yet</td></tr>'

    eq_live = eq_cfg.get("enabled") and not kill_eq
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<title>quantfirm — the book</title>
<style>
:root {{
  --bg:#F4F5F3; --panel:#FFFFFF; --ink:#1B2528; --dim:#5C6B70; --faint:#D8DDDB;
  --accent:#B8860B; --gain:#1E7A52; --loss:#B03A31; --warn:#A8741F;
  --meter:#E4E7E5;
}}
@media (prefers-color-scheme: dark) {{ :root {{
  --bg:#0E1517; --panel:#151D20; --ink:#DCE3E2; --dim:#7E8F93; --faint:#243034;
  --accent:#D9A441; --gain:#3DAE7A; --loss:#D25A50; --warn:#C78A2D;
  --meter:#1D272B;
}} }}
:root[data-theme="dark"] {{
  --bg:#0E1517; --panel:#151D20; --ink:#DCE3E2; --dim:#7E8F93; --faint:#243034;
  --accent:#D9A441; --gain:#3DAE7A; --loss:#D25A50; --warn:#C78A2D; --meter:#1D272B;
}}
:root[data-theme="light"] {{
  --bg:#F4F5F3; --panel:#FFFFFF; --ink:#1B2528; --dim:#5C6B70; --faint:#D8DDDB;
  --accent:#B8860B; --gain:#1E7A52; --loss:#B03A31; --warn:#A8741F; --meter:#E4E7E5;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.45 ui-monospace,"SF Mono","Cascadia Code",Menlo,Consolas,monospace;
  font-variant-numeric: tabular-nums; }}
.wrap {{ max-width:640px; margin:0 auto; padding:20px 16px 48px; display:flex;
  flex-direction:column; gap:14px; }}
header {{ display:flex; align-items:baseline; justify-content:space-between;
  border-bottom:2px solid var(--accent); padding-bottom:10px; }}
header h1 {{ font-size:15px; margin:0; letter-spacing:.08em; }}
header h1 .tick {{ color:var(--accent); }}
.stamp {{ color:var(--dim); font-size:11px; }}
.card {{ background:var(--panel); border:1px solid var(--faint); border-radius:4px;
  padding:14px 16px; }}
.hero {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:10px 18px; }}
.hero .big {{ font-size:40px; font-weight:700; letter-spacing:-.02em; }}
.pill {{ font-size:13px; font-weight:600; padding:3px 10px; border-radius:99px; }}
.pill.up {{ background:color-mix(in srgb, var(--gain) 14%, transparent); color:var(--gain); }}
.pill.down {{ background:color-mix(in srgb, var(--loss) 14%, transparent); color:var(--loss); }}
.sub {{ width:100%; color:var(--dim); font-size:12.5px; }}
.meter {{ margin-top:10px; }}
.meter .bar {{ height:6px; background:var(--meter); border-radius:3px; overflow:hidden; }}
.meter .fill {{ height:100%; width:{dd_used*100:.1f}%; background:{'var(--loss)' if dd_used>0.6 else 'var(--warn)' if dd_used>0.3 else 'var(--gain)'};
  border-radius:3px; }}
.meter .lbl {{ display:flex; justify-content:space-between; color:var(--dim);
  font-size:11px; margin-top:4px; letter-spacing:.05em; }}
h2 {{ font-size:11.5px; letter-spacing:.14em; color:var(--dim); margin:0 0 10px;
  text-transform:uppercase; font-weight:600; }}
.tablewrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
th {{ text-align:left; color:var(--dim); font-weight:500; font-size:11px;
  letter-spacing:.08em; text-transform:uppercase; padding:0 8px 6px 0; }}
td {{ padding:5px 8px 5px 0; border-top:1px solid var(--faint); }}
td.num, th.num {{ text-align:right; padding-right:0; }}
td:last-child, th:last-child {{ text-align:right; padding-right:0; }}
.sym {{ font-weight:700; }}
.buy {{ color:var(--gain); font-weight:600; }} .sell {{ color:var(--loss); font-weight:600; }}
.cashrow td {{ color:var(--dim); }}
.empty {{ color:var(--dim); text-align:center; padding:14px 0; }}
.spark {{ display:block; width:100%; height:auto; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
.chip {{ display:flex; align-items:center; gap:7px; font-size:12.5px;
  border:1px solid var(--faint); border-radius:99px; padding:5px 12px; }}
.dot {{ width:8px; height:8px; border-radius:50%; }}
.dot.live {{ background:var(--gain); box-shadow:0 0 0 3px color-mix(in srgb, var(--gain) 22%, transparent); }}
.dot.halt {{ background:var(--loss); }}
.dot.idle {{ background:var(--dim); }}
footer {{ color:var(--dim); font-size:11.5px; line-height:1.6; }}
footer b {{ color:var(--ink); }}
</style>
<div class="wrap">
<header><h1><span class="tick">▮</span> QUANTFIRM / THE BOOK</h1>
  <span class="stamp">{now}</span></header>

<section class="card">
  <div class="hero">
    <span class="big">{money(equity)}</span>
    <span class="pill {cls(day_pl)}">{money(day_pl, sign=True)} today</span>
    <span class="pill {cls(total_pl)}">{money(total_pl, sign=True)} all-time</span>
    <span class="sub">strategy <b>{eq_cfg.get("strategy","—")}</b> · started $250.00 · peak {money(peak)}</span>
  </div>
  <div class="meter">
    <div class="bar"><div class="fill"></div></div>
    <div class="lbl"><span>drawdown {dd:.1%}</span><span>kill switch at −{kill_line:.0%}</span></div>
  </div>
</section>

<section class="card">
  <h2>Equity curve</h2>
  <svg class="spark" viewBox="0 0 {W} {H}" role="img" aria-label="equity history">
    <polygon points="{area}" fill="color-mix(in srgb, var(--accent) 12%, transparent)"/>
    <polyline points="{line}" fill="none" stroke="var(--accent)" stroke-width="1.8"/>
    <circle cx="{end_x}" cy="{end_y}" r="3" fill="var(--accent)"/>
  </svg>
</section>

<section class="card">
  <h2>Positions</h2>
  <div class="tablewrap"><table>
    <tr><th>name</th><th>qty</th><th>last</th><th class="num">value</th></tr>
    {pos_rows}
  </table></div>
</section>

<section class="card">
  <h2>Desks</h2>
  <div class="chips">
    <span class="chip"><span class="dot {'live' if eq_live else 'halt'}"></span>
      equity · {'LIVE' if eq_live else 'HALTED' if kill_eq else 'disabled'}</span>
    <span class="chip"><span class="dot {'halt' if kill_cr else 'idle'}"></span>
      crypto · {'HALTED' if kill_cr else 'NO-GO (disabled)'}</span>
    <span class="chip"><span class="dot idle"></span>research · weekly Mon</span>
    <span class="chip"><span class="dot idle"></span>risk committee · daily 14:00 UTC</span>
  </div>
</section>

<section class="card">
  <h2>Recent trades</h2>
  <div class="tablewrap"><table>
    <tr><th>time</th><th>name</th><th>side</th><th class="num">amount</th><th>price</th></tr>
    {trade_rows}
  </table></div>
</section>

<footer>Agent-operated. Rebalances only when a holding falls out of its momentum
rank band (~monthly). High-risk mandate: expect large swings; the
<b>−{kill_line:.0%} kill switch</b> flattens to cash and halts.
Books live in the repo; this page regenerates after each trading day.</footer>
</div>
"""
    sys.stdout.write(html)


if __name__ == "__main__":
    main()
