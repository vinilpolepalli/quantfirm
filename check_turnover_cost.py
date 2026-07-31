"""Check B/C: walk_forward summary index mismatch + fold-entry cost.

C: summary(all_oos, pos_full, ...) — returns are OOS-only (bars >= warmup)
   but annual_turnover/avg_exposure use the FULL-sample position (warmup
   included). Strategy that churns only during warmup shows huge reported
   turnover despite zero trading in scored bars.

B: cost of the position standing at fold start. run() charges entry at bar 0
   (pos.diff().fillna(pos.iloc[0])); walk_forward fills the first diff with
   0 and slices [lo:hi), so a position built during warmup is never charged.
   buy_and_hold makes this exact: run() charges one per_side, walk_forward
   charges nothing.
"""
import numpy as np
import pandas as pd
from quantfirm.backtest import run, walk_forward
from quantfirm.costs import RH_MARKET
from quantfirm.metrics import annual_turnover

n = 20000
warm = 10000
idx = pd.date_range("2019-01-01", periods=n, freq="h", tz="UTC")
rng = np.random.default_rng(0)
px = 100 * np.exp(np.cumsum(rng.normal(0.0001, 0.01, n)))
df = pd.DataFrame({"close": px, "open": px, "high": px, "low": px,
                   "volume": 1.0}, index=idx)


def churn_then_hold(df):
    """Alternates 0/1 every bar for the first `warm` bars, then holds 1."""
    v = np.ones(len(df))
    k = min(warm, len(df))
    v[:k] = np.arange(k) % 2
    return pd.Series(v, index=df.index)


out = walk_forward(df, churn_then_hold, {}, cost=RH_MARKET, warmup_bars=warm,
                   n_folds=5)
pos_oos = churn_then_hold(df).iloc[warm:]
true_oos_turnover = annual_turnover(pos_oos)
print("C. reported annual_turnover in walk_forward output:", out["annual_turnover"])
print("   actual turnover over the scored (OOS) bars:     ", round(true_oos_turnover, 2))
print("   avg_exposure reported:", out["avg_exposure"],
      " | actual OOS avg exposure:", round(float(pos_oos.mean()), 3))
print()

# B: buy-and-hold entry cost
bh = lambda df: pd.Series(1.0, index=df.index)
r_run = run(df, bh(df), cost=RH_MARKET)
r_wf = walk_forward(df, bh, {}, cost=RH_MARKET, warmup_bars=warm, n_folds=5)

# total return of the underlying over each scored span
underlying_full = px[-1] / px[0] - 1
underlying_oos = px[-1] / px[warm] - 1
print("B. run(): buy_and_hold total_return", r_run["total_return"],
      " vs underlying", round(underlying_full, 4),
      " -> entry cost charged:", round(underlying_full - r_run["total_return"], 4))
print("   walk_forward: buy_and_hold total_return", r_wf["total_return"],
      " vs underlying over OOS span", round(underlying_oos, 4),
      " -> entry cost charged:", round(underlying_oos - r_wf["total_return"], 4))
