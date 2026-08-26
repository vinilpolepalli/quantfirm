"""Render the options paper desk dashboard from committed state.

  python scripts/gen_options_dashboard.py            # writes dashboard/options.html

Same visual system as the main dashboard (scripts/theme.py). Everything on the
page is generated from state/options_paper_state.json; nothing is hand-entered.
This desk is a PAPER SIMULATION — the page says so loudly on purpose.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "dashboard", "options.html")


def main() -> None:
    with open(os.path.join(ROOT, "state", "options_paper_state.json")) as f:
        st = json.load(f)

    money, pct = theme.money, theme.pct
    bank = float(st["bankroll_usd"])
    equity = float(st["equity"])
    hist = [(h["date"], float(h["equity"])) for h in st["history"]]

    total_pl = equity - bank
    day_base = hist[-2][1] if len(hist) > 1 else bank
    day_pl = equity - day_base

    opens = [p for p in st["positions"] if p["status"] == "open"]
    closed = [p for p in st["positions"] if p["status"] == "closed"]

    # drawdown ladder: entries halt at 75% of bankroll, flatten at 50%
    halt_lv, flat_lv = 0.75 * bank, 0.50 * bank
    used = min(1.0, max(0.0, (bank - equity) / (bank - flat_lv))) if equity < bank else 0.0
    meter_col = ("var(--loss)" if equity < halt_lv else
                 "var(--warn)" if used > 0.3 else "var(--accent)")

    # cost meter — the number this desk exists to measure
    slip = sum(float(p.get("entry_slippage", 0)) * 100 * p["qty"] for p in st["positions"])
    slip += sum((float(p.get("exit_debit", 0)) - float(p.get("exit_net_mid", 0))) * 100 * p["qty"]
                for p in closed)
    fees = sum(float(p.get("fees_open", 0)) + float(p.get("fees_close", 0))
               for p in st["positions"])

    def pos_row(p):
        mark = p.get("mark")
        mark_txt = "stale" if mark is None else f"{mark:.2f}"
        unrl = (p["entry_credit"] - (mark if mark is not None else p["entry_credit"])) \
            * 100 * p["qty"] - p["fees_open"]
        return (
            f'<tr><td class="sym">{p["id"]}</td>'
            f'<td>−{p["short"]["strike"]:.0f}P/+{p["long"]["strike"]:.0f}P {p["short"]["expiry"][5:]}</td>'
            f'<td class="n">{p["dte"]}</td>'
            f'<td class="n">{p["entry_credit"]:.2f}</td>'
            f'<td class="n">{mark_txt}</td>'
            f'<td class="n">{money(unrl, True)}</td></tr>')

    pos_rows = "".join(pos_row(p) for p in opens) \
        or '<tr><td colspan="6" class="empty">no open positions</td></tr>'

    closed_rows = "".join(
        f'<tr><td>{p["closed"][5:]}</td><td class="sym">{p["id"]}</td>'
        f'<td>{p["exit_reason"].replace("_", " ")}</td>'
        f'<td class="n">{p["entry_credit"]:.2f} → {p["exit_debit"]:.2f}</td>'
        f'<td class="n {theme.dircls(p["realized_pnl"])}">{money(p["realized_pnl"], True)}</td></tr>'
        for p in reversed(closed)) or '<tr><td colspan="5" class="empty">no closed trades yet</td></tr>'

    inc = st.get("incidents", [])
    inc_rows = "".join(f"<li>{i}</li>" for i in inc[-8:]) or "<li>none</li>"

    today = date.today().isoformat()
    started, ends = st["started"], st["ends"]
    days_in = sum(1 for h in st["history"])
    mark_ts = hist[-1][0] if hist else today
    now = f"MARKED {datetime.fromisoformat(mark_ts).strftime('%d %b %Y').upper()} · TICK {days_in}"

    status = ("FLATTENED" if equity < flat_lv else
              "HALTED" if st.get("halted") else
              "ENDED" if today > ends else "RUNNING")

    body = f"""<div class="wrap">
<header>
  <div class="mast">
    <h1 class="name">Quant<em>firm</em></h1>
    <div class="meta"><a href="index.html">main book ↗</a><span>{now}</span></div>
  </div>
  <div class="rule"></div>
  <div class="kicker">Options desk · PAPER SIMULATION — no real orders, no real money</div>
</header>

<section class="hero">
  <div class="kicker">Paper book value</div>
  <span class="fig">{money(equity)}</span>
  <div class="deltas">
    {theme.delta_pill(day_pl, day_pl / day_base if day_base else 0, "today")}
    {theme.delta_pill(total_pl, total_pl / bank, "since start")}
  </div>
  <div class="line">{len(opens)} open · {len(closed)} closed ·
    window <b>{started} → {ends}</b> · status <b>{status}</b> ·
    SPY put credit spreads, $1 wide, ~18Δ, 28–45 DTE</div>
  <div class="meter">
    <div class="track"><div class="fill"
      style="width:{used * 100:.1f}%;background:{meter_col}"></div></div>
    <div class="cap"><span>entries halt below <b>{money(halt_lv)}</b></span>
      <span>flatten below <b>{money(flat_lv)}</b></span></div>
  </div>
</section>

<div class="grid">
  <section class="card full">
    <h2>Paper equity curve <span class="n">marked at each daily tick</span></h2>
    {theme.equity_chart(hist, bank, uid="opt")}
    {theme.equity_table(hist, bank)}
  </section>

  <section class="card">
    <h2>Open positions <span class="n">{len(opens)} of 3 max</span></h2>
    <div class="scroll"><table>
      <tr><th>id</th><th>legs</th><th class="n">dte</th>
        <th class="n">credit</th><th class="n">mark</th><th class="n">unrlzd</th></tr>
      {pos_rows}
    </table></div>
  </section>

  <section class="card">
    <h2>Closed trades <span class="n">{len(closed)}</span></h2>
    <div class="scroll"><table>
      <tr><th>date</th><th>id</th><th>exit</th><th class="n">credit→debit</th>
        <th class="n">P&L</th></tr>
      {closed_rows}
    </table></div>
  </section>

  <section class="card">
    <h2>Cost meter <span class="n">what this window measures</span></h2>
    <div class="scroll"><table>
      <tr><td>modeled slippage</td><td class="n">{money(slip)}</td></tr>
      <tr><td>regulatory fees</td><td class="n">{money(fees)}</td></tr>
      <tr><td><b>total friction</b></td>
        <td class="n"><b>{money(slip + fees)} · {(slip + fees) / bank * 100:.2f}% of bankroll</b></td></tr>
      <tr><td class="empty" colspan="2">fills modeled at 60% of combined
        half-spread each way + $0.04/contract/side</td></tr>
    </table></div>
  </section>

  <section class="card">
    <h2>Incidents <span class="n">{len(inc)} total</span></h2>
    <ul class="inc">{inc_rows}</ul>
  </section>
</div>

<footer>PAPER SIMULATION. Every trading decision is made by deterministic code
(<b>quantfirm/options/paper.py</b>, pre-registered in docs/OPTIONS_PAPER.md);
the agent only fetches quotes and runs the tick. Two weeks measures execution
costs and ops reliability — it cannot validate a strategy, and nothing here is
a promise about real-money results. Generated from committed state; nothing is
hand-entered. Not investment advice.</footer>
</div>"""

    doc = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        '<meta name="color-scheme" content="light dark">\n'
        "<title>quantfirm — options paper desk</title>\n"
        f"<style>{theme.page_css('fonts/')}"
        ".inc{margin:0;padding-left:1.1em;font-size:13px;color:var(--ink-2)}"
        ".inc li{margin-bottom:6px}</style>\n</head>\n<body>\n"
        f"{body}\n</body>\n</html>\n")
    with open(OUT, "w") as f:
        f.write(doc)
    print(OUT)


if __name__ == "__main__":
    main()
