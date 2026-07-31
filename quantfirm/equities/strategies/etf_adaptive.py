"""ETF adaptive allocation (bias-free track) — etf-adaptive desk.

Top-N of a diverse 9-ETF menu by blended multi-horizon momentum, monthly
rebalance, with crash gates. Tuned champion (dev walk-forward, 38 trials):
slow 3/6/12m equal blend (no 1m leg — it churns and whipsaws), top-4, equal
weight, per-asset absolute-momentum gate only (canary gates tested but they
trade 2018-style protection for too much upside elsewhere in dev).

Gate layers available:
  1. Canary gate (VAA/PAA style, default OFF): breadth of negative blended
     momentum across canary assets (EEM + LQD) shifts a matching fraction of
     the book into defense.
  2. Absolute-momentum filter (default ON): any top-N slot whose own blended
     momentum is not positive forfeits its weight to defense.

Defense is the best of a bond/short-duration menu by its own blended momentum;
if even that is non-positive, the slot stays in cash (earns 0 in the sim).

Everything is causal: the weight row at date t uses closes <= t only
(pct_change / rolling look strictly backward), and the backtester trades row t
at close t+1. Rows are emitted only on rebalance dates (every 21 bars).

Account fit: max positions = top_n + 1 safe ETF (<= 15), monthly cadence,
long-only, fractional-dollar friendly (all liquid ETFs).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

# Diverse, survivorship-free menu: US large/small, intl DM/EM, long bonds,
# gold, broad commodities, REITs. All have full history in the panel.
DEFAULT_MENU = ("SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD", "DBC", "VNQ")
DEFAULT_SAFE = ("IEF", "SHY", "TLT")
DEFAULT_CANARIES = ("EEM", "LQD")

LOOKBACKS = (21, 63, 126, 252)  # 1 / 3 / 6 / 12 months in trading days


def _blend_momentum(closes: pd.DataFrame, weights) -> pd.DataFrame:
    """Weighted sum of 1/3/6/12m total returns. With Keller's 13612W weights
    (12, 4, 2, 1) each term is ~annualized, so the sign is a sensible
    absolute-momentum gate as well as a ranking signal."""
    out = None
    for lb, wt in zip(LOOKBACKS, weights):
        if wt == 0:
            continue
        term = closes.pct_change(lb) * float(wt)
        out = term if out is None else out + term
    return out


@register("etf_adaptive")
def etf_adaptive(closes: pd.DataFrame,
                 menu=DEFAULT_MENU,
                 top_n: int = 4,
                 mom_weights=(0.0, 1.0, 1.0, 1.0),
                 weighting: str = "equal",
                 vol_days: int = 63,
                 every: int = 21,
                 canaries=DEFAULT_CANARIES,
                 gate: str = "none",
                 abs_filter: bool = True,
                 safe_menu=DEFAULT_SAFE,
                 cash_gate: bool = True) -> pd.DataFrame:
    """Blended-momentum top-N ETF rotation with canary + absolute crash gates.

    gate: "breadth" (defense fraction = share of canaries with negative
    momentum), "any" (fully defensive if any canary is negative), or "none".
    """
    menu = [s for s in menu if s in closes.columns]
    safe_menu = [s for s in safe_menu if s in closes.columns]
    canaries = [s for s in canaries if s in closes.columns]

    blend = _blend_momentum(closes, mom_weights)
    vol = closes.pct_change(fill_method=None).rolling(vol_days).std()

    dates = closes.index[::every]
    w = pd.DataFrame(0.0, index=dates, columns=closes.columns)

    for d in dates:
        row = blend.loc[d]
        vals = row.reindex(menu).dropna()
        if len(vals) < top_n:          # warmup — stay in cash
            continue

        # --- canary gate ---
        if gate != "none" and canaries:
            cvals = row.reindex(canaries).dropna()
            if len(cvals) == 0:
                def_frac = 0.0
            elif gate == "any":
                def_frac = 1.0 if (cvals <= 0).any() else 0.0
            else:                       # breadth
                def_frac = float((cvals <= 0).mean())
        else:
            def_frac = 0.0

        sleeve = 1.0 - def_frac         # nominal offense sleeve

        # --- offense picks + absolute momentum filter ---
        ranked = vals.sort_values(ascending=False)
        picks = list(ranked.index[:top_n])
        if abs_filter:
            passers = [s for s in picks if ranked[s] > 0]
        else:
            passers = picks
        # each failed slot forfeits sleeve/top_n to defense
        offense_total = sleeve * len(passers) / top_n
        def_total = 1.0 - offense_total

        if passers and offense_total > 0:
            if weighting == "inv_vol":
                iv = 1.0 / vol.loc[d].reindex(passers)
                iv = iv.replace([np.inf, -np.inf], np.nan).dropna()
                if len(iv):
                    ww = iv / iv.sum() * offense_total
                    for s, x in ww.items():
                        w.at[d, s] = float(x)
                else:
                    for s in passers:
                        w.at[d, s] = offense_total / len(passers)
            else:                       # equal
                for s in passers:
                    w.at[d, s] = offense_total / len(passers)

        # --- defense sleeve ---
        if def_total > 1e-9 and safe_menu:
            svals = row.reindex(safe_menu).dropna()
            if len(svals):
                best = svals.idxmax()
                if (not cash_gate) or svals[best] > 0:
                    w.at[d, best] = w.at[d, best] + def_total
                # else: stay in cash (weight 0)
    return w
