"""CLI for the Kalshi 15M metals desk.

  python -m quantfirm.kalshi.cli backtest  --data DIR [--split test] [--theta X]
  python -m quantfirm.kalshi.cli sweep     --data DIR
  python -m quantfirm.kalshi.cli calibrate --data DIR
  python -m quantfirm.kalshi.cli paper     --minutes 60 [--no-demo] [--metals gold,silver]
  python -m quantfirm.kalshi.cli status    # venue + feed + credential check
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os

from .strategy import Params

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_DIR = os.path.join(REPO, "state")

# Train/test date split (unix ts). Underlying 1m coverage starts 2026-08-13;
# train = first ~17 days, test = the rest. Chosen ONCE, before any sweep.
SPLIT_TS = 1787788800  # 2026-08-27T00:00:00Z


def _params_from_args(a) -> Params:
    kw = {}
    for f in dataclasses.fields(Params):
        v = getattr(a, f.name, None)
        if v is not None:
            kw[f.name] = v
    return Params(**kw)


def _print_metrics(m: dict, verbose: bool = False):
    view = {k: v for k, v in m.items() if k != "trades"}
    print(json.dumps(view, indent=1, default=str))
    if verbose:
        for t in m["trades"][:50]:
            print(t)


def cmd_backtest(a):
    from .backtest import Backtest
    bt = Backtest(a.data, bankroll=a.bankroll)
    p = _params_from_args(a)
    lo, hi = ((None, SPLIT_TS) if a.split == "train"
              else (SPLIT_TS, None) if a.split == "test" else (None, None))
    m = bt.run(p, start_ts=lo, end_ts=hi)
    _print_metrics(m, a.verbose)
    if a.out:
        with open(a.out, "w") as f:
            json.dump({k: v for k, v in m.items() if k != "trades"}, f,
                      indent=1, default=str)


def cmd_sweep(a):
    """Grid on TRAIN split only; prints train table + the chosen point."""
    from .backtest import Backtest
    bt = Backtest(a.data, bankroll=a.bankroll)
    grid_theta = [0.02, 0.03, 0.04, 0.05, 0.07, 0.10]
    grid_hl = [15.0, 30.0, 60.0]
    rows = []
    for th in grid_theta:
        for hl in grid_hl:
            p = Params(theta=th, vol_halflife_min=hl)
            m = bt.run(p, end_ts=SPLIT_TS)
            rows.append({"theta": th, "halflife": hl, "n": m["n_trades"],
                         "pnl": m["net_pnl"], "hit": m["hit_rate"],
                         "sharpe": m["daily_sharpe_ann"],
                         "mdd": m["max_drawdown_pct"]})
            print(rows[-1], flush=True)
    viable = [r for r in rows if r["n"] >= 30]
    best = max(viable, key=lambda r: r["pnl"]) if viable else None
    print("\nCHOSEN (train):", best)
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"grid": rows, "chosen": best}, f, indent=1)


def cmd_calibrate(a):
    from .backtest import Backtest
    from .calibrate import calibration
    bt = Backtest(a.data)
    out = calibration(bt)
    print(json.dumps(out, indent=1))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(out, f, indent=1)


# The pre-registered live taker config (docs/KALSHI.md). Any CLI param
# overrides its field; the effective Params is stamped into the state file
# so every session is auditable against this registration.
REGISTERED = dict(theta=0.07, vol_halflife_min=30.0, tau_min_s=300,
                  tau_max_s=600, price_min=0.35, price_max=0.92)


def cmd_paper(a):
    import dataclasses as _dc
    from .paper import PaperEngine
    kw = dict(REGISTERED)
    for f in dataclasses.fields(Params):
        v = getattr(a, f.name, None)
        if v is not None:
            kw[f.name] = v
    p = Params(**kw)
    os.makedirs(STATE_DIR, exist_ok=True)
    print("effective params:", _dc.asdict(p))
    eng = PaperEngine(
        params=p,
        state_path=os.path.join(STATE_DIR, "kalshi_paper_state.json"),
        log_path=os.path.join(STATE_DIR, "kalshi_paper_trades.csv"),
        decisions_path=(os.path.join(STATE_DIR, "kalshi_paper_decisions.jsonl")
                        if a.log_decisions else None),
        metals=tuple(a.metals.split(",")),
        use_demo=not a.no_demo,
        bankroll0=a.bankroll,
        maker=not a.no_maker)
    eng.run(minutes=a.minutes, poll_s=a.poll)


def cmd_status(a):
    from .client import KalshiClient
    from .feeds import SwissquoteFeed
    for env in ("prod", "demo"):
        c = KalshiClient(env)
        try:
            st = c.exchange_status()
            print(f"{env}: exchange_active={st.get('exchange_active')}"
                  f" trading_active={st.get('trading_active')}"
                  f" creds={'YES' if c.can_trade else 'no'}")
            if c.can_trade:
                print(f"  balance: ${c.balance()}")
        except Exception as e:
            print(f"{env}: ERROR {e}")
    for sym in ("XAU", "XAG"):
        print(f"swissquote {sym}:", SwissquoteFeed(sym).price())
    c = KalshiClient("prod")
    for s in ("KXGOLD15M", "KXSILVER15M", "KXCOPPER15M"):
        m = c.open_market_for_series(s)
        if m:
            q = c.get_quote(m["ticker"])
            print(f"{s}: {m['ticker']} K={m['floor_strike']}"
                  f" book={q.yes_bid}/{q.yes_ask}")
        else:
            print(f"{s}: no open market (weekend/maintenance?)")


def main():
    ap = argparse.ArgumentParser(prog="quantfirm.kalshi")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_params(sp):
        sp.add_argument("--theta", type=float)
        sp.add_argument("--vol-halflife-min", dest="vol_halflife_min", type=float)
        sp.add_argument("--slippage-extra", dest="slippage_extra", type=float)
        sp.add_argument("--tau-min-s", dest="tau_min_s", type=int)
        sp.add_argument("--tau-max-s", dest="tau_max_s", type=int)
        sp.add_argument("--price-min", dest="price_min", type=float)
        sp.add_argument("--price-max", dest="price_max", type=float)
        sp.add_argument("--flow-gate", dest="flow_gate",
                        choices=["off", "flow_only", "stale_only"])
        sp.add_argument("--fill-mode", dest="fill_mode",
                        choices=["touch", "lag"])
        sp.add_argument("--bankroll", type=float, default=500.0)

    sp = sub.add_parser("backtest")
    sp.add_argument("--data", required=True)
    sp.add_argument("--split", choices=["train", "test", "all"], default="all")
    sp.add_argument("--out")
    sp.add_argument("--verbose", action="store_true")
    add_params(sp)
    sp.set_defaults(fn=cmd_backtest)

    sp = sub.add_parser("sweep")
    sp.add_argument("--data", required=True)
    sp.add_argument("--out")
    add_params(sp)
    sp.set_defaults(fn=cmd_sweep)

    sp = sub.add_parser("calibrate")
    sp.add_argument("--data", required=True)
    sp.add_argument("--out")
    add_params(sp)
    sp.set_defaults(fn=cmd_calibrate)

    sp = sub.add_parser("paper")
    sp.add_argument("--minutes", type=float, default=60.0)
    sp.add_argument("--poll", type=float, default=2.0)
    sp.add_argument("--metals", default="gold,silver")
    sp.add_argument("--no-demo", action="store_true")
    sp.add_argument("--no-maker", action="store_true")
    sp.add_argument("--log-decisions", action="store_true")
    add_params(sp)
    sp.set_defaults(fn=cmd_paper)

    sp = sub.add_parser("status")
    sp.set_defaults(fn=cmd_status)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
