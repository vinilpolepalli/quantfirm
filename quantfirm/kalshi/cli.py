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


def cmd_maker(a):
    """Backtest the MAKER leg over full history, across fill models."""
    import dataclasses as _dc
    from .maker import MakerBacktest, MakerParams
    mb = MakerBacktest(a.data, bankroll=a.bankroll)
    lo, hi = ((None, SPLIT_TS) if a.split == "train"
              else (SPLIT_TS, None) if a.split == "test" else (None, None))
    kw = {}
    for f in _dc.fields(MakerParams):
        v = getattr(a, f.name, None)
        if v is not None:
            kw[f.name] = v
    modes = [a.fill_model] if a.fill_model else ["through", "queue", "adverse"]
    out = {}
    for mode in modes:
        m = mb.run(MakerParams(**{**kw, "fill_mode": mode}), start_ts=lo, end_ts=hi)
        out[mode] = {k: v for k, v in m.items() if k != "fills"}
        if m["n_fills"] == 0:
            print(f"{mode:>8}: no fills ({m.get('skipped')})")
            continue
        print(f"{mode:>8}: n={m['n_fills']:>5} pnl=${m['net_pnl']:>9.2f} "
              f"({m['return_pct']:>7.1f}%) hit={m['hit_rate']:.3f} "
              f"be={m['breakeven_hit']:.3f} cushion={m['cushion_pp']:+.2f}pp "
              f"t={m['t_stat']:>6.2f} mdd={m['max_drawdown_pct']:.1f}%")
    if a.out:
        with open(a.out, "w") as f:
            json.dump(out, f, indent=1, default=str)


def cmd_maker_control(a):
    """Null-model control. If this earns like the real strategy, the maker
    backtest is measuring fill mechanics, not edge — and is invalid."""
    from .maker import MakerBacktest, MakerParams, MarketMidControl
    real = MakerBacktest(a.data, bankroll=a.bankroll)
    ctrl = MarketMidControl(a.data, bankroll=a.bankroll)
    print(f"{'mode':>8} {'variant':>12} {'n':>6} {'pnl':>11} {'hit':>7} {'t':>7}")
    verdict_ok = True
    for mode in ("through", "queue"):
        rows = []
        for name, eng in (("model", real), ("market-mid", ctrl)):
            m = eng.run(MakerParams(fill_mode=mode))
            rows.append((name, m))
            print(f"{mode:>8} {name:>12} {m['n_fills']:>6} ${m['net_pnl']:>10.2f} "
                  f"{m['hit_rate']:>7.3f} {m['t_stat']:>7.2f}")
        model_t = rows[0][1]["t_stat"]
        ctrl_t = rows[1][1]["t_stat"]
        if ctrl_t >= model_t * 0.5:
            verdict_ok = False
    print()
    if verdict_ok:
        print("VERDICT: control is far weaker than the model — fill model may be sound.")
    else:
        print("VERDICT: *** INVALID *** the null model earns comparably or better.")
        print("The backtest P&L is a fill-mechanics artifact, not edge. Do not")
        print("use it as evidence. See the module docstring in maker.py.")


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
        tape_path=(None if a.no_tape else
                   os.path.join(STATE_DIR, "kalshi_tape")),   # + _YYYY-MM-DD.jsonl
        tape_poll_s=a.tape_poll,
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

    sp = sub.add_parser("maker")
    sp.add_argument("--data", required=True)
    sp.add_argument("--split", choices=["train", "test", "all"], default="all")
    sp.add_argument("--fill-model", dest="fill_model",
                    choices=["through", "queue", "adverse"])
    sp.add_argument("--margin", type=float)
    sp.add_argument("--fade", type=float)
    sp.add_argument("--min-price", dest="min_price", type=float)
    sp.add_argument("--max-price", dest="max_price", type=float)
    sp.add_argument("--queue-ahead-mult", dest="queue_ahead_mult", type=float)
    sp.add_argument("--favorite-hi", dest="favorite_hi", type=float)
    sp.add_argument("--favorite-lo", dest="favorite_lo", type=float)
    sp.add_argument("--bankroll", type=float, default=500.0)
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_maker)

    sp = sub.add_parser("maker-control")
    sp.add_argument("--data", required=True)
    sp.add_argument("--bankroll", type=float, default=500.0)
    sp.set_defaults(fn=cmd_maker_control)

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
    sp.add_argument("--no-tape", action="store_true",
                    help="do not record the public trade tape")
    sp.add_argument("--tape-poll", dest="tape_poll", type=int, default=15,
                    help="seconds between tape polls per market (default 15)")
    add_params(sp)
    sp.set_defaults(fn=cmd_paper)

    sp = sub.add_parser("status")
    sp.set_defaults(fn=cmd_status)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
