"""Equity-desk CLI — JSON on stdout, used by CI and tournament agents.

    python -m quantfirm.equities.cli list
    python -m quantfirm.equities.cli backtest --strategy dual_momentum --split dev
    python -m quantfirm.equities.cli walkforward --strategy xsec_momentum \
        --params '{"top_n": 10}' --split dev
    python -m quantfirm.equities.cli sweep --strategy sector_rotation \
        --grid '{"lookback": [63, 126, 252], "top_n": [2, 3, 4]}'

Tournament agents: --split dev ONLY; holdout belongs to the judge.
--cost-bps defaults to 5 (per side); the judge also stresses 10.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys

from . import backtest as bt
from .data import load_panel
from .strategies import load_all


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["list", "backtest", "walkforward", "sweep"])
    p.add_argument("--strategy")
    p.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--params", default="{}")
    p.add_argument("--grid", default="{}")
    p.add_argument("--folds", type=int, default=4)
    args = p.parse_args()

    registry = load_all()
    if args.cmd == "list":
        print(json.dumps(sorted(registry)))
        return
    if args.strategy not in registry:
        print(json.dumps({"error": f"unknown strategy {args.strategy}",
                          "known": sorted(registry)}))
        sys.exit(1)

    closes = bt.split(load_panel(), args.split)
    strat = registry[args.strategy]
    params = json.loads(args.params)

    if args.cmd == "backtest":
        out = bt.run_strategy(closes, strat, params, args.cost_bps)
    elif args.cmd == "walkforward":
        out = bt.walk_forward(closes, strat, params, args.cost_bps, n_folds=args.folds)
    else:
        grid = json.loads(args.grid)
        keys = sorted(grid)
        rows = []
        for combo in itertools.product(*(grid[k] for k in keys)):
            ps = dict(params); ps.update(dict(zip(keys, combo)))
            res = bt.walk_forward(closes, strat, ps, args.cost_bps, n_folds=args.folds)
            rows.append({"params": ps, **res})
        rows.sort(key=lambda r: r.get("oos_sharpe", 0), reverse=True)
        out = {"n_trials": len(rows), "results": rows}

    out.update({"strategy": args.strategy, "split": args.split})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
