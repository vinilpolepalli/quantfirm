"""xsec_momentum — cross-sectional momentum across the six long-history perps.

REGISTERED BEFORE THE FIRST RUN (campaign protocol, research/kalshi_perps/CAMPAIGN.md).

Hypothesis
----------
Among the six Kalshi perps with multi-year proxy histories (btc, eth, gold,
silver, sol from 2021-06, xrp from 2019-02 with a 2021-01 → 2023-07 hole),
the names with the strongest trailing 3–12-month return keep outperforming
the others over the next month, so a monthly-rebalanced book that is long the
top two (and, in the documented variant, short the bottom two) earns more per
unit of risk than holding all six. On this mixed universe the sort mostly
rotates between crypto and metals, and within crypto between majors and alts.

Mechanism: relative momentum — under-reaction and slow diffusion of news plus
flows chasing recent winners (Jegadeesh & Titman 1993, J. Finance; Asness,
Moskowitz & Pedersen 2013 "Value and Momentum Everywhere", J. Finance). The
12-1 variant skips the most recent month to avoid short-term reversal.

External evidence (mixed — the prior is weak, which is why this is a family
and not the incumbent):
  * Borri, Liu, Tsyvinski & Wu (2025) find a two-week cross-sectional crypto
    momentum premium GROSS of costs; Liu, Tsyvinski & Wu (2022, J. Finance)
    document 1–4 week momentum in coin returns.
  * Han, Kang & Ryu (SSRN 4675565) find time-series momentum robust but
    cross-sectional crypto momentum weak once costs and intra-period moves are
    counted — "many momentum portfolios are liquidated".
  * Asness–Moskowitz–Pedersen 2013: cross-sectional momentum exists in every
    asset class incl. commodities, but on a 6-name universe the "cross-section"
    is thin, so the expected Sharpe is a fraction of the 40-asset versions.
  Costs: a top-2 rotation costs a tier-0 round trip (≈29 bps per leg turned
  over) so the cadence is monthly, not weekly (see "cadence" below).

Construction (all causal: rolling windows and shifts only, no aux series)
-----------------------------------------------------------------------
  spec = (mode, lookback, skip):
    mom_t  = close[t-skip] / close[t-skip-lookback] − 1        (per asset)
    fresh  = the asset printed a native bar within the last STALE_DAYS days
    valid  = every day of the return window was fresh (no forward-filled hole
             is ever ranked — xrp's 905-day Coinbase gap and its +170% relisting
             jump are excluded, metals holidays ≤ 4 days are not)
    rank   = rank of mom among the valid names, 1 = strongest
    "top"  : signal 1 on rank ≤ top_k, 0 elsewhere (long-only)        [primary]
    "ls"   : +1 on the top_k, −1 on the bottom_k, else 0 (risk-balanced legs:
             vol_target sizes each leg by 1/σ, so the book is equal-risk long
             vs short, not equal-dollar — the sensible form on a universe that
             mixes 60%-vol coins with 15%-vol gold)
    "rank" : signal = (n_valid + 1 − rank) / n_valid (best 1.0 … worst 1/n),
             long-only, all valid names held
  Sizing: vol_target(signal, panel, target_vol × conc). vol_target scales a
  FULLY-LONG n-asset reference book to target_vol, so a k-of-n book would
  otherwise carry ~k/n of the benchmark's risk. conc is a constant of the
  design (n/top_k for "top", n/(2·top_k) for "ls", 2n/(n+1) for "rank"),
  never a function of the data, so the "weak signal → smaller book" property
  of the shared machinery still holds (fewer valid names → smaller book).
  The venue caps (0.75 per asset, 1.5 gross, 35% liquidation distance)
  apply after. Expected realised vol runs a little above the benchmark's
  because a 2-name book is less diversified than a 6-name one.

Cadence: every CLI run of this family uses --every 30 (monthly check of the
3% band). The hypothesis IS about cadence: a cross-sectional sort is a
monthly portfolio by construction and the fee arithmetic forbids weekly
churn of a top-2 book. Nothing else in BacktestConfig is changed.

Registered grid (≤ 6 configurations, frozen)
--------------------------------------------
  fixed: target_vol = 0.12, top_k = 2
  1. spec = ("top",  63,  0)   long top-2 by 3-month return, flat the rest
  2. spec = ("top", 252, 21)   long top-2 by 12-1-month return
  3. spec = ("ls",   63,  0)   long top-2 / short bottom-2, 3-month
  4. spec = ("ls",  252, 21)   long top-2 / short bottom-2, 12-1-month
  5. spec = ("rank", 126, 0)   rank-weighted long-only, 6-month return
  6. configuration 1 on the 4-asset universe (btc, eth, gold, silver) over the
     standard window (dev_start 2016-06-01, 6 folds, 550 warm-up) as a fixed-
     parameter fold report, for comparison with the tournament table. Same
     registry key as 1.
Walk-forward: --universe btc,eth,gold,silver,sol,xrp --start 2021-07-01
--folds 4 --warmup 200 --every 30 (sol only starts 2021-06; the sample is
4 years, the first fold's in-sample selection window is ~6 months — short).
Selection rule (pre-registered): the config the walk-forward picks in the
most folds; tie → the last fold's pick. That config gets the fixed dev run
(--yearly --stress) and the robust run. Any change after seeing results is a
new trial and will be added to TRIALS and named in the report.

Reproduction (repo root):
  python -m quantfirm.perps.cli walkforward --strategy xsec_momentum \
      --universe btc,eth,gold,silver,sol,xrp --start 2021-07-01 --folds 4 --warmup 200 --every 30 \
      --params '{"target_vol": 0.12, "top_k": 2}' \
      --grid '{"spec": [["top",63,0],["top",252,21],["ls",63,0],["ls",252,21],["rank",126,0]]}' \
      --note "family=xsec_momentum v1"
  python -m quantfirm.perps.cli walkforward --strategy xsec_momentum --every 30 \
      --params '{"target_vol": 0.12, "top_k": 2, "spec": ["top",63,0]}' --note "family=xsec_momentum v1 4-asset"
  python -m quantfirm.perps.cli backtest --strategy xsec_momentum --split dev --start 2021-07-01 --yearly --stress \
      --universe btc,eth,gold,silver,sol,xrp --every 30 --params '<selected>' --note "family=xsec_momentum v1"
  python -m quantfirm.perps.cli robust --strategy xsec_momentum --universe btc,eth,gold,silver,sol,xrp \
      --start 2021-07-01 --every 30 --params '<selected>' --n-boot 500 --n-null 60
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align
from ..strategies import register, vol_target

# A print older than this many calendar days is stale. Metals holidays leave
# gaps of at most 4 calendar days on the union calendar; xrp's 2021–23 hole
# is 905 days.
STALE_DAYS = 5
MODES = ("top", "ls", "rank")


def _fresh(panel: dict[str, pd.DataFrame], idx: pd.DatetimeIndex) -> pd.DataFrame:
    """1.0 on day t if the asset printed a native bar within the last
    STALE_DAYS days (t included), else 0.0. Causal: looks back only."""
    out = {}
    for a, d in panel.items():
        has = pd.Series(1.0, index=d.index).reindex(idx)
        out[a] = has.ffill(limit=STALE_DAYS - 1).notna().astype(float)
    return pd.DataFrame(out, index=idx)


def _signal(panel: dict[str, pd.DataFrame], mode: str, lookback: int, skip: int,
            top_k: int) -> tuple[pd.DataFrame, float]:
    """Cross-sectional signal in [-1, 1] and the design concentration factor."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    closes = align(panel)
    idx = closes.index
    n = len(closes.columns)
    lookback = max(int(lookback), 1)
    skip = max(int(skip), 0)          # a negative skip would be look-ahead; clamp
    top_k = max(int(top_k), 1)
    win = lookback + skip
    # trailing return over [t − skip − lookback, t − skip]; NaN before an asset has history
    mom = closes.shift(skip) / closes.shift(win) - 1.0
    # no forward-filled hole anywhere inside the window, or the name is not ranked
    valid = _fresh(panel, idx).rolling(win + 1, min_periods=win + 1).min() >= 1.0
    mom = mom.where(valid)
    rk = mom.rank(axis=1, ascending=False, method="first")     # 1 = strongest, NaN = not ranked
    nv = mom.notna().sum(axis=1).astype(float)
    if mode == "top":
        ok = nv > top_k                                        # a real selection: ≥ 1 name left out
        sig = (rk <= top_k).astype(float)
        conc = n / top_k
    elif mode == "ls":
        ok = nv >= 2 * top_k                                   # longs and shorts disjoint
        long = (rk <= top_k).astype(float)
        short = rk.gt(nv - top_k, axis=0).astype(float)         # bottom top_k among the valid names
        sig = long - short
        conc = n / (2 * top_k)
    else:  # rank
        ok = nv >= 2
        sig = rk.rsub(nv + 1.0, axis=0).div(nv, axis=0)        # best 1.0 … worst 1/n_valid
        conc = 2.0 * n / (n + 1.0)
    sig = sig.mul(ok.astype(float), axis=0).fillna(0.0).clip(-1.0, 1.0)
    return sig, float(conc)


@register("xsec_momentum")
def xsec_momentum(panel, spec=("top", 63, 0), top_k: int = 2, target_vol: float = 0.12,
                  **kw) -> pd.DataFrame:
    """Cross-sectional momentum: ``spec = (mode, lookback_days, skip_days)``.

    mode "top": long the top_k names by trailing return, flat the rest;
    "ls": long top_k / short bottom_k (risk-balanced); "rank": long-only,
    weight ∝ rank. Sized with the shared vol_target off the fully-long
    reference book, scaled by the design concentration factor so the
    selected names split the benchmark's risk budget (see module docstring).
    """
    mode, lookback, skip = spec
    sig, conc = _signal(panel, str(mode), lookback, skip, top_k)
    return vol_target(sig, panel, float(target_vol) * conc, **kw)


TRIALS = {
    "xsec_momentum": {
        "params": {"target_vol": 0.12, "top_k": 2},
        "grid": {"spec": [("top", 63, 0), ("top", 252, 21), ("ls", 63, 0), ("ls", 252, 21),
                          ("rank", 126, 0)]},
    },
}

# Registered configuration 6: the primary variant on the core 4-asset universe
# over the standard window, fixed parameters (same registry key as grid point 1).
UNIVERSE_CHECK = {"universe": ("btc", "eth", "gold", "silver"),
                  "params": {"target_vol": 0.12, "top_k": 2, "spec": ("top", 63, 0)},
                  "walkforward": {"dev_start": "2016-06-01", "n_folds": 6, "warmup_days": 550,
                                  "rebalance_every": 30}}
