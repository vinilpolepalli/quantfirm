"""Book reconstruction — a recovery path, NOT a strategy.

When an outside actor liquidates part of the book (see the 2026-08-04
incident: a legacy routine's +7% take-profit rule sold 3 of 6 positions),
the desk holds cash it must redeploy at an arbitrary point in the strategy's
21-day rebalance cycle. Deploying into stale targets from the last scheduled
re-rank is not obviously right: the vacated slots are fresh decisions, and
the rank-band exists to avoid churning names you *hold* — applying it to
names you no longer hold would invert its purpose into "buy this because you
used to own it."

So reconstruction runs the strategy's own selection rule once, at the latest
bar, seeded with the positions actually held:

  * real incumbents inside the band (and passing absolute momentum) are kept
  * vacated slots are filled with the best-ranked available names
  * inverse-vol weighting, identical math to the strategy

This is the same computation the strategy would perform at its next
scheduled re-rank, run early because the book was destroyed rather than
because a calendar date arrived. It is invoked only via an explicit one-shot
state flag (`reconstruct_pending`) and never fires on its own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .strategies.xsec_refined import _stock_universe


def reconstruct_targets(closes: pd.DataFrame, held: list, params: dict) -> dict:
    """Return {symbol: target_weight} for a one-off rebuild at the last bar."""
    formation = params.get("formation", 189)
    skip = params.get("skip", 21)
    vol_days = params.get("vol_days", 63)
    top_n = params.get("top_n", 6)
    band_mult = params.get("band_mult", 3.0)
    weighting = params.get("weighting", "inv_vol")
    abs_filter = params.get("abs_filter", True)
    vol_scale = params.get("vol_scale", True)

    stocks = _stock_universe(closes.columns)
    mom = closes[stocks].pct_change(formation - skip).shift(skip)
    vol = closes[stocks].pct_change(fill_method=None).rolling(vol_days).std()
    score = (mom / vol.replace(0.0, np.nan)) if vol_scale else mom

    d = closes.index[-1]
    s_row = score.loc[d].dropna()
    m_row = mom.loc[d]
    if len(s_row) < top_n:
        return {}

    ranked = s_row.sort_values(ascending=False)
    band = max(top_n, int(round(band_mult * top_n)))
    band_set = set(ranked.index[:band])

    def _ok(sym: str) -> bool:
        if not abs_filter:
            return True
        v = m_row.get(sym, np.nan)
        return pd.notna(v) and v > 0

    kept = [s for s in held if s in band_set and s in s_row.index and _ok(s)]
    for s in ranked.index:
        if len(kept) >= top_n:
            break
        if s not in kept and _ok(s):
            kept.append(s)

    if not kept:
        return {}
    offense_total = len(kept) / top_n
    if weighting == "inv_vol":
        iv = (1.0 / vol.loc[d].reindex(kept)).replace([np.inf, -np.inf], np.nan).dropna()
        if len(iv):
            ww = iv / iv.sum() * offense_total
            return {s: float(x) for s, x in ww.items()}
    return {s: offense_total / len(kept) for s in kept}
