"""End-of-day report generator: writes dashboard/reports/YYYY-MM-DD.html
(+ .pdf when chromium is available) and rebuilds reports/index.html.

Run by the daily execution session after mark-to-market:
    python scripts/gen_report.py            # today's report + index
    python scripts/gen_report.py --no-pdf   # skip the PDF step
"""

from __future__ import annotations

import csv
import glob
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "dashboard", "reports")

CSS = """
:root { --bg:#F4F5F3; --panel:#FFF; --ink:#1B2528; --dim:#5C6B70; --faint:#D8DDDB;
  --accent:#B8860B; --gain:#1E7A52; --loss:#B03A31; }
@media (prefers-color-scheme: dark) { :root { --bg:#0E1517; --panel:#151D20;
  --ink:#DCE3E2; --dim:#7E8F93; --faint:#243034; --accent:#D9A441;
  --gain:#3DAE7A; --loss:#D25A50; } }
@media print { :root { --bg:#FFF; --panel:#FFF; --ink:#111; --dim:#555;
  --faint:#CCC; --accent:#8a6508; --gain:#1E7A52; --loss:#B03A31; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:14px/1.55 ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums; }
.wrap { max-width:680px; margin:0 auto; padding:28px 20px 48px; }
h1 { font-size:16px; letter-spacing:.08em; border-bottom:2px solid var(--accent);
  padding-bottom:10px; margin:0 0 4px; }
h1 span { color:var(--accent); }
.date { color:var(--dim); font-size:12px; margin-bottom:22px; }
h2 { font-size:11.5px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--dim); margin:24px 0 8px; }
table { width:100%; border-collapse:collapse; font-size:13.5px; }
th { text-align:left; color:var(--dim); font-weight:500; font-size:11px;
  letter-spacing:.08em; text-transform:uppercase; padding:0 8px 6px 0; }
td { padding:5px 8px 5px 0; border-top:1px solid var(--faint); }
td:last-child, th:last-child { text-align:right; padding-right:0; }
.k { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
  gap:10px; margin:14px 0; }
.k div { background:var(--panel); border:1px solid var(--faint); border-radius:4px;
  padding:10px 12px; }
.k .l { color:var(--dim); font-size:10.5px; letter-spacing:.1em;
  text-transform:uppercase; }
.k .v { font-size:19px; font-weight:700; margin-top:2px; }
.up { color:var(--gain); } .down { color:var(--loss); }
.sym { font-weight:700; }
p, li { max-width:65ch; }
footer { margin-top:28px; color:var(--dim); font-size:11.5px;
  border-top:1px solid var(--faint); padding-top:12px; }
a { color:var(--accent); }
"""


def load(path, default):
    try:
        with open(os.path.join(ROOT, path)) as f:
            return json.load(f)
    except Exception:
        return default


def money(x, sign=False):
    s = f"{abs(x):,.2f}"
    return (("+$" if x >= 0 else "−$") + s) if sign else "$" + s


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    eq = load("state/equity_state.json", {})
    eq_cfg = load("config/equity_live.json", {})
    kill_eq = os.path.exists(os.path.join(ROOT, "state/KILL_SWITCH_EQ"))

    today = datetime.now(timezone.utc).date().isoformat()
    hist = eq.get("equity_history", [])
    equity = hist[-1][1] if hist else 0.0
    peak = eq.get("peak_equity", equity) or equity
    dd = equity / peak - 1 if peak else 0.0
    day_base = next((v for ts, v in reversed(hist) if ts[:10] < today), 250.0)
    day_pl = equity - day_base
    total_pl = equity - 250.0

    trades_today = []
    try:
        with open(os.path.join(ROOT, "state/equity_trade_log.csv")) as f:
            trades_today = [t for t in csv.DictReader(f) if t["ts"][:10] == today]
    except Exception:
        pass
    last_px = {k: float(v) for k, v in (eq.get("last_prices") or {}).items()}
    try:
        with open(os.path.join(ROOT, "state/equity_trade_log.csv")) as f:
            for t in csv.DictReader(f):
                last_px.setdefault(t["symbol"], float(t["price"]))
    except Exception:
        pass

    positions = eq.get("positions", {})
    pos_rows = "".join(
        f'<tr><td class="sym">{s}</td><td>{q:.6f}</td>'
        f'<td>{money(q * last_px.get(s, 0.0))}</td></tr>'
        for s, q in sorted(positions.items(),
                           key=lambda kv: -kv[1] * last_px.get(kv[0], 0)))
    cash = eq.get("settled_cash", 0.0) + eq.get("unsettled_cash", 0.0)
    trade_rows = "".join(
        f'<tr><td>{t["ts"][11:16]}</td><td class="sym">{t["symbol"]}</td>'
        f'<td>{t["side"].upper()}</td><td>{float(t["price"]):,.2f}</td>'
        f'<td>{money(float(t["dollars"]))}</td></tr>'
        for t in trades_today) or "<tr><td colspan=5>no trades</td></tr>"

    incidents = []
    if kill_eq:
        incidents.append("EQUITY KILL SWITCH ACTIVE — book flattened/halting")
    if eq.get("pending_order"):
        incidents.append("unresolved pending order in state")
    inc_html = ("".join(f"<li>{i}</li>" for i in incidents)
                if incidents else "<li>none — all systems normal</li>")

    def pl_cls(x):
        return "up" if x >= 0 else "down"

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>quantfirm EOD report — {today}</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1><span>▮</span> QUANTFIRM — END OF DAY REPORT</h1>
<div class="date">{today} · generated {datetime.now(timezone.utc).strftime("%H:%M UTC")}
 · <a href="index.html">all reports</a> · <a href="../">dashboard</a></div>
<div class="k">
  <div><div class="l">Book value</div><div class="v">{money(equity)}</div></div>
  <div><div class="l">Day P&amp;L</div><div class="v {pl_cls(day_pl)}">{money(day_pl, True)}</div></div>
  <div><div class="l">All-time P&amp;L</div><div class="v {pl_cls(total_pl)}">{money(total_pl, True)}</div></div>
  <div><div class="l">Drawdown</div><div class="v">{dd:.2%}</div></div>
</div>
<h2>Positions at close</h2>
<table><tr><th>name</th><th>qty</th><th>value</th></tr>{pos_rows}
<tr><td class="sym">CASH</td><td>—</td><td>{money(cash)}</td></tr></table>
<h2>Trades today</h2>
<table><tr><th>time (utc)</th><th>name</th><th>side</th><th>price</th><th>amount</th></tr>
{trade_rows}</table>
<h2>Incidents</h2><ul>{inc_html}</ul>
<h2>Desks</h2>
<ul>
<li>equity — {'LIVE' if eq_cfg.get('enabled') and not kill_eq else 'HALTED' if kill_eq else 'disabled'}
 · strategy {eq_cfg.get('strategy','—')} · kill switch at −{float(eq_cfg.get('risk',{}).get('kill_drawdown',0.5)):.0%}</li>
<li>crypto — disabled (tournament NO-GO stands)</li>
<li>research — weekly review Mondays · risk committee daily</li>
</ul>
<footer>Agent-operated systematic trading · books and code:
github.com/vinilpolepalli/2-3-24VEX · not investment advice, high-risk
principal mandate documented in the repo.</footer>
</div></body></html>"""

    path = os.path.join(OUT, f"{today}.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"report: {path}")

    if "--no-pdf" not in sys.argv:
        chrome = None
        for pat in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",):
            hits = glob.glob(pat)
            if hits:
                chrome = hits[0]
                break
        chrome = chrome or shutil.which("chromium") or shutil.which("chromium-browser")
        if chrome:
            pdf = os.path.join(OUT, f"{today}.pdf")
            try:
                subprocess.run(
                    [chrome, "--headless", "--disable-gpu", "--no-sandbox",
                     f"--print-to-pdf={pdf}", "--no-pdf-header-footer", path],
                    capture_output=True, timeout=60, check=True)
                print(f"pdf: {pdf}")
            except Exception as e:
                print(f"pdf skipped: {e}", file=sys.stderr)
        else:
            print("pdf skipped: no chromium found", file=sys.stderr)

    # rebuild index
    items = sorted(glob.glob(os.path.join(OUT, "20*.html")), reverse=True)
    rows = ""
    for p in items:
        d = os.path.basename(p)[:-5]
        pdf_link = (f' · <a href="{d}.pdf">pdf</a>'
                    if os.path.exists(os.path.join(OUT, f"{d}.pdf")) else "")
        rows += f'<tr><td><a href="{d}.html">{d}</a>{pdf_link}</td></tr>'
    index = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>quantfirm — daily reports</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1><span>▮</span> QUANTFIRM — DAILY REPORTS</h1>
<div class="date"><a href="../">← dashboard</a></div>
<table><tr><th>report</th></tr>{rows}</table>
</div></body></html>"""
    with open(os.path.join(OUT, "index.html"), "w") as f:
        f.write(index)
    print(f"index: {len(items)} reports")


if __name__ == "__main__":
    main()
