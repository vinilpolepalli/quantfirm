"""CLI for the Kalshi 15M metals desk.

  python -m quantfirm.kalshi.cli backtest  --data DIR [--split test] [--theta X]
  python -m quantfirm.kalshi.cli sweep     --data DIR
  python -m quantfirm.kalshi.cli calibrate --data DIR
  python -m quantfirm.kalshi.cli paper     --minutes 60 [--no-demo] [--metals gold,silver]
  python -m quantfirm.kalshi.cli status    # venue + feed + credential check
  python -m quantfirm.kalshi.cli open-count
  python -m quantfirm.kalshi.cli heartbeat
  python -m quantfirm.kalshi.cli poly          # Polymarket 15m vs Kalshi (read-only)
  python -m quantfirm.kalshi.cli poly-compare  # live crypto fills vs poly_book paper
  python -m quantfirm.kalshi.cli cashout-replay  # sell-if-signal-dies vs hold (off live)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from datetime import datetime

from .strategy import Params
from .universe import BANKROLL, PAPER_ASSETS, PAPER_STRATEGY, SPLIT_TS

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_DIR = os.path.join(REPO, "state")


def _engine_paths(a) -> dict:
    prefix = getattr(a, "state_prefix", None) or "kalshi_paper"
    tape = None
    if prefix == "kalshi_paper":
        tape = os.path.join(STATE_DIR, "kalshi_paper_tape.jsonl")
    return {
        "state_path": os.path.join(STATE_DIR, f"{prefix}_state.json"),
        "log_path": os.path.join(STATE_DIR, f"{prefix}_trades.csv"),
        "decisions_path": (os.path.join(STATE_DIR, f"{prefix}_decisions.jsonl")
                           if getattr(a, "log_decisions", False) else None),
        "tape_path": tape,
    }


def _refuse_live_sleeve(a) -> None:
    """Paper sleeves (poly_book, …) must not inherit --live."""
    prefix = getattr(a, "state_prefix", None) or "kalshi_paper"
    if getattr(a, "live", False) and prefix != "kalshi_paper":
        raise SystemExit(
            f"refusing --live with --state-prefix {prefix} "
            "(paper sleeve cannot send Kalshi orders)")



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
    from .strategies import registry
    bt = Backtest(a.data, bankroll=a.bankroll)
    if a.strategy:
        spec = {s.name: s for s in registry()}[a.strategy]
        from dataclasses import replace
        p = spec.params
        if a.fill_mode:
            p = replace(p, fill_mode=a.fill_mode)
        decide_fn = spec.fn
        print(f"strategy={spec.name} fill={p.fill_mode} — {spec.note}", flush=True)
    else:
        p = _params_from_args(a)
        decide_fn = None
    lo, hi = ((None, SPLIT_TS) if a.split == "train"
               else (SPLIT_TS, None) if a.split == "test" else (None, None))
    if getattr(a, "since", None):
        since_ts = int(datetime.fromisoformat(
            a.since.replace("Z", "+00:00")).timestamp())
        lo = since_ts if lo is None else max(lo, since_ts)
    m = bt.run(p, start_ts=lo, end_ts=hi, decide_fn=decide_fn)
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


def cmd_tournament(a):
    from .tournament import render_markdown, run_tournament
    out_json = a.out or os.path.join(REPO, "research", "kalshi", "tournament.json")
    result = run_tournament(a.data, bankroll=a.bankroll, out_json=out_json)
    md = render_markdown(result)
    md_path = a.md or os.path.join(REPO, "research", "kalshi_tournament.md")
    with open(md_path, "w") as f:
        f.write(md)
    print(md)
    print(f"\nwrote {out_json} and {md_path}")


def cmd_diagnostics(a):
    from .backtest import Backtest
    from .diagnostics import run_diagnostics
    bt = Backtest(a.data, bankroll=a.bankroll)
    lo, hi = ((None, SPLIT_TS) if a.split == "train"
              else (SPLIT_TS, None) if a.split == "test" else (None, None))
    print(json.dumps(run_diagnostics(bt, lo, hi), indent=1))


def cmd_paper(a):
    _refuse_live_sleeve(a)
    import dataclasses as _dc
    from .paper import PaperEngine
    from .strategies import registry
    decide_fn = None
    specs = {s.name: s for s in registry()}
    if a.strategy and a.strategy in specs:
        spec = specs[a.strategy]
        from dataclasses import replace
        p = spec.params
        n_assets = len(a.metals.split(","))
        if n_assets > p.max_open:
            p = replace(p, max_open=n_assets)
        decide_fn = spec.fn
        print(f"paper taker strategy: {spec.name} — {spec.note}")
    else:
        kw = dict(REGISTERED)
        for f in dataclasses.fields(Params):
            v = getattr(a, f.name, None)
            if v is not None:
                kw[f.name] = v
        p = Params(**kw)
        if a.strategy and a.strategy != "oracle":
            print(f"unknown --strategy {a.strategy}; falling back to registered oracle")
    os.makedirs(STATE_DIR, exist_ok=True)
    print("effective params:", _dc.asdict(p))
    paths = _engine_paths(a)
    eng = PaperEngine(
        params=p,
        state_path=paths["state_path"],
        log_path=paths["log_path"],
        decisions_path=paths["decisions_path"],
        tape_path=paths["tape_path"],
        metals=tuple(a.metals.split(",")),
        use_demo=not a.no_demo,
        bankroll0=a.bankroll,
        maker=not a.no_maker,
        live=getattr(a, "live", False),
        decide_fn=decide_fn,
        strategy=a.strategy)
    eng.run(minutes=a.minutes, poll_s=a.poll)


def cmd_agent(a):
    """24/7 LangGraph desk. Same engine as paper, graph-orchestrated."""
    _refuse_live_sleeve(a)
    from .agent import run_agent
    import dataclasses as _dc
    from dataclasses import replace
    from .paper import PaperEngine
    from .strategies import registry
    specs = {s.name: s for s in registry()}
    spec = specs.get(a.strategy) or specs[PAPER_STRATEGY]
    p = spec.params
    n_assets = len(a.metals.split(","))
    if n_assets > p.max_open:
        p = replace(p, max_open=n_assets)
    os.makedirs(STATE_DIR, exist_ok=True)
    print("effective params:", _dc.asdict(p))
    paths = _engine_paths(a)
    eng = PaperEngine(
        params=p,
        state_path=paths["state_path"],
        log_path=paths["log_path"],
        decisions_path=paths["decisions_path"],
        tape_path=paths["tape_path"],
        metals=tuple(a.metals.split(",")),
        use_demo=not a.no_demo,
        bankroll0=a.bankroll,
        maker=not a.no_maker,
        live=a.live,
        decide_fn=spec.fn,
        strategy=spec.name)
    from .universe import YF_SYMBOLS
    for metal in eng.metals:
        if metal in eng.feeds and metal in YF_SYMBOLS:
            eng.warm_vol_from_bars(metal, YF_SYMBOLS[metal])
    run_agent(eng, minutes=a.minutes, poll_s=a.poll, live=a.live,
              strategy=spec.name)


def cmd_open_count(_a):
    """Print how many of the live 15m series have an open window.

    Supervisor uses this instead of grepping `status` (a flake there used
    to sleep 10 minutes and miss the next window).
    """
    from .runtime import count_open_markets
    print(count_open_markets())


def cmd_heartbeat(_a):
    from .runtime import write_desk_status
    print(json.dumps(write_desk_status(), indent=1))


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
    from .universe import LIVE_SERIES
    from .feeds import KalshiLiveFeed
    for s in LIVE_SERIES:
        m = c.open_market_for_series(s)
        if m:
            q = c.get_quote(m["ticker"])
            live = KalshiLiveFeed(c, s).price()
            print(f"{s}: {m['ticker']} K={m['floor_strike']}"
                  f" book={q.yes_bid}/{q.yes_ask} live={live}")
        else:
            print(f"{s}: no open market (weekend/maintenance?)")


def cmd_poly(_a):
    """Print Polymarket 15m Up/Down BBO next to Kalshi YES/NO. Read-only."""
    from .client import KalshiClient
    from .poly import POLY_ASSETS, PolymarketFeed, poly_favorite
    from .universe import LIVE_SERIES

    feed = PolymarketFeed()
    c = KalshiClient("prod")
    inv = {asset: ticker for ticker, asset in LIVE_SERIES.items()}
    rows = []
    for asset in POLY_ASSETS:
        rec = {"asset": asset}
        q = feed.quote(asset)
        if q:
            rec["poly"] = {
                "slug": q.slug,
                "up": [q.up_bid, q.up_ask],
                "down": [q.down_bid, q.down_ask],
                "favorite": poly_favorite(q),
            }
        series = inv.get(asset)
        m = c.open_market_for_series(series) if series else None
        if m:
            kq = c.get_quote(m["ticker"])
            yes_bid = float(kq.yes_bid) if kq.yes_bid is not None else None
            yes_ask = float(kq.yes_ask) if kq.yes_ask is not None else None
            k_fav = None
            if yes_ask is not None and yes_ask >= 0.55:
                k_fav = "yes"
            no_px = (1.0 - yes_bid) if yes_bid is not None else None
            if no_px is not None and no_px >= 0.55:
                if k_fav is None or no_px > (yes_ask or 0):
                    k_fav = "no"
            rec["kalshi"] = {
                "ticker": m["ticker"],
                "K": m.get("floor_strike"),
                "yes": [yes_bid, yes_ask],
                "favorite": k_fav,
            }
            rec["agree"] = (
                rec.get("poly", {}).get("favorite") == rec["kalshi"]["favorite"]
                if rec.get("poly") and rec["kalshi"]["favorite"] else None)
        rows.append(rec)
    print(json.dumps(rows, indent=1))


def cmd_poly_compare(_a):
    from .poly import compare_snapshot
    print(json.dumps(compare_snapshot(), indent=1))


def cmd_cashout_replay(a):
    """Replay sell-if-signal-dies vs hold-to-settle. Does not touch live."""
    from .cashout import replay_snapshot

    snap = replay_snapshot(
        a.log, a.decisions, a.trades, use_poly=not a.no_poly,
        price_min=a.price_min, min_hold_s=a.min_hold_s)
    print(json.dumps(snap, indent=1))


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
        sp.add_argument("--bankroll", type=float, default=BANKROLL)

    sp = sub.add_parser("backtest")
    sp.add_argument("--data", required=True)
    sp.add_argument("--split", choices=["train", "test", "all"], default="all")
    sp.add_argument(
        "--strategy",
        default=None,
        help="registered name from strategies.registry() "
             "(one_pct, favorite_div, …). Default: oracle params from flags",
    )
    sp.add_argument(
        "--since",
        default=None,
        help="ISO timestamp (e.g. 2026-09-05T00:00:00Z); "
             "skip windows that close before this",
    )
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
    sp.add_argument("--bankroll", type=float, default=BANKROLL)
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_maker)

    sp = sub.add_parser("maker-control")
    sp.add_argument("--data", required=True)
    sp.add_argument("--bankroll", type=float, default=BANKROLL)
    sp.set_defaults(fn=cmd_maker_control)

    sp = sub.add_parser("calibrate")
    sp.add_argument("--data", required=True)
    sp.add_argument("--out")
    add_params(sp)
    sp.set_defaults(fn=cmd_calibrate)

    sp = sub.add_parser("paper")
    sp.add_argument("--minutes", type=float, default=60.0)
    sp.add_argument("--poll", type=float, default=2.0)
    sp.add_argument("--metals", default=",".join(PAPER_ASSETS))
    sp.add_argument("--strategy", default=PAPER_STRATEGY,
                    help="taker strategy name from strategies.registry()")
    sp.add_argument("--no-demo", action="store_true")
    sp.add_argument("--no-maker", action="store_true")
    sp.add_argument("--live", action="store_true",
                    help="send real prod orders (also requires KALSHI_LIVE=1 + prod key)")
    sp.add_argument("--log-decisions", action="store_true")
    sp.add_argument("--state-prefix", default="kalshi_paper",
                    help="state/ log file prefix. poly paper uses kalshi_poly_paper")
    add_params(sp)
    sp.set_defaults(fn=cmd_paper)

    sp = sub.add_parser("agent")
    sp.add_argument("--minutes", type=float, default=60.0)
    sp.add_argument("--poll", type=float, default=2.0)
    sp.add_argument("--metals", default=",".join(PAPER_ASSETS))
    sp.add_argument("--strategy", default=PAPER_STRATEGY)
    sp.add_argument("--no-demo", action="store_true")
    sp.add_argument("--no-maker", action="store_true")
    sp.add_argument("--live", action="store_true")
    sp.add_argument("--log-decisions", action="store_true")
    sp.add_argument("--state-prefix", default="kalshi_paper")
    add_params(sp)
    sp.set_defaults(fn=cmd_agent)

    sp = sub.add_parser("tournament")
    sp.add_argument("--data", required=True)
    sp.add_argument("--out")
    sp.add_argument("--md")
    add_params(sp)
    sp.set_defaults(fn=cmd_tournament)

    sp = sub.add_parser("diagnostics")
    sp.add_argument("--data", required=True)
    sp.add_argument("--split", choices=["train", "test", "all"], default="train")
    add_params(sp)
    sp.set_defaults(fn=cmd_diagnostics)

    sp = sub.add_parser("status")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("open-count")
    sp.set_defaults(fn=cmd_open_count)

    sp = sub.add_parser("heartbeat")
    sp.set_defaults(fn=cmd_heartbeat)

    sp = sub.add_parser("poly")
    sp.set_defaults(fn=cmd_poly)

    sp = sub.add_parser("poly-compare")
    sp.set_defaults(fn=cmd_poly_compare)

    sp = sub.add_parser(
        "cashout-replay",
        help="replay cash-out vs hold-to-settle (off the live loop)",
    )
    sp.add_argument("--log", default="state/kalshi_paper_loop.log")
    sp.add_argument("--decisions", default="state/kalshi_paper_decisions.jsonl")
    sp.add_argument("--trades", default="state/kalshi_paper_trades.csv")
    sp.add_argument("--no-poly", action="store_true",
                    help="Kalshi ≥60¢ favorite only; ignore Polymarket")
    sp.add_argument("--price-min", type=float, default=0.60)
    sp.add_argument("--min-hold-s", type=float, default=15)
    sp.set_defaults(fn=cmd_cashout_replay)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
