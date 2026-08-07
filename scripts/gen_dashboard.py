"""Render the firm dashboard HTML from committed state. Run by the daily
execution session after mark-to-market. Two outputs:

  python scripts/gen_dashboard.py > fragment.html
      page content only — for the claude.ai Artifact publisher, which wraps
      it in its own document skeleton (and whose CSP blocks the webfonts, so
      the fragment falls back to the system stack)

  python scripts/gen_dashboard.py --standalone > dashboard/index.html
      complete HTML document — for Vercel (or any static host), which
      serves the file raw

  python scripts/gen_dashboard.py --standalone --state DIR
      render from an alternate state directory (used to regenerate a
      point-in-time view; never writes anything back)

The visual system lives in scripts/theme.py, shared with gen_report.py.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
START = 250.0


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


def main() -> None:
    state_dir = arg("--state", "state")
    eq = load(os.path.join(state_dir, "equity_state.json"), {})
    eq_cfg = load("config/equity_live.json", {})
    kill_eq = os.path.exists(os.path.join(ROOT, state_dir, "KILL_SWITCH_EQ"))
    kill_cr = os.path.exists(os.path.join(ROOT, state_dir, "KILL_SWITCH"))

    money, pct, dircls = theme.money, theme.pct, theme.dircls

    hist = eq.get("equity_history", [])
    equity = hist[-1][1] if hist else 0.0
    peak = eq.get("peak_equity", equity) or equity
    dd = equity / peak - 1 if peak else 0.0
    kill_line = float(eq_cfg.get("risk", {}).get("kill_drawdown", 0.5))
    dd_used = min(1.0, abs(dd) / kill_line) if kill_line else 0.0

    total_pl = equity - START
    day_base = next((v for ts, v in reversed(hist[:-1])
                     if ts[:10] != hist[-1][0][:10]), START) if len(hist) > 1 else START
    day_pl = equity - day_base

    positions = eq.get("positions", {})
    try:
        with open(os.path.join(ROOT, state_dir, "equity_trade_log.csv")) as f:
            all_trades = list(csv.DictReader(f))
    except Exception:
        all_trades = []
    trades = all_trades[-8:][::-1]

    # Marked prices are authoritative; the trade log only covers recently traded
    # names, so pricing off it alone silently zeroes long-held positions.
    last_px = {k: float(v) for k, v in (eq.get("last_prices") or {}).items()}
    for t in all_trades:
        last_px.setdefault(t["symbol"], float(t["price"]))

    cash = eq.get("settled_cash", 0.0) + eq.get("unsettled_cash", 0.0)

    holdings = sorted(((s, q, q * last_px.get(s, 0.0)) for s, q in positions.items()),
                      key=lambda r: -r[2])
    book = sum(v for _, _, v in holdings) + cash or 1.0

    pos_rows = ""
    for sym, qty, val in holdings:
        w = val / book
        pos_rows += (
            f'<tr><td class="sym">{sym}</td>'
            f'<td class="n">{money(last_px.get(sym, 0.0))}</td>'
            f'<td class="n">{money(val)}</td>'
            f'<td class="n">{w * 100:.1f}%</td></tr>')
    pos_rows += (
        f'<tr class="muted"><td class="sym">CASH</td><td class="n">—</td>'
        f'<td class="n">{money(cash)}</td>'
        f'<td class="n">{cash / book * 100:.1f}%</td></tr>')

    trade_rows = "".join(
        f'<tr><td>{t["ts"][5:10]}</td><td class="sym">{t["symbol"]}</td>'
        f'<td class="side-{t["side"]}">{t["side"].upper()}</td>'
        f'<td class="n">{money(float(t["dollars"]))}</td>'
        f'<td class="n">{float(t["price"]):,.2f}</td></tr>'
        for t in trades) or '<tr><td colspan="5" class="empty">no trades yet</td></tr>'

    eq_live = bool(eq_cfg.get("enabled")) and not kill_eq
    meter_col = ("var(--loss)" if dd_used > 0.6 else
                 "var(--warn)" if dd_used > 0.3 else "var(--accent)")
    # stamp the mark the figures describe, not wall-clock: a page regenerated
    # later must not claim numbers fresher than the book behind them
    mark_ts = hist[-1][0] if hist else datetime.now(timezone.utc).isoformat()
    now = datetime.fromisoformat(mark_ts).strftime(
        "marked %d %b %Y · %H:%M UTC").upper()
    n_pos = len(holdings)
    dd_txt = "0.0%" if dd >= -0.0005 else f"{dd * 100:.1f}%"

    body = f"""<div class="wrap">
<header>
  <div class="mast">
    <h1 class="name">Quant<em>firm</em></h1>
    <div class="meta"><a href="reports/">daily reports ↗</a><span>{now}</span></div>
  </div>
  <div class="rule"></div>
  <div class="kicker">The book · agent-operated systematic equity</div>
</header>

<section class="hero">
  <div class="kicker">Book value</div>
  <span class="fig">{money(equity)}</span>
  <div class="deltas">
    {theme.delta_pill(day_pl, day_pl / day_base if day_base else 0, "today")}
    {theme.delta_pill(total_pl, total_pl / START, "since inception")}
  </div>
  <div class="line">{n_pos} position{"" if n_pos == 1 else "s"} ·
    strategy <b>{eq_cfg.get("strategy", "—")}</b> ·
    funded <b>{money(START)}</b> on {hist[0][0][:10] if hist else "—"} ·
    peak <b>{money(peak)}</b></div>
  <div class="meter">
    <div class="track"><div class="fill"
      style="width:{dd_used * 100:.1f}%;background:{meter_col}"></div></div>
    <div class="cap"><span>drawdown from peak <b>{dd_txt}</b></span>
      <span>kill switch at <b>−{kill_line:.0%}</b></span></div>
  </div>
</section>

<div class="grid">
  <section class="card full">
    <h2>Equity curve <span class="n">marked at each close</span></h2>
    {theme.equity_chart(hist, START, uid="dash")}
    {theme.equity_table(hist, START)}
  </section>

  <section class="card">
    <h2>Positions <span class="n">{n_pos} names</span></h2>
    <div class="scroll"><table>
      <tr><th>name</th><th class="n">last</th><th class="n">value</th>
        <th class="n">weight</th></tr>
      {pos_rows}
    </table></div>
  </section>

  <section class="card">
    <h2>Recent trades <span class="n">last {len(trades)}</span></h2>
    <div class="scroll"><table>
      <tr><th>date</th><th>name</th><th>side</th><th class="n">amount</th>
        <th class="n">price</th></tr>
      {trade_rows}
    </table></div>
  </section>

  <section class="card full">
    <h2>Desks</h2>
    <div class="chips">
      <span class="chip"><span class="dot-i {'live' if eq_live else 'halt'}"></span>
        equity&nbsp;<b>{'live' if eq_live else 'halted' if kill_eq else 'disabled'}</b></span>
      <span class="chip"><span class="dot-i {'halt' if kill_cr else 'idle'}"></span>
        crypto&nbsp;<b>{'halted' if kill_cr else 'no-go'}</b></span>
      <span class="chip"><span class="dot-i idle"></span>research&nbsp;<b>weekly, Mon</b></span>
      <span class="chip"><span class="dot-i idle"></span>risk&nbsp;<b>daily, 14:00 UTC</b></span>
    </div>
  </section>
</div>

<footer>Agent-operated. The book rebalances only when a holding drops out of its
momentum rank band, which works out to roughly monthly — quiet days are the
strategy working, not a stall. High-risk mandate by design: expect swings, and
the <b>−{kill_line:.0%} kill switch</b> flattens to cash and halts trading if it
trips. Every figure on this page is generated from the committed state files in
the repo; nothing here is hand-entered. Not investment advice.</footer>
</div>"""

    if "--standalone" in sys.argv:
        sys.stdout.write(
            '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta name="robots" content="noindex, nofollow">\n'
            '<meta name="color-scheme" content="light dark">\n'
            "<title>quantfirm — the book</title>\n"
            f"<style>{theme.page_css('fonts/')}</style>\n</head>\n<body>\n"
            f"{body}\n</body>\n</html>\n")
    else:
        sys.stdout.write("<title>quantfirm — the book</title>\n"
                         f"<style>{theme.page_css(None)}</style>\n{body}\n")


if __name__ == "__main__":
    main()
