"""dual_momentum — Antonacci-style dual momentum across two blocs (crypto, metals).

HYPOTHESIS
  The benchmark (vol_target_hold, OOS Sharpe 1.13) is levered beta on four
  assets that all rose over 2018-2025; its drawdowns come from the crypto bear
  legs (2018, 2022) and the metals stalls (2021-22). The incumbent
  trend_long_only (0.80) lost to it because its fast components (10/50 MA,
  21-day sign, 55-day breakout) fire per asset several times a year and pay
  the 29 bps round trip on every whipsaw. A SLOW (6- or 12-month) absolute-
  momentum gate evaluated per BLOC (equal-weight of two correlated assets,
  which averages out single-asset noise) changes state a few times a year, so
  it should keep most of the benchmark's bull-market exposure while sitting in
  3.25% collateral through the bear legs; relative momentum between the blocs
  then tilts risk toward the bloc that is actually trending.

MECHANISM (row t uses data <= t; the backtester executes at t+1's open)
  1. Trailing return per asset over `lookback` CALENDAR days ending `skip` days
     ago: close(t-skip) / close(t-skip-lookback) - 1, computed on a calendar-
     daily forward-filled close frame so crypto (365 bars/yr) and metals (252)
     are measured over the same horizon. An asset counts only if it printed a
     native bar within the last 7 days at every point of that window (this
     excludes xrp during its 2021-01 -> 2023-07 Coinbase delisting instead of
     booking the relisting jump as momentum).
  2. Bloc return = equal-weight mean of its available assets' trailing returns.
  3. Absolute momentum gate: a bloc is eligible iff its return exceeds
     hurdle_apy * lookback / 365 (the 3.25%/yr collateral yield, pro-rated).
  4. Relative momentum: the bloc with the higher trailing return gets risk
     share `top_share`, the other 1 - top_share. Signals: winner 1.0 per asset,
     loser (1 - top_share) / top_share per asset, a gated-out bloc 0. Under
     equal-risk sizing the risk split is top_share : (1 - top_share) and a
     passing winner is held at exactly the benchmark's sleeve size. If only the
     winner passes, the loser's share goes to collateral (GEM's "cash" leg).
  5. Long-only. `vol_target` sizes the book (a weak or partial signal gives a
     smaller book, never a levered one).

EVIDENCE (external to this sample)
  * Antonacci, "Risk Premia Harvesting Through Dual Momentum" (SSRN 2042750)
    and "Absolute Momentum: A Simple Rule-Based Strategy and Universal
    Trend-Following Overlay" (SSRN 2244633): 12-month absolute momentum with a
    T-bill hurdle plus relative momentum between sleeves (GEM), 1974-2012.
  * Moskowitz, Ooi, Pedersen 2012, "Time Series Momentum", JFE 104(2): 12-month
    trailing return predicts the next 1-12 months across 58 futures.
  * Hurst, Ooi, Pedersen 2017, "A Century of Evidence on Trend-Following
    Investing" (SSRN 2993026): 1880-2016, all asset classes including metals.
  * Jegadeesh-Titman 1993 and Asness-Moskowitz-Pedersen 2013 skip the most
    recent month to avoid short-term reversal — the one `skip = 30` config.
  * Liu-Tsyvinski 2021, "Risks and Returns of Cryptocurrency", RFS 34(6):
    time-series momentum in BTC/ETH.
  * Firm tournament (research/kalshi_perps/tournament.md): trend_long_only
    OOS 0.80 / turnover 2.7-5.0 per yr vs vol_target_hold 1.13 / 1.7 per yr —
    whipsaw cost, which is what bloc-level slow gating is meant to remove.

REGISTERED GRID (6 configurations, frozen before the first run)
  dual_momentum       target_vol 0.12; lookback {182, 365} x top_share {0.7, 1.0}   (4)
  dual_momentum_skip  target_vol 0.12; lookback 365, skip 30, top_share 1.0 (GEM 12-1) (1)
  dual_momentum_6     target_vol 0.12; lookback 365, top_share 0.7, crypto bloc
                      (btc, eth, sol, xrp) — run on --universe btc,eth,gold,silver,
                      sol,xrp --start 2021-07-01 (a SHORTER sample); on the 4-asset
                      tournament universe it collapses to dual_momentum(365, 0.7)   (1)
  Lookbacks are calendar days: 182 ~ 6 months, 365 = 12 months (the 126/252
  trading-day conventions would be ~4 and ~8 months on this calendar-daily
  frame, not the 6/12-month horizons the hypothesis names).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align
from ..specs import COLLATERAL_APY
from ..strategies import register, vol_target

MAX_STALE_DAYS = 7          # an asset is "available" on day t if it printed a native bar in (t-7, t]
CRYPTO_BLOC = ("btc", "eth")
METALS_BLOC = ("gold", "silver")


def _availability(panel: dict[str, pd.DataFrame], daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    """True where the asset has a native bar within the last MAX_STALE_DAYS days (causal)."""
    out = {}
    for a, d in panel.items():
        has = pd.Series(1.0, index=d.index.normalize())
        has = has[~has.index.duplicated()].reindex(daily_index).fillna(0.0)
        out[a] = has.rolling(MAX_STALE_DAYS + 1, min_periods=1).max() >= 1.0
    return pd.DataFrame(out, index=daily_index)


def _trailing_returns(panel: dict[str, pd.DataFrame], closes: pd.DataFrame, lookback: int,
                      skip: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Per-asset return over [t-skip-lookback, t-skip] in calendar days, NaN unless the asset was
    continuously available over that window. Returns (ret, avail, daily) on a calendar-daily index."""
    daily = closes.resample("1D").last().ffill()
    avail = _availability(panel, daily.index)
    ret = daily.shift(skip) / daily.shift(skip + lookback) - 1.0
    window = lookback + skip + 1
    cont = avail.astype(float).rolling(window, min_periods=window).min() == 1.0
    return ret.where(cont), avail, daily


def _dual_momentum_signal(panel, closes, lookback, skip, top_share, hurdle_apy, crypto, metals) -> pd.DataFrame:
    ret, avail, daily = _trailing_returns(panel, closes, lookback, skip)
    blocs = {"crypto": [a for a in crypto if a in closes.columns],
             "metals": [a for a in metals if a in closes.columns]}
    blocs = {b: cols for b, cols in blocs.items() if cols}
    hurdle = hurdle_apy * lookback / 365.0
    bloc_ret = {b: ret[cols].mean(axis=1) for b, cols in blocs.items()}          # skipna: available assets only
    passes = {b: (r > hurdle) for b, r in bloc_ret.items()}                     # NaN -> False (not eligible)
    loser = (1.0 - top_share) / top_share
    share = {}
    if len(blocs) == 2:
        rc = bloc_ret["crypto"].fillna(-np.inf)
        rm = bloc_ret["metals"].fillna(-np.inf)
        crypto_wins = rc >= rm                                                   # ties (both -inf) -> gated anyway
        share["crypto"] = pd.Series(np.where(crypto_wins, 1.0, loser), index=daily.index)
        share["metals"] = pd.Series(np.where(crypto_wins, loser, 1.0), index=daily.index)
    else:
        for b in blocs:
            share[b] = pd.Series(1.0, index=daily.index)
    sig = pd.DataFrame(0.0, index=daily.index, columns=closes.columns)
    for b, cols in blocs.items():
        s = share[b] * passes[b].astype(float)
        for a in cols:
            sig[a] = s.where(ret[a].notna() & avail[a], 0.0)                     # an asset needs its own valid history
    return sig.reindex(closes.index).fillna(0.0).clip(0.0, 1.0)


@register("dual_momentum")
def dual_momentum(panel, target_vol: float = 0.12, lookback: int = 365, top_share: float = 0.7,
                  skip: int = 0, hurdle_apy: float = COLLATERAL_APY,
                  crypto: tuple = CRYPTO_BLOC, metals: tuple = METALS_BLOC, **kw) -> pd.DataFrame:
    """Bloc-level dual momentum (absolute gate vs the collateral yield + relative tilt), long-only,
    equal risk per asset via vol_target. `lookback`/`skip` are calendar days."""
    lookback = max(int(lookback), 1)
    skip = max(int(skip), 0)                      # never negative: shift(-k) would be look-ahead
    top_share = min(max(float(top_share), 0.5), 1.0)
    closes = align(panel)
    sig = _dual_momentum_signal(panel, closes, lookback, skip, top_share, float(hurdle_apy),
                                tuple(crypto), tuple(metals))
    return vol_target(sig, panel, target_vol, **kw)


@register("dual_momentum_skip")
def dual_momentum_skip(panel, target_vol: float = 0.12, lookback: int = 365, top_share: float = 1.0,
                       skip: int = 30, **kw) -> pd.DataFrame:
    """GEM 12-1: 12-month lookback skipping the most recent month, 100/0 relative allocation."""
    return dual_momentum(panel, target_vol=target_vol, lookback=lookback, top_share=top_share, skip=skip, **kw)


@register("dual_momentum_6")
def dual_momentum_6(panel, target_vol: float = 0.12, lookback: int = 365, top_share: float = 0.7,
                    crypto: tuple = ("btc", "eth", "sol", "xrp"), **kw) -> pd.DataFrame:
    """Default configuration with a four-asset crypto bloc; meaningful only on the 6-asset universe
    (sol listed 2021-06; xrp excluded by the availability rule during its 2021-01 -> 2023-07 gap)."""
    return dual_momentum(panel, target_vol=target_vol, lookback=lookback, top_share=top_share,
                         crypto=crypto, **kw)


TRIALS = {
    "dual_momentum": {"params": {"target_vol": 0.12},
                      "grid": {"lookback": [182, 365], "top_share": [0.7, 1.0]}},
    "dual_momentum_skip": {"params": {"target_vol": 0.12, "lookback": 365, "skip": 30, "top_share": 1.0},
                           "grid": {}},
    "dual_momentum_6": {"params": {"target_vol": 0.12, "lookback": 365, "top_share": 0.7,
                                   "crypto": ("btc", "eth", "sol", "xrp")},
                        "grid": {}},
}
