"""crash_filter_beta — the vol-targeted long book with a CRASH FILTER, not a trend gate.

Hypothesis
----------
The benchmark (`vol_target_hold`: OOS Sharpe 1.13, CAGR 18.2%, max DD -18.4%,
2018→2025-06) earns crypto's long drift, and its losses sit in a few deep
legs (2018, 2022). The incumbent gate (`trend_long_only`: MA / TSMOM /
breakout votes) removes those legs but re-trades so often (turnover 3.8/yr
vs 1.7/yr) that whipsaw plus the 24–29 bps round trip gives the saving back:
OOS 0.80 / 9.8% / -12.5%. A DEPTH trigger fires only when price is more than
`exit_depth` below its trailing `high_window`-day high. Crashes are rare and
deep, so it should trade a fraction as often as a moving-average vote while
still stepping aside for 2018/2022-style legs. Re-entry is hysteretic and
slow (heal to within `reenter_depth` of the trailing high, 30-day momentum
non-negative, at least `min_flat` days flat), so bear-market rallies that
stall below the old high do not chop the book. Bet: same drift as the
benchmark, shallower drawdowns, fewer trades than the incumbent.

Mechanism (per asset on its native daily bars, long-only, then `vol_target`)
--------------------------------------------------------------------------
Daily port of quantfirm/strategies/drawdown_filter.py (crypto desk, hourly
BTC: dev OOS Sharpe 1.32 vs 1.12 buy-and-hold, MDD -0.66 vs -0.77):
  dd_t     = close_t / max(close_{t-W+1..t}) - 1                   (W = high_window)
  exit     : dd_t <= -depth_a
             depth_a = exit_depth, or metals_depth for gold/silver when set
             optional vol-spike leg: 7-day return <= mom_exit AND 7-day
             realised vol > vol_mult x its trailing 90-day median
  re-enter : >= min_flat days flat AND dd_t >= -reenter_depth_a AND 30-day
             return >= 0 AND no exit condition on the day
             reenter_depth_a = reenter_depth x depth_a / exit_depth  (same
             shape, scaled with the asset's depth)
State 1 = long, 0 = flat, decided at close t; the backtester executes at
t+1's open. Per-asset states are reindexed to the union calendar and
forward-filled over metals holidays, clipped at 0, then sized by
`vol_target` (equal risk; reference-book scaling, so a flat asset shrinks
the book and never levers the rest). Rolling windows and positive-lag
pct_change only: row t uses data <= t.

External evidence
-----------------
* Kaminski & Lo (2014), "When Do Stop-Loss Rules Stop Losses?", Journal of
  Financial Markets: stop-loss rules add value when returns are positively
  autocorrelated (momentum regimes) and destroy value under mean reversion.
* Han, Zhou & Zhu (2016), "Taming Momentum Crashes: A Simple Stop-Loss
  Strategy", https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2407199 :
  a 10% stop on momentum portfolios cuts the worst monthly loss by roughly
  three quarters and raises the average return.
* Daniel & Moskowitz (2016), "Momentum Crashes", Journal of Financial
  Economics: crashes follow market declines and volatility spikes — the
  rationale for the slow, momentum-confirmed re-entry and the vol-spike leg.
* Faber (2007), "A Quantitative Approach to Tactical Asset Allocation",
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461 : a 10-month
  SMA gate cuts drawdowns across asset classes at ~1 trade a year — the
  incumbent's ancestor; this family keeps the cut and aims at fewer trades.
* Moreira & Muir (2017), "Volatility-Managed Portfolios", Journal of
  Finance — the sizing layer.
* In-house: research/kalshi_perps/tournament.md (2026-09-15.1) and
  quantfirm/strategies/drawdown_filter.py (same idea, hourly bars; the years
  overlap, so it is supportive rather than independent evidence).

Registered grid — 6 configurations, frozen before the first run
---------------------------------------------------------------
  variant         exit_depth  high_window  vol-spike exit                 metals_depth
  d20_w60         0.20        60           off                            = exit_depth
  d20_w120        0.20        120          off                            = exit_depth
  d30_w60         0.30        60           off                            = exit_depth
  d30_w120        0.30        120          off                            = exit_depth
  d30_w60_spike   0.30        60           on: mom_exit -0.15, vol_mult 1.6  = exit_depth
  d30_w60_m12     0.30        60           off                            0.12 (gold, silver)
Fixed: target_vol 0.12, reenter_depth 0.05, min_flat 10, reenter_mom_lb 30;
spike windows 7d return / 7d vol / 90d median are constants carried from the
reference. The variants build on (0.30, 60) because the reference ran 0.30
on a 35-day window. Anything else is a new trial: it gets added to TRIALS
and disclosed in the report.

Selection rule (fixed a priori): the walk-forward's last-fold in-sample pick
is the configuration taken to `backtest --yearly --stress` and `robust`, the
same convention the tournament uses for its stress cell.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align
from ..specs import SPECS
from ..strategies import register, vol_target

# Spike-trigger windows carried from the reference (24*7 / 24*7 / 24*90 hourly bars → days).
SPIKE_MOM_LB = 7
SPIKE_VOL_WINDOW = 7
SPIKE_VOL_REF_WINDOW = 90

BASE = {"exit_depth": 0.30, "high_window": 60, "mom_exit": None, "vol_mult": None, "metals_depth": None}

VARIANTS: dict[str, dict] = {
    "d20_w60": {"exit_depth": 0.20, "high_window": 60},
    "d20_w120": {"exit_depth": 0.20, "high_window": 120},
    "d30_w60": {"exit_depth": 0.30, "high_window": 60},
    "d30_w120": {"exit_depth": 0.30, "high_window": 120},
    "d30_w60_spike": {"exit_depth": 0.30, "high_window": 60, "mom_exit": -0.15, "vol_mult": 1.6},
    "d30_w60_m12": {"exit_depth": 0.30, "high_window": 60, "metals_depth": 0.12},
}


def _crash_state(close: pd.Series, high_window: int, exit_depth: float, reenter_depth: float,
                 min_flat: int, reenter_mom_lb: int, mom_exit: float | None = None,
                 vol_mult: float | None = None) -> pd.Series:
    """1 = long, 0 = flat, on the asset's own bars. Causal: rolling windows and
    positive-lag pct_change only; the state at t depends on rows <= t."""
    roll_max = close.rolling(high_window, min_periods=1).max()
    dd = (close / roll_max - 1.0).to_numpy()
    mom_re = close.pct_change(reenter_mom_lb).to_numpy()
    crash = dd <= -exit_depth
    if mom_exit is not None and vol_mult is not None:
        mom = close.pct_change(SPIKE_MOM_LB).to_numpy()
        vol = close.pct_change().rolling(SPIKE_VOL_WINDOW).std()
        vol_ref = vol.rolling(SPIKE_VOL_REF_WINDOW, min_periods=SPIKE_VOL_WINDOW).median()
        spike = (vol > vol_mult * vol_ref).to_numpy()
        crash = crash | ((mom <= mom_exit) & spike)
    healed = (dd >= -reenter_depth) & (mom_re >= 0.0)

    n = len(close)
    pos = np.ones(n)
    holding = True
    days_flat = 0
    for i in range(n):
        if holding:
            if crash[i]:
                holding = False
                days_flat = 0
        else:
            days_flat += 1
            if days_flat >= min_flat and healed[i] and not crash[i]:
                holding = True
        pos[i] = 1.0 if holding else 0.0
    return pd.Series(pos, index=close.index)


@register("crash_filter_beta")
def crash_filter_beta(panel, target_vol: float = 0.12, variant: str | None = None,
                      exit_depth: float | None = None, high_window: int | None = None,
                      metals_depth: float | None = None, mom_exit: float | None = None,
                      vol_mult: float | None = None, reenter_depth: float = 0.05,
                      min_flat: int = 10, reenter_mom_lb: int = 30, **kw) -> pd.DataFrame:
    """Long by default; flat per asset while its crash filter is tripped; vol-targeted.

    ``variant`` names a registered configuration (VARIANTS); explicit numeric
    arguments override it (used by the perturbation test), and with neither
    the BASE configuration (0.30 / 60, spike off, uniform depth) applies.
    """
    p = dict(BASE)
    if variant is not None:
        p.update(VARIANTS[variant])
    for k, v in (("exit_depth", exit_depth), ("high_window", high_window), ("metals_depth", metals_depth),
                 ("mom_exit", mom_exit), ("vol_mult", vol_mult)):
        if v is not None:
            p[k] = v
    base_depth = max(float(p["exit_depth"]), 1e-9)

    closes = align(panel)
    cols = {}
    for a, d in panel.items():
        cls = SPECS[a].asset_class if a in SPECS else "crypto"
        depth = float(p["metals_depth"]) if (cls == "metals" and p["metals_depth"] is not None) else base_depth
        re_depth = float(reenter_depth) * depth / base_depth
        st = _crash_state(d["close"], int(p["high_window"]), depth, re_depth, int(min_flat),
                          int(reenter_mom_lb), p["mom_exit"], p["vol_mult"])
        cols[a] = st.reindex(closes.index).ffill().fillna(0.0)
    sig = pd.DataFrame(cols, index=closes.index)[list(closes.columns)].clip(lower=0.0)
    return vol_target(sig, panel, target_vol, **kw)


TRIALS = {
    "crash_filter_beta": {
        "params": {"target_vol": 0.12},
        "grid": {"variant": ["d20_w60", "d20_w120", "d30_w60", "d30_w120", "d30_w60_spike", "d30_w60_m12"]},
    }
}
