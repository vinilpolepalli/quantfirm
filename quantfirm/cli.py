"""CLI used by humans, CI, and tournament agents.

    python -m quantfirm.cli list
    python -m quantfirm.cli backtest --strategy donchian --symbol BTCUSDT --split dev
    python -m quantfirm.cli walkforward --strategy donchian --symbol BTCUSDT
    python -m quantfirm.cli sweep --strategy tsmom --symbol BTCUSDT \
        --grid '{"lookback": [240, 720, 1440], "band": [0.0, 0.02]}'

All output is JSON on stdout so agents can parse it. Tournament agents must
use --split dev (the default); --split holdout is reserved for the judge.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys

from . import backtest as bt
from .costs import SCENARIOS, RH_MARKET
from .data import load_history
from .strategies import load_all


def _cost(name: str):
    for c in SCENARIOS:
        if c.name == name:
            return c
    return RH_MARKET


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["list", "backtest", "walkforward", "sweep"])
    p.add_argument("--strategy")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--interval", default="1h")
    p.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    p.add_argument("--cost", default="rh_market")
    p.add_argument("--params", default="{}")
    p.add_argument("--grid", default="{}")
    p.add_argument("--folds", type=int, default=5)
    args = p.parse_args()

    registry = load_all()

    if args.cmd == "list":
        print(json.dumps(sorted(registry)))
        return

    if args.strategy not in registry:
        print(json.dumps({"error": f"unknown strategy {args.strategy}", "known": sorted(registry)}))
        sys.exit(1)

    df = bt.split(load_history(args.symbol, args.interval), args.split)
    strat = registry[args.strategy]
    cost = _cost(args.cost)
    params = json.loads(args.params)

    if args.cmd == "backtest":
        out = bt.run_strategy(df, strat, params, cost)
    elif args.cmd == "walkforward":
        out = bt.walk_forward(df, strat, params, cost, n_folds=args.folds)
    else:  # sweep
        grid = json.loads(args.grid)
        keys = sorted(grid)
        combos = list(itertools.product(*(grid[k] for k in keys))) or [()]
        rows = []
        for combo in combos:
            ps = dict(params)
            ps.update(dict(zip(keys, combo)))
            res = bt.walk_forward(df, strat, ps, cost, n_folds=args.folds)
            rows.append({"params": ps, **res})
        rows.sort(key=lambda r: r.get("oos_sharpe", 0), reverse=True)
        out = {"n_trials": len(rows), "results": rows}

    out["strategy"] = args.strategy
    out["symbol"] = args.symbol
    out["split"] = args.split
    print(json.dumps(out))


if __name__ == "__main__":
    main()
