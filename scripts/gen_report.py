"""End-of-day report generator: writes dashboard/reports/YYYY-MM-DD.html
(+ .pdf when chromium is available) and rebuilds reports/index.html.

Run by the daily execution session after mark-to-market:
    python scripts/gen_report.py            # today's report + index
    python scripts/gen_report.py --no-pdf   # skip the PDF step
    python scripts/gen_report.py --state DIR --date YYYY-MM-DD --out DIR
                                            # regenerate a point-in-time report

The visual system lives in scripts/theme.py, shared with gen_dashboard.py.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "dashboard", "reports")
DEFAULT_BASIS = 250.0


def arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def load(path, default):
    try:
        with open(os.path.join(ROOT, path)) as f:
            return json.load(f)
    except Exception:
        return default


def index_html() -> str:
    """Rebuild reports/index.html from whatever reports exist on disk."""
    items = sorted(glob.glob(os.path.join(OUT, "20*.html")), reverse=True)
    rows = ""
    for p in items:
        d = os.path.basename(p)[:-5]
        pdf = (f'<td class="n"><a href="{d}.pdf">pdf</a></td>'
               if os.path.exists(os.path.join(OUT, f"{d}.pdf"))
               else '<td class="n muted">—</td>')
        rows += (f'<tr><td><a href="{d}.html">{d}</a></td>'
                 f'<td class="n">end of day</td>{pdf}</tr>')
    body = f"""<div class="wrap">
<header>
  <div class="mast">
    <h1 class="name">Quant<em>firm</em></h1>
    <div class="meta"><a href="../">← the book</a></div>
  </div>
  <div class="rule"></div>
  <div class="kicker">Daily reports · {len(items)} filed</div>
</header>
<section class="card" style="margin-top:var(--s6)">
  <div class="scroll"><table>
    <tr><th>date</th><th class="n">report</th><th class="n">print</th></tr>
    {rows or '<tr><td colspan="3" class="empty">no reports yet</td></tr>'}
  </table></div>
</section>
<footer>One report per trading day, written after the book is marked to market.
Each is generated from the committed state files in the repo.</footer>
</div>"""
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta name="robots" content="noindex, nofollow">\n'
            '<meta name="color-scheme" content="light dark">\n'
            "<title>quantfirm — daily reports</title>\n"
            f"<style>{theme.page_css('../fonts/')}</style>\n</head>\n<body>\n"
            f"{body}\n</body>\n</html>\n"), len(items)


def main() -> None:
    out_dir = arg("--out", OUT)
    state_dir = arg("--state", "state")
    os.makedirs(out_dir, exist_ok=True)

    eq = load(os.path.join(state_dir, "equity_state.json"), {})
    eq_cfg = load("config/equity_live.json", {})
    kill_eq = os.path.exists(os.path.join(ROOT, state_dir, "KILL_SWITCH_EQ"))

    money, pct, dircls = theme.money, theme.pct, theme.dircls

    hist = eq.get("equity_history", [])
    # Capital added after inception raises the bar, it is not profit.
    basis = float(eq.get("cost_basis", DEFAULT_BASIS))
    added = round(basis - DEFAULT_BASIS, 2)
    today = arg("--date", datetime.now(timezone.utc).date().isoformat())
    equity = hist[-1][1] if hist else 0.0
    peak = eq.get("peak_equity", equity) or equity
    dd = equity / peak - 1 if peak else 0.0
    kill_line = float(eq_cfg.get("risk", {}).get("kill_drawdown", 0.5))

    day_base = next((v for ts, v in reversed(hist) if ts[:10] < today), basis)
    day_pl = equity - day_base
    total_pl = equity - basis

    try:
        with open(os.path.join(ROOT, state_dir, "equity_trade_log.csv")) as f:
            all_trades = list(csv.DictReader(f))
    except Exception:
        all_trades = []
    trades_today = [t for t in all_trades if t["ts"][:10] == today]

    last_px = {k: float(v) for k, v in (eq.get("last_prices") or {}).items()}
    for t in all_trades:
        last_px.setdefault(t["symbol"], float(t["price"]))

    positions = eq.get("positions", {})
    cash = eq.get("settled_cash", 0.0) + eq.get("unsettled_cash", 0.0)
    holdings = sorted(((s, q, q * last_px.get(s, 0.0)) for s, q in positions.items()),
                      key=lambda r: -r[2])
    book = sum(v for _, _, v in holdings) + cash or 1.0

    pos_rows = "".join(
        f'<tr><td class="sym">{s}</td><td class="n">{q:.6f}</td>'
        f'<td class="n">{money(last_px.get(s, 0.0))}</td>'
        f'<td class="n">{money(v)}</td><td class="n">{v / book * 100:.1f}%</td></tr>'
        for s, q, v in holdings)
    pos_rows += (f'<tr class="muted"><td class="sym">CASH</td><td class="n">—</td>'
                 f'<td class="n">—</td><td class="n">{money(cash)}</td>'
                 f'<td class="n">{cash / book * 100:.1f}%</td></tr>')

    trade_rows = "".join(
        f'<tr><td>{t["ts"][11:16]}</td><td class="sym">{t["symbol"]}</td>'
        f'<td class="side-{t["side"]}">{t["side"].upper()}</td>'
        f'<td class="n">{float(t["price"]):,.2f}</td>'
        f'<td class="n">{money(float(t["dollars"]))}</td></tr>'
        for t in trades_today)
    if not trade_rows:
        trade_rows = ('<tr><td colspan="5" class="empty">no trades — every holding '
                      'stayed inside its rank band</td></tr>')

    incidents = [i["detail"] for i in eq.get("incidents", [])
                 if i.get("ts", "")[:10] == today and i.get("detail")]
    if kill_eq:
        incidents.append("<b>equity kill switch active</b> — book flattened, trading halted")
    if eq.get("pending_order"):
        incidents.append("unresolved pending order in state")
    inc_html = "".join(f"<li>{i}</li>" for i in incidents) or \
        "<li>none — reconciliation clean, no risk limits touched</li>"

    n_pos = len(holdings)
    # the mark behind the numbers, not wall-clock — see gen_dashboard
    stamp = (datetime.fromisoformat(hist[-1][0]).strftime("%H:%M UTC")
             if hist else datetime.now(timezone.utc).strftime("%H:%M UTC"))
    pretty = datetime.fromisoformat(today).strftime("%d %B %Y")

    body = f"""<div class="wrap">
<header>
  <div class="mast">
    <h1 class="name">Quant<em>firm</em></h1>
    <div class="meta"><a href="index.html">all reports</a><a href="../">the book</a></div>
  </div>
  <div class="rule"></div>
  <div class="kicker">End of day · {pretty} · filed {stamp}</div>
</header>

<section class="hero">
  <div class="kicker">Book value at close</div>
  <span class="fig">{money(equity)}</span>
  <div class="deltas">
    {theme.delta_pill(day_pl, day_pl / day_base if day_base else 0, "today")}
    {theme.delta_pill(total_pl, total_pl / basis, "since inception")}
  </div>
  <div class="tiles">
    <div class="tile"><div class="l">Drawdown from peak</div>
      <div class="v">{"0.0%" if dd >= -0.0005 else f"{dd * 100:.1f}%"}</div>
      <div class="s">peak {money(peak)} · halt at −{kill_line:.0%}</div></div>
    <div class="tile"><div class="l">Positions</div>
      <div class="v">{n_pos}</div>
      <div class="s">{money(cash)} cash · {cash / book * 100:.1f}% of book</div></div>
    <div class="tile"><div class="l">Trades today</div>
      <div class="v">{len(trades_today)}</div>
      <div class="s">strategy {eq_cfg.get("strategy", "—")}</div></div>
  </div>
</section>

<div class="grid">
  <section class="card full">
    <h2>Equity curve <span class="n">through {today}</span></h2>
    {theme.equity_chart(hist, basis, uid="rep")}
    {theme.equity_table(hist, basis)}
  </section>

  <section class="card full">
    <h2>Positions at close</h2>
    <div class="scroll"><table>
      <tr><th>name</th><th class="n">qty</th><th class="n">mark</th>
        <th class="n">value</th><th class="n">weight</th></tr>
      {pos_rows}
    </table></div>
  </section>

  <section class="card full">
    <h2>Trades <span class="n">{today}</span></h2>
    <div class="scroll"><table>
      <tr><th>utc</th><th>name</th><th>side</th><th class="n">price</th>
        <th class="n">amount</th></tr>
      {trade_rows}
    </table></div>
  </section>

  <section class="card">
    <h2>Incidents</h2>
    <ul class="notes">{inc_html}</ul>
  </section>

  <section class="card">
    <h2>Desks</h2>
    <div class="chips">
      <span class="chip"><span class="dot-i {'live' if eq_cfg.get('enabled') and not kill_eq else 'halt'}"></span>
        equity&nbsp;<b>{'live' if eq_cfg.get('enabled') and not kill_eq else 'halted' if kill_eq else 'disabled'}</b></span>
      <span class="chip"><span class="dot-i idle"></span>crypto&nbsp;<b>no-go</b></span>
      <span class="chip"><span class="dot-i idle"></span>research&nbsp;<b>weekly, Mon</b></span>
      <span class="chip"><span class="dot-i idle"></span>risk&nbsp;<b>daily, 14:00 UTC</b></span>
    </div>
  </section>
</div>

<footer>Agent-operated systematic trading. Books and code:
<b>github.com/vinilpolepalli/quantfirm</b>. Every figure above is generated from
the committed state files — positions and cash are reconciled against the broker
before this report is written. High-risk principal mandate, documented in the
repo. Not investment advice.</footer>
</div>"""

    html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta name="robots" content="noindex, nofollow">\n'
            '<meta name="color-scheme" content="light dark">\n'
            f"<title>quantfirm EOD — {today}</title>\n"
            f"<style>{theme.page_css('../fonts/')}</style>\n</head>\n<body>\n"
            f"{body}\n</body>\n</html>\n")

    path = os.path.join(out_dir, f"{today}.html")
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
            pdf = os.path.join(out_dir, f"{today}.pdf")
            try:
                subprocess.run(
                    [chrome, "--headless", "--disable-gpu", "--no-sandbox",
                     # without a virtual-time budget the print fires before the
                     # self-hosted woff2 files load and the PDF falls back to a
                     # system mono
                     "--virtual-time-budget=5000",
                     f"--print-to-pdf={pdf}", "--no-pdf-header-footer", path],
                    capture_output=True, timeout=60, check=True)
                print(f"pdf: {pdf}")
            except Exception as e:
                print(f"pdf skipped: {e}", file=sys.stderr)
        else:
            print("pdf skipped: no chromium found", file=sys.stderr)

    if out_dir == OUT:
        idx, n = index_html()
        with open(os.path.join(OUT, "index.html"), "w") as f:
            f.write(idx)
        print(f"index: {n} reports")


if __name__ == "__main__":
    main()
