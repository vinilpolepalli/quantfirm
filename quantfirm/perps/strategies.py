"""Pre-registered perps strategies: (panel, **params) -> target weights.

A strategy maps a dict of daily OHLCV frames (one per asset) to a DataFrame of
TARGET NOTIONAL WEIGHTS — signed fraction of account equity per asset, decided
at the close of day t. The backtester executes them at the NEXT day's open,
holds contracts (not weights) between rebalances, and charges fees, funding,
interest and liquidation. Nothing here knows about fills.

Every function is causal by construction (rolling windows and shifts only);
``tests/test_perps.py`` checks that appending future bars does not change
past rows. Parameters are frozen here; sweeping them is a registered trial
(the tournament counts every grid point for the deflated Sharpe).

Economic priors (external to this sample):
  * Time-series momentum works across asset classes for a century
    (Moskowitz-Ooi-Pedersen 2012; Hurst-Ooi-Pedersen 2017) and in crypto at
    1–4 week horizons (Liu-Tsyvinski 2021). Its edge is a handful of trades a
    year, which is what a 12 bps taker fee needs.
  * Vol targeting lowers drawdowns and raises Sharpe where vol is persistent
    (Moreira-Muir 2017); crypto vol is very persistent.
  * Funding carry is not a strategy on Kalshi: rates below 0.01%/interval
    (≈11%/yr) round to zero and 55–97% of historical intervals ARE zero.
  * Short-horizon mean reversion / market making are excluded by arithmetic:
    the tier-0 round trip is 24–29 bps of notional.
Controls (buy_hold, vol_target_hold, flat, coin_flip) set the bar: a
candidate that cannot beat vol-scaled long-only out of sample has no edge.

Sizing API, in the order a family module should reach for it:
  * ``tradable(panel)`` / ``gate_signal(sig, panel)`` — the venue lists 20
    tradable perps whose price proxies begin between 2000 and 2026, and one of
    them (xrp) stopped quoting for 905 days mid-history. These two carry
    tradability as a boolean so a signal is never sized on a forward-filled
    price. Import them here; do not re-derive the rule per family.
  * ``breadth_vol_target(sig, panel, target_vol)`` — the wide-universe sizer:
    availability mask, pairwise-complete covariance with a minimum-observations
    rule, and a weight step that scales with the number of names.
  * ``vol_target(...)`` — the core sizer. Its defaults are FROZEN at the
    four-asset behaviour every published number was produced with; the breadth
    behaviour is opt-in through ``cov_min_obs`` and ``available``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import align, availability
from .specs import RESEARCH_UNIVERSE, SPECS, max_weight_for_distance

REGISTRY: dict = {}
BARS_PER_YEAR = {"crypto": 365, "metals": 252}


def register(name: str, control: bool = False):
    def deco(fn):
        REGISTRY[name] = fn
        fn.strategy_name = name
        fn.is_control = control
        return fn
    return deco


# ----------------------------------------------------------------- helpers
def asset_vol(panel: dict[str, pd.DataFrame], window: int = 30,
              floor: float = 0.05) -> pd.DataFrame:
    """Annualised realised vol per asset on its NATIVE bars (metals do not
    trade weekends, so their vol must not be diluted by zero returns),
    reindexed to the union calendar and forward-filled."""
    idx = align(panel).index
    out = {}
    for a, d in panel.items():
        bpy = BARS_PER_YEAR[SPECS[a].asset_class] if a in SPECS else 365
        r = d["close"].pct_change()
        v = r.rolling(window).std() * np.sqrt(bpy)
        out[a] = v.reindex(idx).ffill().clip(lower=floor)
    return pd.DataFrame(out)


# ------------------------------------------------- availability (breadth API)
# A wide universe lists at different times and some of it stops quoting for
# months (XRP was off Coinbase 2021-01-19 → 2023-07-13). ``align()`` forward-
# fills, on purpose, so a Saturday BTC bar does not orphan gold — which means a
# price that no longer exists is indistinguishable from one that does. These
# two helpers carry tradability as a separate boolean, so every family module
# gates its signal the same way instead of each designer inventing a rule.
DEFAULT_MAX_STALE_DAYS = 7


def tradable(panel: dict[str, pd.DataFrame], max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
             index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Bool frame on the aligned index: was each asset actually quoting?

    Thin re-export of ``data.availability`` so families import one module.
    True iff the asset printed a NATIVE bar within the last ``max_stale_days``:
    False before its first bar, False inside a delisting gap, True across a
    metals weekend or holiday (which is why the default is 7 days, not 1).
    """
    return availability(panel, max_stale_days=max_stale_days, index=index)


def gate_signal(signal: pd.DataFrame, panel: dict[str, pd.DataFrame] | None = None,
                max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
                mask: pd.DataFrame | None = None) -> pd.DataFrame:
    """Zero a raw signal wherever the asset was not tradable that day.

    Pass a ``panel`` (the mask is derived from it) or a precomputed ``mask``.
    A signal column with no entry in the mask is zeroed, not trusted: no bar
    means no price, and no price means nothing to size. Use this BEFORE
    ``vol_target``, and hand the sizer the SAME mask (``available=``): gating
    the signal alone still leaves the fully-long reference book and the
    covariance reading a forward-filled flat line as real data.
    """
    if mask is None:
        if panel is None:
            raise ValueError("gate_signal needs either a panel or a mask")
        mask = tradable(panel, max_stale_days, index=signal.index)
    m = (mask.reindex(index=signal.index, columns=signal.columns)
             .fillna(False).astype(bool))
    return signal.where(m, 0.0)


def usable_history(returns: pd.DataFrame, window: int, min_obs: int) -> pd.DataFrame:
    """Bool frame: does each asset have ≥ ``min_obs`` non-NaN returns in the
    trailing ``window`` rows ending at t? This is the minimum-observations rule
    ``portfolio_vol`` and ``vol_target`` share, exposed so a caller can see
    exactly which names were in the book on a given day."""
    return returns.notna().rolling(window, min_periods=1).sum() >= min_obs


# --------------------------------------------------------------- vol sizing
def _pairwise_cov(block: np.ndarray, min_obs: int) -> tuple[np.ndarray, np.ndarray]:
    """Pairwise-complete covariance of a (window × k) block that may hold NaN.

    cov_ij is estimated on the rows where BOTH i and j printed a return, which
    is the only estimator that neither drops a row because one young asset was
    missing nor pretends a missing return was a zero one. Returns (cov, ok),
    where ``ok[i]`` is False when asset i has fewer than ``min_obs`` own
    observations in the window; cov rows/columns of such assets are zeroed so
    they can never contribute to a quadratic form.
    """
    M = (~np.isnan(block)).astype(float)
    X = np.nan_to_num(block)            # X is 0 exactly where M is 0
    N = M.T @ M                         # N[i,j] = overlapping observations
    A = X.T @ M                         # A[i,j] = Σ over the overlap of x_i
    P = X.T @ X                         # P[i,j] = Σ over the overlap of x_i x_j
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = (P - A * A.T / N) / (N - 1.0)
    enough = N >= min_obs
    cov = np.where(enough, np.nan_to_num(cov), 0.0)
    return cov, np.diag(enough).copy()


def portfolio_vol(weights: pd.DataFrame, returns: pd.DataFrame, window: int = 60,
                  min_obs: int | None = None) -> pd.Series:
    """Ex-ante annualised portfolio vol using the trailing covariance (causal).

    ``min_obs=None`` (the default) is the LEGACY estimator, unchanged: missing
    returns are read as zeros and ``np.cov`` runs on the whole block. That is
    correct only while every asset carrying weight has a complete window, which
    is true of the four-asset research universe over its published window and
    is what every published number on this desk was produced with. Do not
    repoint the default: it would silently make old and new results
    incomparable.

    ``min_obs=int`` is the estimator a wide universe needs. Covariances are
    PAIRWISE-COMPLETE (each pair estimated on the days both assets printed a
    return) and an asset with fewer than ``min_obs`` own observations in the
    window is EXCLUDED from that day's book — its weight is dropped from the
    quadratic form here, and ``vol_target`` drops it from the traded book too.
    Excluded, not sized on noise: a name with 20 usable days has no estimable
    covariance with anything, and zero-filling its gaps makes it look both
    nearly riskless and uncorrelated with everything — a free diversifier the
    book then levers itself up against.

    A pairwise-complete matrix need not be positive semi-definite, so w'Σw can
    come out negative on a badly overlapped universe. Nothing here inverts it —
    only the quadratic form is needed, so singularity itself is harmless — but
    a negative form would produce a zero vol and an infinitely levered book, so
    it falls back to the diagonal (variance-only) form, which cannot be
    negative and is the conservative reading of "we do not know the
    correlations".
    """
    cols = list(weights.columns)
    W = weights[cols].fillna(0.0).to_numpy(dtype=float)
    n = len(W)
    out = np.full(n, np.nan)
    if min_obs is None:
        R = returns[cols].fillna(0.0).to_numpy()
        for t in range(window, n):
            block = R[t - window + 1:t + 1]
            cov = np.cov(block, rowvar=False)
            if np.ndim(cov) == 0:
                cov = np.array([[cov]])
            w = W[t]
            out[t] = np.sqrt(max(float(w @ cov @ w), 0.0) * 365)
        return pd.Series(out, index=weights.index)

    if min_obs < 2:
        raise ValueError("min_obs must be >= 2 (a covariance needs two points)")
    R = returns[cols].to_numpy(dtype=float)     # NaN kept: it is the signal
    for t in range(window, n):
        block = R[t - window + 1:t + 1]
        cov, ok = _pairwise_cov(block, min_obs)
        w = np.where(ok, W[t], 0.0)
        q = float(w @ cov @ w)
        if not np.isfinite(q) or q < 0.0:
            q = float((w ** 2) @ np.diag(cov))   # see the docstring
        out[t] = np.sqrt(max(q, 0.0) * 365)
    return pd.Series(out, index=weights.index)


# Fallback maintenance rate for an asset with no PerpSpec. The venue's HIGHEST
# published rate (wld, 0.5919) rather than a middling guess: an unknown market
# gets the tightest liquidation-distance cap on the board, not a flattering one.
UNKNOWN_MAINT_RATE = max(s.maint_rate for s in SPECS.values())


def cap_weights(w: pd.DataFrame, max_gross: float = 1.5, max_asset: float = 0.75,
                min_liq_distance: float = 0.35) -> pd.DataFrame:
    """Per-asset cap (incl. the liquidation-distance cap from the venue's
    maintenance rate) then a proportional gross-leverage cap. BOTH always
    apply, in that order, and the gross rescale can only shrink weights, so it
    never re-breaches a per-asset cap.

    The per-asset cap is ``min(max_asset, max_weight_for_distance(d, m_a))``
    and ``m_a`` is EACH asset's OWN maintenance rate, which on this board spans
    a factor of nine: gold 0.0655, btc 0.1654, eth 0.2146, up to kshib 0.5015,
    vvv 0.5712 and wld 0.5919. At a 35% liquidation-distance floor that is a
    cap of 2.55x equity on gold, 2.19x on btc and 1.36x on wld — so the same
    dollar of book can be moved much less on a thin alt before the venue
    liquidates it, and the cap says so per name rather than per portfolio.
    (With ``max_asset`` at the profile values of 0.5–1.0 the flat per-asset cap
    is the binding one on every listed market; the distance cap bites first
    only when a caller raises ``max_asset`` above ~1.36 or the floor above
    ~0.9, and it bites on the thin alts before it bites on gold.)

    On a wide universe the binding constraint is normally ``max_gross``:
    sixteen equal-risk names each carry roughly 1/16 of the book, far under any
    per-asset cap, and the gross rescale is what sets the size.
    """
    w = w.copy()
    for a in w.columns:
        m = SPECS[a].maint_rate if a in SPECS else UNKNOWN_MAINT_RATE
        cap_long = min(max_asset, max_weight_for_distance(min_liq_distance, m, short=False))
        cap_short = min(max_asset, max_weight_for_distance(min_liq_distance, m, short=True))
        w[a] = w[a].clip(lower=-cap_short, upper=cap_long)
    gross = w.abs().sum(axis=1)
    scale = (max_gross / gross).where(gross > max_gross, 1.0).fillna(1.0)
    return w.mul(scale, axis=0).fillna(0.0)


# The 5% weight step was calibrated on a four-name book, where the average name
# carries a quarter of the risk. On a sixteen-name book the average name carries
# a sixteenth, and a 5% step rounds most of the alts to zero — the wide book
# would quietly collapse to whichever two names happen to be above 2.5%. ``step
# ="auto"`` keeps the same RELATIVE granularity by scaling with the universe:
# exactly 0.05 at four names (so nothing published changes), 0.0125 at sixteen.
STEP_AT_FOUR = 0.05


def resolve_step(step, n_assets: int) -> float:
    """``"auto"`` → STEP_AT_FOUR × 4 / n_assets; anything else passes through."""
    if isinstance(step, str):
        if step != "auto":
            raise ValueError(f"step must be a number or 'auto', got {step!r}")
        if n_assets <= 0:
            return 0.0
        return STEP_AT_FOUR * len(RESEARCH_UNIVERSE) / n_assets
    return step


def vol_target(signal: pd.DataFrame, panel: dict[str, pd.DataFrame], target_vol: float,
               vol_window: int = 60, cov_window: int = 120, max_gross: float = 1.5,
               max_asset: float = 0.75, min_liq_distance: float = 0.35,
               max_scale: float = 3.0, step: float | str = 0.05,
               cov_min_obs: int | None = None,
               available: pd.DataFrame | None = None) -> pd.DataFrame:
    """Signal in [-1, 1] per asset → notional weights.

    1. equal risk per asset: raw_i = signal_i / σ_i / N
    2. scale the book so a REFERENCE fully-long book (all signals = 1) has
       ex-ante vol ``target_vol`` under the trailing covariance. Scaling off
       the reference rather than the live signal means a weak or mixed signal
       yields a SMALLER book, never a levered-up one; a mixed long/short book
       then runs below target vol, which is the conservative side.
    3. round to ``step`` of equity so vol drift alone does not trade, then
       apply the venue/risk caps.
    Everything is causal (rolling windows only).

    Two optional arguments make this usable on a universe whose members list at
    different times. Both default to OFF, and with both off every line below is
    the arithmetic that produced the published four-asset numbers.

    ``cov_min_obs`` switches the trailing covariance to the pairwise-complete
    estimator described in ``portfolio_vol`` and drops any asset with fewer
    than that many usable returns in ``cov_window`` from the book that day
    (weight 0 — excluded, not sized on a covariance nobody can estimate).
    60 of 120 is a reasonable rule; the asset rejoins the book the day it has
    enough history, which is the same day a human would have let it in.

    ``available`` is the boolean tradability mask from ``tradable()``. It is
    applied to the signal, to the REFERENCE book and to the returns feeding the
    covariance — all three, because all three are wrong without it. ``align()``
    forward-fills, so across xrp's 905-day Coinbase delisting the aligned xrp
    column is a flat line: every return in it is an exact zero that never
    happened, and every covariance term involving xrp over that window is
    fabricated. The reference book is fully long BY CONSTRUCTION, signal or no
    signal, so without the mask it carries a leg in a market that cannot be
    entered, exited or marked, and the ex-ante vol the whole book is scaled by
    is computed partly from data that does not exist. A return is kept only
    when the asset was available on BOTH ends of it, which also throws away the
    one bar that would otherwise book a 905-day price move as a single day.

    ``available`` with ``cov_min_obs=None`` is a half measure: the mask reaches
    the signal and the reference book, but the legacy covariance still reads
    the masked returns as zeros. Use both, or use ``breadth_vol_target``.

    ``breadth_vol_target`` is the wide-universe entry point and turns both on.
    """
    closes = align(panel)
    rets = closes.pct_change()
    vol = asset_vol(panel, vol_window)
    n = len(signal.columns)
    ref = (1.0 / vol) / n
    if available is not None:
        av = (available.reindex(index=closes.index, columns=closes.columns)
                       .fillna(False).astype(bool))
        # a return needs a tradable bar at BOTH ends, so the day a delisted
        # market comes back does not book its whole blackout as one move
        rets = rets.where(av & av.shift(1).fillna(False))
        ref = ref.where(av)            # the reference book holds only live names
        signal = gate_signal(signal, mask=av)
    pv_ref = portfolio_vol(ref, rets, cov_window, min_obs=cov_min_obs)
    k = (target_vol / pv_ref).clip(upper=max_scale)
    raw = signal.div(vol).div(n).fillna(0.0)
    if cov_min_obs is not None:
        usable = usable_history(rets, cov_window, cov_min_obs)
        raw = raw.where(usable.reindex(index=raw.index, columns=raw.columns)
                              .fillna(False).astype(bool), 0.0)
    w = raw.mul(k, axis=0).fillna(0.0)
    step = resolve_step(step, n)
    if step and step > 0:
        w = (w / step).round() * step
    return cap_weights(w, max_gross, max_asset, min_liq_distance)


# Sizing defaults for a universe wider than the four researched assets. Kept as
# a dict so a family module can splat it and a reader can see exactly what the
# wide path changed: pairwise covariance with a 60-of-120 minimum, and a weight
# step that scales with the number of names.
BREADTH_SIZING: dict = {"cov_min_obs": 60, "step": "auto"}


def breadth_vol_target(signal: pd.DataFrame, panel: dict[str, pd.DataFrame],
                       target_vol: float, max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
                       **kw) -> pd.DataFrame:
    """``vol_target`` with the wide-universe defaults, availability included.

    The one call a breadth family should make: it derives the tradability mask
    from the panel, zeroes the signal where the asset was not quoting, and
    hands the same mask to the sizer so the reference book and the covariance
    see it too. Any keyword overrides ``BREADTH_SIZING``.
    """
    opts = dict(BREADTH_SIZING)
    opts.update(kw)
    av = opts.pop("available", None)
    if av is None:
        av = tradable(panel, max_stale_days, index=align(panel).index)
    return vol_target(gate_signal(signal, mask=av), panel, target_vol,
                      available=av, **opts)


def _tsmom_signal(closes: pd.DataFrame, lookbacks=(21, 63, 126, 252)) -> pd.DataFrame:
    sig = sum(np.sign(closes / closes.shift(lb) - 1.0) for lb in lookbacks) / len(lookbacks)
    return sig.fillna(0.0)


def _ma_signal(closes: pd.DataFrame, pairs=((10, 50), (20, 100), (50, 200)),
               band: float = 0.0) -> pd.DataFrame:
    out = 0
    for f, s in pairs:
        gap = closes.rolling(f).mean() / closes.rolling(s).mean() - 1.0
        out = out + np.sign(gap.where(gap.abs() > band, 0.0))
    return (out / len(pairs)).fillna(0.0)


def _breakout_signal(panel: dict[str, pd.DataFrame], idx: pd.DatetimeIndex,
                     entry: int = 55, exit_: int = 20) -> pd.DataFrame:
    """Turtle-style Donchian: enter on an ``entry``-day high/low breakout,
    exit when price crosses the ``exit_``-day channel the other way."""
    cols = {}
    for a, d in panel.items():
        hi = d["high"].rolling(entry).max().shift(1)
        lo = d["low"].rolling(entry).min().shift(1)
        xhi = d["high"].rolling(exit_).max().shift(1)
        xlo = d["low"].rolling(exit_).min().shift(1)
        c = d["close"].to_numpy()
        h, l, xh, xl = hi.to_numpy(), lo.to_numpy(), xhi.to_numpy(), xlo.to_numpy()
        pos = np.zeros(len(c))
        p = 0.0
        for i in range(len(c)):
            if not np.isnan(h[i]) and c[i] > h[i]:
                p = 1.0
            elif not np.isnan(l[i]) and c[i] < l[i]:
                p = -1.0
            elif p > 0 and not np.isnan(xl[i]) and c[i] < xl[i]:
                p = 0.0
            elif p < 0 and not np.isnan(xh[i]) and c[i] > xh[i]:
                p = 0.0
            pos[i] = p
        cols[a] = pd.Series(pos, index=d.index).reindex(idx).ffill().fillna(0.0)
    return pd.DataFrame(cols)


def _finish(sig: pd.DataFrame, panel, target_vol, long_only=False, **kw) -> pd.DataFrame:
    if long_only:
        sig = sig.clip(lower=0.0)
    return vol_target(sig, panel, target_vol, **kw)


# -------------------------------------------------------------- candidates
@register("tsmom")
def tsmom(panel, lookbacks=(21, 63, 126, 252), target_vol: float = 0.12,
          long_only: bool = False, **kw) -> pd.DataFrame:
    """Multi-horizon time-series momentum (average sign of 1/3/6/12-month
    returns), equal risk per asset, vol-targeted."""
    closes = align(panel)
    return _finish(_tsmom_signal(closes, lookbacks), panel, target_vol, long_only, **kw)


@register("ma_trend")
def ma_trend(panel, pairs=((10, 50), (20, 100), (50, 200)), band: float = 0.0,
             target_vol: float = 0.12, long_only: bool = False, **kw) -> pd.DataFrame:
    """Three moving-average crossovers averaged (Baz et al. 2015 style)."""
    closes = align(panel)
    return _finish(_ma_signal(closes, pairs, band), panel, target_vol, long_only, **kw)


@register("breakout")
def breakout(panel, entry: int = 55, exit_: int = 20, target_vol: float = 0.12,
             long_only: bool = False, **kw) -> pd.DataFrame:
    closes = align(panel)
    return _finish(_breakout_signal(panel, closes.index, entry, exit_), panel,
                   target_vol, long_only, **kw)


@register("trend_ensemble")
def trend_ensemble(panel, target_vol: float = 0.12, long_only: bool = False,
                   lookbacks=(21, 63, 126, 252), pairs=((10, 50), (20, 100), (50, 200)),
                   entry: int = 55, exit_: int = 20, **kw) -> pd.DataFrame:
    """Average of the three trend signals. The primary candidate: three weakly
    correlated trend definitions trade less often than any one of them."""
    closes = align(panel)
    sig = (_tsmom_signal(closes, lookbacks) + _ma_signal(closes, pairs)
           + _breakout_signal(panel, closes.index, entry, exit_)) / 3.0
    return _finish(sig, panel, target_vol, long_only, **kw)


@register("trend_long_only")
def trend_long_only(panel, target_vol: float = 0.12, **kw) -> pd.DataFrame:
    """Ensemble with shorts set to flat. Crypto shorts have paid negative
    drift historically; this asks whether the short side earns its fees."""
    return trend_ensemble(panel, target_vol=target_vol, long_only=True, **kw)


@register("trend_conservative")
def trend_conservative(panel, target_vol: float = 0.08, **kw) -> pd.DataFrame:
    """Ensemble at 8% vol, gross ≤ 1.0. The 'not too risky' rung."""
    kw.setdefault("max_gross", 1.0)
    kw.setdefault("max_asset", 0.5)
    return trend_ensemble(panel, target_vol=target_vol, **kw)


@register("carry_tilt")
def carry_tilt(panel, target_vol: float = 0.12, funding: dict | None = None,
               pay_limit_daily: float = 0.0006, **kw) -> pd.DataFrame:
    """Ensemble, but a position that would PAY funding above
    ``pay_limit_daily`` (≈22%/yr) is cut to zero for that day. On Kalshi the
    rate is ~zero, so this collapses to the ensemble — registered to show it.
    ``funding``: {asset: daily funding Series} (positive = longs pay)."""
    w = trend_ensemble(panel, target_vol=target_vol, **kw)
    if not funding:
        return w
    for a, f in funding.items():
        if a not in w.columns:
            continue
        f = f.reindex(w.index).fillna(0.0)
        pays = ((w[a] > 0) & (f > pay_limit_daily)) | ((w[a] < 0) & (f < -pay_limit_daily))
        w.loc[pays, a] = 0.0
    return w


@register("gold_silver_ratio")
def gold_silver_ratio(panel, window: int = 120, z_entry: float = 2.0, z_exit: float = 0.5,
                      target_vol: float = 0.08, **kw) -> pd.DataFrame:
    """Long gold / short silver when the ratio's z-score is very low, and the
    reverse when very high. A popular idea with weak evidence; registered so
    it is counted, expected to lose to the controls."""
    closes = align(panel)
    if "gold" not in closes or "silver" not in closes:
        return pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    lr = np.log(closes["gold"] / closes["silver"])
    z = (lr - lr.rolling(window).mean()) / lr.rolling(window).std()
    zz = z.to_numpy()
    pos = np.zeros(len(zz))
    p = 0.0
    for i in range(len(zz)):
        if np.isnan(zz[i]):
            pos[i] = p
            continue
        if p == 0.0:
            if zz[i] > z_entry:
                p = -1.0   # ratio rich: short gold, long silver
            elif zz[i] < -z_entry:
                p = 1.0
        elif abs(zz[i]) < z_exit:
            p = 0.0
        pos[i] = p
    sig = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    sig["gold"] = pos
    sig["silver"] = -pos
    return _finish(sig, panel, target_vol, **kw)


# ---------------------------------------------------------------- controls
@register("buy_hold", control=True)
def buy_hold(panel, weight: float = 1.0, **_) -> pd.DataFrame:
    """Equal-weight long, gross = ``weight``. Unlevered beta."""
    closes = align(panel)
    n = len(closes.columns)
    return pd.DataFrame(weight / n, index=closes.index, columns=closes.columns)


@register("vol_target_hold", control=True)
def vol_target_hold(panel, target_vol: float = 0.12, **kw) -> pd.DataFrame:
    """Long-only, equal risk, vol-targeted. THE benchmark: a trend strategy
    that cannot beat this out of sample is just levered beta with fees."""
    closes = align(panel)
    sig = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
    return vol_target(sig, panel, target_vol, **kw)


@register("flat", control=True)
def flat(panel, **_) -> pd.DataFrame:
    """Never trades. Earns only the collateral interest."""
    closes = align(panel)
    return pd.DataFrame(0.0, index=closes.index, columns=closes.columns)


@register("coin_flip", control=True)
def coin_flip(panel, target_vol: float = 0.12, hold: int = 21, seed: int = 7, **kw) -> pd.DataFrame:
    """Random ±1 signals held ``hold`` days, same sizing machinery. If the
    candidates do not clearly beat this, the sizing is the 'edge'."""
    closes = align(panel)
    rng = np.random.default_rng(seed)
    n_blocks = len(closes) // hold + 1
    sig = pd.DataFrame(
        np.repeat(rng.choice([-1.0, 1.0], size=(n_blocks, len(closes.columns))), hold, axis=0)[:len(closes)],
        index=closes.index, columns=closes.columns)
    return vol_target(sig, panel, target_vol, **kw)


def load_all() -> dict:
    """The core registry plus every module in quantfirm/perps/families/."""
    from . import families
    families.load_all()
    return REGISTRY


def family_trials() -> dict:
    from . import families
    return families.load_all()
