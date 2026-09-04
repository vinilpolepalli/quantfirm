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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from quantfirm.options import paper  # noqa: E402

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

    # drawdown ladder (v2 HIGH-RISK): entries halt at 40%, flatten at 20%
    halt_lv, flat_lv = 0.40 * bank, 0.20 * bank
    risk_open = sum(float(p.get("max_loss", 0)) for p in opens)
    used = min(1.0, max(0.0, (bank - equity) / (bank - flat_lv))) if equity < bank else 0.0
    meter_col = ("var(--loss)" if equity < halt_lv else
                 "var(--warn)" if used > 0.3 else "var(--accent)")

    # cost meter — the number this desk exists to measure
    slip = sum(abs(float(p.get("entry_slippage", 0))) * 100 * p["qty"]
               for p in st["positions"])
    slip = abs(slip)
    slip += sum(abs(float(p["exit_mid"]) - float(p["exit_price"])) * 100 * p["qty"]
                for p in closed if p.get("exit_mid") is not None)
    fees = sum(float(p.get("fees_open", 0)) + float(p.get("fees_close", 0))
               for p in st["positions"])

    def legdesc(p):
        legs = sorted(p["legs"], key=lambda l: float(l["strike"]))
        body = "/".join(("+" if l["side"] == "long" else "\u2212")
                        + f'{paper._strike(l["strike"])}{l["type"][0].upper()}' for l in legs)
        return f'{p["underlying"]} {body} {min(l["expiry"] for l in p["legs"])[5:]}'

    def pos_row(p):
        mark = p.get("mark")
        entry = float(p["paid_open"])
        mark_txt = "stale" if mark is None else f"{mark:+.2f}"
        unrl = ((mark if mark is not None else entry) - entry) * 100 * p["qty"] \
            - p["fees_open"]
        return (
            f'<tr><td class="sym">{p["id"]}</td>'
            f'<td>{p.get("sleeve", "—")}</td>'
            f'<td>{legdesc(p)}</td>'
            f'<td class="n">{p["dte"]}</td>'
            f'<td class="n">{entry:+.2f}</td>'
            f'<td class="n">{mark_txt}</td>'
            f'<td class="n">{money(float(p.get("max_loss", 0)))}</td>'
            f'<td class="n {theme.dircls(unrl)}">{money(unrl, True)}</td></tr>')

    pos_rows = "".join(pos_row(p) for p in opens) \
        or '<tr><td colspan="8" class="empty">no open positions</td></tr>'

    closed_rows = "".join(
        f'<tr><td>{p["closed"][5:]}</td><td class="sym">{p["id"]}</td><td>{p.get("sleeve","—")}</td>'
        f'<td>{p["exit_reason"].replace("_", " ")}</td>'
        f'<td class="n">{float(p["paid_open"]):+.2f} → {float(p.get("exit_price", 0)):+.2f}</td>'
        f'<td class="n {theme.dircls(p["realized_pnl"])}">{money(p["realized_pnl"], True)}</td></tr>'
        for p in reversed(closed)) or '<tr><td colspan="6" class="empty">no closed trades yet</td></tr>'

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
  <div class="kicker">Options desk · PAPER SIMULATION · <b>HIGH-RISK MANDATE</b>
    — no real orders, no real money</div>
</header>

<section class="hero">
  <div class="kicker">Paper book value</div>
  <span class="fig">{money(equity)}</span>
  <div class="deltas">
    {theme.delta_pill(day_pl, day_pl / day_base if day_base else 0, "today")}
    {theme.delta_pill(total_pl, total_pl / bank, "since start")}
  </div>
  <div class="line">{len(opens)} open · {len(closed)} closed ·
    capital at risk <b>{money(risk_open)}</b> of {money(bank)} ·
    window <b>{started} → {ends}</b> · status <b>{status}</b></div>
  <div class="meter">
    <div class="track"><div class="fill"
      style="width:{used * 100:.1f}%;background:{meter_col}"></div></div>
    <div class="cap"><span>entries halt below <b>{money(halt_lv)}</b> (40%)</span>
      <span>flatten below <b>{money(flat_lv)}</b> (20%)</span></div>
  </div>
</section>

<div class="grid">
  <section class="card full">
    <h2>Paper equity curve <span class="n">marked at each daily tick</span></h2>
    {theme.equity_chart(hist, bank, uid="opt")}
    {theme.equity_table(hist, bank)}
  </section>

  <section class="card">
    <h2>Open positions <span class="n">{len(opens)} of {paper.MAX_OPEN_TOTAL} max</span></h2>
    <div class="scroll"><table>
      <tr><th>id</th><th>sleeve</th><th>legs</th><th class="n">dte</th>
        <th class="n">entry</th><th class="n">mark</th><th class="n">risk</th>
        <th class="n">unrlzd</th></tr>
      {pos_rows}
    </table></div>
  </section>

  <section class="card">
    <h2>Closed trades <span class="n">{len(closed)}</span></h2>
    <div class="scroll"><table>
      <tr><th>date</th><th>id</th><th>sleeve</th><th>exit</th>
        <th class="n">entry→exit</th><th class="n">P&L</th></tr>
      {closed_rows}
    </table></div>
  </section>

  <section class="card">
    <h2>Cost meter <span class="n">friction paid to date</span></h2>
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

<footer>PAPER SIMULATION under an explicit <b>maximum-risk mandate</b> from the
owner. Every trading decision is made by deterministic code
(<b>quantfirm/options/paper.py</b>, pre-registered in docs/OPTIONS_PAPER_V2.md);
the agent only fetches quotes and runs the tick. The published evidence says
these aggressive structures carry <b>negative expected value</b> — short-dated
premium selling, long lottery options and event bets all lose on average, and
this book is expected to swing hard and may well end at zero. Losses are bounded
(no naked shorts) but the whole simulated $500 is genuinely at stake. Generated
from committed state; nothing is hand-entered. Not investment advice.</footer>
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
