"""trend_v2 — a second attempt at the long-only trend incumbent (``trend_long_only``).

REGISTERED 2026-09-15 BEFORE THE FIRST RUN (CAMPAIGN.md rule 2). Family
module for the perps research campaign; DEV window only.

Hypothesis
----------
The incumbent averages three noisy binary trend signals (multi-lookback
TSMOM signs, three MA-crossover signs, a 55/20 Donchian), clips at zero and
scales the REFERENCE fully-long book to 12% vol (OOS Sharpe 0.80, 6/6 folds,
-12.5% OOS DD; benchmark ``vol_target_hold`` 1.13 / -18.4%). Two costs
follow from that construction: (i) binary signals flip, so the book
re-trades on noise (3.76 turnover/yr, 55 bps/yr of fees at tier 0), and
(ii) the clipped average signal sits near one half most of the time, so the
book runs at ~8% realised vol against a 12% target — the risk budget is idle.
trend_v2 keeps the economic bet (long-only trend in BTC, ETH, gold, silver,
vol-targeted, weekly band rebalancing unless stated) and changes ONLY the
signal construction and the sizing:

  (a) continuous trend strength — Baz, Granger, Harvey, Le Roux & Sargaison
      (2015), "Dissecting Investment Strategies in the Cross Section and Time
      Series" (SSRN 2695101), trend section: for EWMA time-scale pairs
      (S,L) in (8,24), (16,48), (32,96) with decay 1-1/n,
      x_k = EWMA_S(P) - EWMA_L(P);  y_k = x_k / sd_63(P);
      z_k = y_k / sd_252(y_k);  u_k = z_k * exp(-z_k^2/4) / 0.89;
      signal = mean_k(u_k), clipped at 0 (long-only). A smooth response
      trades less on noise than three sign flips and SHRINKS exposure in
      over-extended trends (|z| > sqrt(2)), where crypto reversals live.
  (b) slower cadence — the 12-month TSMOM sign only, executed monthly
      (``--every 30``; CAMPAIGN.md rule 5 allows the cadence change when
      cadence is the hypothesis). Moskowitz, Ooi & Pedersen (2012, JFE,
      "Time Series Momentum") and Hurst, Ooi & Pedersen (2017, JPM, "A
      Century of Evidence on Trend-Following Investing") use a 12-month sign
      at a monthly cadence; it flips ~1-2x/yr per asset, so fees fall to a
      few round trips a year.
  (c) skip-month TSMOM (12-1) — the momentum literature's convention
      (Jegadeesh & Titman 1993; Asness, Moskowitz & Pedersen 2013, "Value
      and Momentum Everywhere", JF) to step over the 1-month reversal. In
      crypto the 1-4 week horizon is where Liu & Tsyvinski (2021, RFS,
      "Risks and Returns of Cryptocurrency") find momentum, so skipping it
      may hurt: (b) vs (c) is the test.
  (d) vol-target the SIGNAL-STRENGTH-WEIGHTED book: ``sizing="live"`` scales
      the live book (weights proportional to signal_i / sigma_i) so that ITS
      ex-ante vol under the trailing 120-day covariance equals the target,
      capped at ``live_cap`` (2.0) times the reference-book scaling that
      ``vol_target`` uses. Two full-strength names therefore reach 12%; a
      weak signal still means a smaller book (never more than 2x the
      reference scaling), so weak signals are never levered up. Trailing
      windows only: causal. (Passing ``max_scale`` would not do this: for
      this universe target/pv_ref is ~0.17, far below the 3.0 cap.)
  (e) ONE 6-asset run (btc, eth, gold, silver, sol, xrp; ``--start
      2021-07-01``) of the headline configuration, trend_v2_baz
      sizing=live — chosen here, before any result. Prior for vol-targeting
      risk assets: Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & van
      Hemert (2018, JPM, "The Impact of Volatility Targeting").

Data and causality
------------------
Daily closes only, from the campaign panel (Coinbase spot for crypto, Yahoo
front-month futures for metals). Signals are computed on each asset's
NATIVE bars (metals do not trade weekends; windows are in bars, months are
converted with BARS_PER_YEAR: 12 months = 365 crypto / 252 metals bars,
1 month = 30 / 21), then reindexed to the union calendar and forward-filled,
the treatment ``asset_vol`` and the Donchian signal already use. Rolling /
EWMA windows and shifts only; row t uses data <= t; the backtester executes
at t+1's open. No aux series.

Registered grid (<= 6 configurations; verbatim in TRIALS below)
---------------------------------------------------------------
  1. trend_v2_baz         target_vol=0.12, sizing=ref                 weekly    (a)
  2. trend_v2_baz         target_vol=0.12, sizing=live                weekly    (a)+(d)
  3. trend_v2_tsmom       target_vol=0.12, sizing=ref, skip_months=0  every=30  (b)
  4. trend_v2_tsmom       target_vol=0.12, sizing=ref, skip_months=1  every=30  (c)
  5. trend_v2_tsmom_live  target_vol=0.12 (skip_months=0, live_cap=2) every=30  (b)+(d)
  6. configuration 2 on btc,eth,gold,silver,sol,xrp from 2021-07-01              (e)
Every other parameter is frozen at the literature value shown in the
signatures below. Nothing else will be swept.

CLI runs (repo root; the walk-forward is 6 folds, warmup 550, dev start
2016-06-01 unless stated):
  walkforward --strategy trend_v2_baz   --params '{"target_vol": 0.12}' --grid '{"sizing": ["ref", "live"]}'
  walkforward --strategy trend_v2_tsmom --params '{"target_vol": 0.12, "sizing": "ref"}' --grid '{"skip_months": [0, 1]}' --every 30
  walkforward --strategy trend_v2_tsmom_live --params '{"target_vol": 0.12}' --every 30
  walkforward --strategy trend_v2_baz --params '{"target_vol": 0.12, "sizing": "live"}' \
      --universe btc,eth,gold,silver,sol,xrp --start 2021-07-01
Selection rule, fixed in advance: the configuration for the ``backtest
--yearly --stress`` and ``robust`` runs is the LAST-FOLD pick of the 4-asset
walk-forward call with the highest ``oos_sharpe_concat`` (the tournament's
own rule), run at that call's cadence.

Note for the referee: the tournament runs every TRIALS entry at its single
cfg (weekly). Configurations 3-5 are registered at a 30-day cadence; a
weekly run of them is a different trial and is not what this family's
report shows.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align
from ..specs import SPECS
from ..strategies import BARS_PER_YEAR, asset_vol, cap_weights, portfolio_vol, register, vol_target

# Baz et al. (2015) EWMA time-scale pairs (short, long), in bars.
BAZ_PAIRS = ((8, 24), (16, 48), (32, 96))
BAZ_NORM = 0.89   # max of x*exp(-x^2/4) is ~0.858 at x = sqrt(2); the paper divides by 0.89


# ---------------------------------------------------------------- signals
def _bars(asset: str, months: float) -> int:
    """Months -> the asset's native bars (365/yr crypto, 252/yr metals)."""
    bpy = BARS_PER_YEAR[SPECS[asset].asset_class] if asset in SPECS else 365
    return max(int(round(bpy * months / 12.0)), 0)


def _baz_signal(panel: dict[str, pd.DataFrame], idx: pd.DatetimeIndex, pairs=BAZ_PAIRS,
                price_vol_window: int = 63, norm_window: int = 252) -> pd.DataFrame:
    """Baz et al. (2015) continuous trend on native bars, in ~[-0.96, 0.96]."""
    cols = {}
    for a, d in panel.items():
        p = d["close"].astype(float)
        pv = p.rolling(price_vol_window).std()                      # sd of the price level, 63 bars
        u = None
        for s, l in pairs:
            x = (p.ewm(alpha=1.0 / s, adjust=True, min_periods=s).mean()
                 - p.ewm(alpha=1.0 / l, adjust=True, min_periods=l).mean())
            y = (x / pv).replace([np.inf, -np.inf], np.nan)
            z = (y / y.rolling(norm_window).std()).replace([np.inf, -np.inf], np.nan)
            r = z * np.exp(-(z ** 2) / 4.0) / BAZ_NORM
            u = r if u is None else u + r
        cols[a] = (u / len(pairs)).reindex(idx).ffill()
    return pd.DataFrame(cols, index=idx).fillna(0.0)


def _tsmom_sign(panel: dict[str, pd.DataFrame], idx: pd.DatetimeIndex, months: int = 12,
                skip_months: int = 0) -> pd.DataFrame:
    """sign(P[t-skip] / P[t-months] - 1) on native bars; skip_months=1 gives 12-1."""
    cols = {}
    for a, d in panel.items():
        p = d["close"].astype(float)
        lb, sk = _bars(a, months), _bars(a, skip_months)
        if lb <= sk:                                                 # degenerate (perturbation guard)
            lb = sk + 1
        ret = p.shift(sk) / p.shift(lb) - 1.0
        cols[a] = np.sign(ret).reindex(idx).ffill()
    return pd.DataFrame(cols, index=idx).fillna(0.0)


# ----------------------------------------------------------------- sizing
def _size(sig: pd.DataFrame, panel: dict[str, pd.DataFrame], target_vol: float, sizing: str = "ref",
          live_cap: float = 2.0, vol_window: int = 60, cov_window: int = 120, max_gross: float = 1.5,
          max_asset: float = 0.75, min_liq_distance: float = 0.35, max_scale: float = 3.0,
          step: float = 0.05) -> pd.DataFrame:
    """Long-only clip, then either the core ``vol_target`` (reference-book
    scaling, ``sizing="ref"``) or the signal-strength-weighted book scaled to
    ``target_vol`` itself, capped at ``live_cap`` x the reference scaling
    (``sizing="live"``). Same caps and 0.05 step as the core."""
    sig = sig.clip(lower=0.0)
    if sizing == "ref":
        return vol_target(sig, panel, target_vol, vol_window=vol_window, cov_window=cov_window,
                          max_gross=max_gross, max_asset=max_asset, min_liq_distance=min_liq_distance,
                          max_scale=max_scale, step=step)
    if sizing != "live":
        raise ValueError(f"sizing must be 'ref' or 'live', got {sizing!r}")
    closes = align(panel)
    rets = closes.pct_change()
    vol = asset_vol(panel, vol_window)
    n = len(sig.columns)
    ref = (1.0 / vol) / n                                            # the fully-long equal-risk book
    raw = sig.div(vol).div(n).fillna(0.0)                            # the live strength-weighted book
    k_ref = (target_vol / portfolio_vol(ref, rets, cov_window)).clip(upper=max_scale)
    pv_live = portfolio_vol(raw, rets, cov_window)
    k_live = (target_vol / pv_live.where(pv_live > 0)).fillna(np.inf)   # empty book: weights are 0 anyway
    k = np.minimum(k_live, live_cap * k_ref)                        # NaN until the covariance window is full
    w = raw.mul(k, axis=0).fillna(0.0)
    if step and step > 0:
        w = (w / step).round() * step
    return cap_weights(w, max_gross, max_asset, min_liq_distance)


# ------------------------------------------------------------- strategies
@register("trend_v2_baz")
def trend_v2_baz(panel, target_vol: float = 0.12, pairs=BAZ_PAIRS, price_vol_window: int = 63,
                 norm_window: int = 252, sizing: str = "ref", live_cap: float = 2.0, **kw) -> pd.DataFrame:
    """Configurations 1-2 (and 6): long-only Baz et al. (2015) continuous
    trend, vol-targeted off the reference book (ref) or the live book (live)."""
    idx = align(panel).index
    sig = _baz_signal(panel, idx, pairs, price_vol_window, norm_window)
    return _size(sig, panel, target_vol, sizing, live_cap, **kw)


@register("trend_v2_tsmom")
def trend_v2_tsmom(panel, target_vol: float = 0.12, months: int = 12, skip_months: int = 0,
                   sizing: str = "ref", live_cap: float = 2.0, **kw) -> pd.DataFrame:
    """Configurations 3-4: long-only 12-month TSMOM sign (skip_months=1 for
    12-1), registered for a 30-day rebalance cadence (``--every 30``)."""
    idx = align(panel).index
    sig = _tsmom_sign(panel, idx, months, skip_months)
    return _size(sig, panel, target_vol, sizing, live_cap, **kw)


@register("trend_v2_tsmom_live")
def trend_v2_tsmom_live(panel, target_vol: float = 0.12, months: int = 12, skip_months: int = 0,
                        live_cap: float = 2.0, **kw) -> pd.DataFrame:
    """Configuration 5: the 12-month sign with the breadth-weighted book
    vol-targeted (``sizing="live"``), 30-day cadence. A separate name so the
    registered set stays at five parameter sets instead of a 2x2 product."""
    return trend_v2_tsmom(panel, target_vol=target_vol, months=months, skip_months=skip_months,
                          sizing="live", live_cap=live_cap, **kw)


# Frozen before the first run. Configurations 3-5 are meant for --every 30.
TRIALS = {
    "trend_v2_baz": {"params": {"target_vol": 0.12}, "grid": {"sizing": ["ref", "live"]}},
    "trend_v2_tsmom": {"params": {"target_vol": 0.12, "sizing": "ref"}, "grid": {"skip_months": [0, 1]}},
    "trend_v2_tsmom_live": {"params": {"target_vol": 0.12}, "grid": {}},
}
