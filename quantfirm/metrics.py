"""Performance metrics, including overfitting-aware ones.

The swarm's eval lives here. Per the firm charter: the metric is what makes
the swarm work — so it must be hard to game. Key ideas:
  * everything is NET of venue costs (costs.py)
  * walk-forward out-of-sample Sharpe, not full-sample Sharpe
  * deflated Sharpe ratio (Bailey & Lopez de Prado 2014) penalises the
    number of strategies/parameter sets tried across the whole tournament
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

HOURS_PER_YEAR = 24 * 365


def ann_factor(bars_per_year: float) -> float:
    return math.sqrt(bars_per_year)


def sharpe(returns: pd.Series, bars_per_year: float = HOURS_PER_YEAR) -> float:
    r = returns.dropna()
    if len(r) < 10 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * ann_factor(bars_per_year))


def cagr(equity: pd.Series, bars_per_year: float = HOURS_PER_YEAR) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    years = len(equity) / bars_per_year
    if years <= 0:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    if total <= 0:
        return -1.0
    return float(total ** (1 / years) - 1)


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1
    return float(dd.min())


def annual_turnover(position: pd.Series, bars_per_year: float = HOURS_PER_YEAR) -> float:
    """Sum of |position changes| per year (2.0 = one full round trip)."""
    trades = position.diff().abs().sum()
    years = len(position) / bars_per_year
    return float(trades / years) if years > 0 else 0.0


def deflated_sharpe(observed_sr: float, n_trials: int, n_obs: int,
                    skew: float = 0.0, kurt: float = 3.0) -> float:
    """Probability the true Sharpe exceeds the expected max of n_trials noise
    strategies (Bailey & Lopez de Prado). Returns a probability in [0, 1];
    >= 0.95 is the approval bar. Inputs are per-bar (non-annualised) SR.
    """
    if n_obs < 20 or n_trials < 1:
        return 0.0
    emc = 0.5772156649
    max_z = ((1 - emc) * _norm_ppf(1 - 1.0 / n_trials)
             + emc * _norm_ppf(1 - 1.0 / (n_trials * math.e))) if n_trials > 1 else 0.0
    sr0 = max_z / math.sqrt(n_obs - 1)
    denom = math.sqrt(max(1e-12, (1 - skew * observed_sr
                                  + (kurt - 1) / 4 * observed_sr ** 2) / (n_obs - 1)))
    return float(_norm_cdf((observed_sr - sr0) / denom))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_ppf(p: float) -> float:
    # Acklam's rational approximation; adequate for DSR purposes.
    if not 0 < p < 1:
        raise ValueError("p must be in (0,1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def summary(returns: pd.Series, position: pd.Series, equity: pd.Series,
            bars_per_year: float = HOURS_PER_YEAR) -> dict:
    return {
        "net_sharpe": round(sharpe(returns, bars_per_year), 3),
        "cagr": round(cagr(equity, bars_per_year), 4),
        "max_drawdown": round(max_drawdown(equity), 4),
        "annual_turnover": round(annual_turnover(position, bars_per_year), 2),
        "avg_exposure": round(float(position.mean()), 3),
        "n_bars": int(len(returns)),
        "total_return": round(float(equity.iloc[-1] / equity.iloc[0] - 1), 4) if len(equity) else 0.0,
    }
