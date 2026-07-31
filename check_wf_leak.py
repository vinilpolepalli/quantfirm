"""Check A: does walk_forward leak for strategies with internal (full-window)
normalization or internal optimization?

Both strategies below have ZERO true predictive power on a pure random walk.
A correct out-of-sample harness must score them ~0. walk_forward hands the
strategy df.iloc[:hi] — history through the END of the fold being scored — so
any full-window statistic or internal fit sees the fold's own "test" bars.
"""
import numpy as np
import pandas as pd
from quantfirm.backtest import walk_forward
from quantfirm.costs import CostModel

ZERO = CostModel("zero", 0.0)


def leaky_norm(df):
    """Mean-reversion to the mean of the WHOLE window it was handed.

    Uses window.mean() — a full-sample statistic (internal normalization).
    On a random walk this has no causal edge; any positive score is leakage.
    """
    m = df["close"].mean()
    return (df["close"] < m).astype(float)


def internal_optimizer(df):
    """Simulates a strategy that 'optimises internally': tries 40 random
    signals and keeps whichever had the best PnL on the window it was given.
    walk_forward's docstring claims the split still kills such wins."""
    rng = np.random.default_rng(hash(len(df)) % (2**32))
    ret = df["close"].pct_change().fillna(0.0).to_numpy()
    best, best_pnl = None, -np.inf
    for _ in range(40):
        sig = (rng.standard_normal(len(df)) > 0).astype(float)
        pnl = float((np.roll(sig, 1)[1:] * ret[1:]).sum())
        if pnl > best_pnl:
            best_pnl, best = pnl, sig
    return pd.Series(best, index=df.index)


results_norm, results_opt = [], []
for seed in range(10):
    rng = np.random.default_rng(seed)
    n = 20000
    idx = pd.date_range("2019-01-01", periods=n, freq="h", tz="UTC")
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))   # pure random walk
    df = pd.DataFrame({"close": px, "open": px, "high": px, "low": px,
                       "volume": 1.0}, index=idx)
    out_n = walk_forward(df, leaky_norm, {}, cost=ZERO, warmup_bars=2000)
    out_o = walk_forward(df, internal_optimizer, {}, cost=ZERO, warmup_bars=2000)
    results_norm.append(out_n["oos_sharpe"])
    results_opt.append(out_o["oos_sharpe"])

print("random-walk data, zero true edge, zero costs:")
print("leaky_norm       'oos_sharpe' per seed:", results_norm)
print("  mean:", round(float(np.mean(results_norm)), 3))
print("internal_optimizer 'oos_sharpe' per seed:", results_opt)
print("  mean:", round(float(np.mean(results_opt)), 3))
print()
print("A correct OOS harness would score ~0 (|sharpe| < ~0.5) on noise.")
