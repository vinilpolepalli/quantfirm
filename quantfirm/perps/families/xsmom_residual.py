"""xsmom_residual — market-residual cross-sectional momentum, as a SLEEVE.

REGISTERED 2026-09-15 BEFORE THE FIRST BACKTEST (CAMPAIGN.md rule 2, CAMPAIGN2
for the wide-universe rules). DEV window only.

Hypothesis
----------
Round 1's cross-sectional momentum family scored 0.154 on six assets and was
dismissed. Round 2's own screens then found nothing in a raw cross-sectional
rank on twenty names at any formation from 30 to 365 days. Both tested the
RAW sort, and on a universe whose first principal component is two thirds of
the variance a raw return sort is a beta sort: it goes long the high-beta
alts after the market rises. That is the long book again, which is why it
correlated 0.745 with it in round 1.

The claim here is different and narrower. Strip each name's beta to the
equal-weight crypto market, rank on the residual, and the sort is no longer
directional. Two measurements say the breadth exists once the market is
removed even though it does not exist before:

* raw daily correlation among the crypto names averages 0.594 and the first
  component is about two thirds of the variance, so a long book carries about
  two independent bets however many names it holds;
* after removing the equal-weight market, the residual correlation averages
  about -0.08 with an eigenvalue participation ratio near 9.5 of 12, and
  per-name idiosyncratic dispersion runs about 45% a year.

So a market-neutral book on twelve names has roughly nine bets where a long
book on the same names has two. That is the whole reason this is not round
1's family in new clothes.

The horizon is not a free parameter. Borri, Liu, Tsyvinski & Wu (2026,
arXiv:2510.14435; 16,468 coins, 2014-2025) find cross-sectional momentum at a
TWO-WEEK formation with a one-week hold: +2.6%/week full sample (t 3.89) and
+2.1%/week post-2020 (t 3.70), with 12-week and 24-week momentum
insignificant. Round 2's screens tested 30, 60, 90, 180 and 365 days and
found nothing, which is consistent with that paper rather than against it:
they tested the horizons the paper says are dead. This family tests the one
the evidence supports, and only that one.

Why it is registered as a SLEEVE, not as a replacement
------------------------------------------------------
Every round-1 candidate was 0.68 to 0.996 correlated with the long book, and
an overlay that correlated cannot raise portfolio Sharpe whatever it scores
standalone. A dollar-neutral residual book is close to uncorrelated with the
long book by construction, and for an uncorrelated sleeve the standalone
Sharpe is nearly irrelevant: what matters is what the BLEND does. The family
therefore reports, as headline numbers, the sleeve's correlation to
``vol_target_hold`` and the blended book's Sharpe and drawdown, not only its
own.

Mechanism and who pays
----------------------
Under-reaction to coin-specific news, plus retail flow that rotates into the
last fortnight's leader after the move. The payer is the slower flow. This is
a crowded, well-published effect and the prior should be that most of it is
gone; the test is whether any survives on twenty large, exchange-listed names
at this venue's costs.

Data and causality
------------------
Daily closes from the campaign panel only. Availability is the native-bar
mask, so a name contributes nothing before it lists or inside a delisting
gap, and no return spans a gap. Beta is a 180-day rolling regression on the
equal-weight market of the names available that day, computed from returns up
to and including t and used for the weight decided at t, which the backtester
executes at t+1's open. Every window is trailing. Nothing after 2025-07-01 is
read.

Registered grid (verbatim, written before the first run)
--------------------------------------------------------
Two points, not six. The analyst who proposed this specified k=2 and k=3 and
said explicitly not to sweep the lookback; the registry already carries 79
distinct configurations and every extra point raises the deflated-Sharpe bar
for every future idea.

    TRIALS = {"xsmom_residual": {"params": {"target_vol": 0.12, "lookback": 14,
                                            "beta_window": 180, "tranches": 7},
                                 "grid": {"k": [2, 3]}}}
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align, availability
from ..strategies import register, asset_vol, cap_weights
from ..specs import SPECS


def _residual_returns(rets: pd.DataFrame, av: pd.DataFrame, beta_window: int) -> pd.DataFrame:
    """Daily returns with each name's beta to the equal-weight market removed.

    Trailing windows only: the beta used on day t is estimated from returns up
    to and including t, which is the information a decision made at that close
    actually has.
    """
    mkt = rets.where(av).mean(axis=1)
    cov = rets.mul(mkt, axis=0).rolling(beta_window, min_periods=beta_window // 2).mean() \
        - rets.rolling(beta_window, min_periods=beta_window // 2).mean().mul(
            mkt.rolling(beta_window, min_periods=beta_window // 2).mean(), axis=0)
    var = mkt.rolling(beta_window, min_periods=beta_window // 2).var()
    beta = cov.div(var, axis=0)
    return rets.sub(beta.mul(mkt, axis=0))


@register("xsmom_residual")
def xsmom_residual(panel, target_vol: float = 0.12, lookback: int = 14,
                   beta_window: int = 180, k: int = 3, tranches: int = 7,
                   vol_window: int = 60, max_gross: float = 1.5,
                   max_asset: float = 0.75, min_liq_distance: float = 0.35,
                   **kw) -> pd.DataFrame:
    """Dollar-neutral: long the top ``k`` residual-momentum names, short the bottom ``k``.

    ``tranches`` overlapping weekly books, each rebalancing on a different day
    of the week and averaged, so the result does not depend on which weekday
    the backtest happens to start. Metals are excluded from the ranking: the
    market being residualised is the crypto market, and gold is the one asset
    in the book that is not part of it.
    """
    closes = align(panel)
    av = availability(panel).reindex(index=closes.index, columns=closes.columns).fillna(False)
    names = [a for a in closes.columns
             if a in SPECS and SPECS[a].asset_class == "crypto" and SPECS[a].quotes]
    if len(names) < 2 * k + 1:
        return pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    c, m = closes[names], av[names]
    rets = np.log(c).diff().where(m & m.shift(1).fillna(False))
    resid = _residual_returns(rets, m, beta_window)
    sig = resid.rolling(lookback, min_periods=lookback).sum().where(m)
    vol = asset_vol(panel, vol_window).reindex(columns=names)

    books = []
    for offset in range(max(1, tranches)):
        w = pd.DataFrame(0.0, index=closes.index, columns=names)
        rows = range(offset, len(closes.index), max(1, tranches))
        for i in rows:
            s = sig.iloc[i].dropna()
            s = s[[a for a in s.index if bool(m.iloc[i][a])]]
            if len(s) < 2 * k:
                continue
            order = s.sort_values()
            lo, hi = list(order.index[:k]), list(order.index[-k:])
            iv = (1.0 / vol.iloc[i]).replace([np.inf, -np.inf], np.nan)
            for legs, sign in ((hi, 1.0), (lo, -1.0)):
                z = iv[legs].dropna()
                if z.empty or z.sum() <= 0:
                    continue
                w.iloc[i, [w.columns.get_loc(a) for a in z.index]] = sign * (z / z.sum()).to_numpy()
        books.append(w.replace(0.0, np.nan).ffill().fillna(0.0))
    raw = sum(books) / len(books)
    raw = raw.where(m, 0.0)

    # scale the sleeve to its own volatility target on a trailing estimate
    pr = (raw.shift(1) * rets).sum(axis=1)
    realised = pr.rolling(60, min_periods=30).std() * np.sqrt(365)
    scale = (target_vol / realised).replace([np.inf, -np.inf], np.nan).clip(upper=3.0).shift(1)
    w = raw.mul(scale, axis=0).fillna(0.0)
    out = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    out[names] = w
    return cap_weights(out, max_gross, max_asset, min_liq_distance)


TRIALS = {
    "xsmom_residual": {"params": {"target_vol": 0.12, "lookback": 14,
                                  "beta_window": 180, "tranches": 7},
                       "grid": {"k": [2, 3]}},
}
