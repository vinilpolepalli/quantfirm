"""allocator_blend — meta-allocation over two REGISTERED books, no new signal.

Designer agent, 2026-09-15. Everything below the "Registered grid" heading
was frozen before the first backtest (research/kalshi_perps/CAMPAIGN.md).

Hypothesis
----------
The benchmark ``vol_target_hold`` (passive, equal-risk, vol-targeted long
book) and the incumbent ``trend_long_only`` (same sizing engine, exposure
gated by the trend ensemble) are imperfectly correlated — 0.749 on daily dev
excess returns 2018→2025-06 (research/kalshi_perps/robust_incumbent.log) —
and fail differently: the passive book carries the whole crypto bear (fixed
dev DD −21.2%, OOS −18.4%); the trend book pays whipsaw and misses the start
of rallies (dev CAGR 10.7% vs 15.5%) but draws down −9.4% / −12.5%. Two
books with near-equal Sharpe (0.94 / 0.91 fixed dev) and correlation well
below one should blend to a higher Sharpe than either with a drawdown
between them, so Sharpe-per-drawdown should sit above both. The drawdown
ladder in the live risk policy is the same idea in equity space: a
state-dependent allocator between the book and cash. Nothing here reads a
series the two books do not already read.

Mechanism
---------
W_t = (1 − w_t)·W_hold,t + w_t·W_trend,t, both books at the SAME target_vol,
so the blend is a convex combination of two capped frames and stays inside
every cap; it is never levered above either book. Because the trend book
runs ~8% realized vol against the passive book's ~13%, the blend's realized
vol is BELOW the benchmark's — the intended side of the trade-off (Sharpe is
scale-free, CAGR is not; the report says so).
  fixed        w_t = w. ("fixed", 0.3) = 70% passive / 30% trend; ("fixed", 0.5) = 50/50.
  gate         w_t = breadth_t = fraction of the four assets whose ensemble
               trend signal is > 0 at close t (the trend book's own signal,
               default lookbacks). Many gates open → trust the trend book;
               few open → the passive prior takes over. As written in the
               campaign brief.
  gate_inv     w_t = 1 − breadth_t: the sign-flipped reading (passive book
               when breadth is high, trend book when breadth collapses =
               breadth-confirmed trend). Registered because the sign of the
               breadth mapping is the one free choice in idea (b) and the a
               priori case for either is arguable; the walk-forward picks
               in-sample instead of me picking after the fact.
  riskparity   w_t = (1/σ_trend)/(1/σ_hold + 1/σ_trend), σ = trailing 60-day
               realized vol of each book's ex-post return proxy (yesterday's
               target weights × today's asset returns, gross of fees),
               annualized, floored at 5% — the floor asset_vol() applies to
               a single asset; a flat trend book has zero realized vol and
               would otherwise absorb the whole allocation.
  ladder       config 6: the benchmark under the live drawdown ladder,
               BacktestConfig(ladder_soft=0.08, ladder_kill=0.15). The CLI
               has no ladder flags, so ``run_ladder_trial`` runs it through
               quantfirm.perps.backtest and appends it to the trial registry.
               Caveat known in advance: the backtester's kill is per run(),
               so in the walk-forward it resets at each fold boundary (a
               "desk resets after review" model) while in the 2018→ fixed
               run a kill flattens for the rest of the window (the literal
               policy).

External evidence
-----------------
* Trend on the same assets as a diversifier of a long book: Moskowitz–Ooi–
  Pedersen (2012) "Time Series Momentum", J. Financial Economics 104 (TSMOM
  payoff convex in market moves); Hurst–Ooi–Pedersen (2017) "A Century of
  Evidence on Trend-Following Investing", J. Portfolio Management 44 (trend
  added to 60/40, 1880–2016, raises Sharpe and cuts drawdowns); Kaminski
  (2011) "In Search of Crisis Alpha", CME Group white paper.
* Inverse-vol allocation across sleeves: Asness–Frazzini–Pedersen (2012)
  "Leverage Aversion and Risk Parity", Financial Analysts Journal 68;
  Moreira–Muir (2017) "Volatility-Managed Portfolios", J. Finance 72 —
  scaling by trailing realized vol raises Sharpe where vol is persistent.
* Breadth / market-state conditioning of momentum: Cooper–Gutierrez–Hameed
  (2004) "Market States and Momentum", J. Finance 59. Thin for a four-asset
  universe: grade C by the desk's own evidence_review.md scale.
* Drawdown-controlled allocation: Grossman–Zhou (1993) "Optimal Investment
  Strategies for Controlling Drawdowns", Mathematical Finance 3 — lower DD
  paid for with return given up after de-risking. The ladder is the desk's
  live policy (quantfirm/perps/risk.py), so its footprint is due diligence,
  not an alpha claim.

Registered grid (6 configurations, frozen before the first run)
--------------------------------------------------------------
  1. blend=("fixed", 0.3)       70% vol_target_hold / 30% trend_long_only
  2. blend=("fixed", 0.5)       50 / 50
  3. blend=("gate",)            w_t = breadth_t
  4. blend=("gate_inv",)        w_t = 1 − breadth_t
  5. blend=("riskparity", 60)   inverse trailing 60-day realized book vol
  6. vol_target_hold(target_vol=0.12) under ladder_soft=0.08, ladder_kill=0.15
     (run_ladder_trial; not in TRIALS because the tournament's BacktestConfig
     cannot carry the ladder — through the plain config it would just be the
     benchmark counted twice)
All at target_vol=0.12; standard walk-forward (dev start 2016-06-01, 6
folds, warmup 550, 7-day embargo), taker tier 0, Kalshi funding, weekly
check, 3% band — BacktestConfig defaults untouched except the ladder in 6.
Selection rule fixed in advance: the config the walk-forward picks in the
LAST fold (the tournament's own convention) goes to `backtest --yearly
--stress` and `robust`. ("hold",) and ("trend",) are identity settings kept
for verification only (they reproduce the two books exactly); they are not
trials and are not run.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align
from ..strategies import (_breakout_signal, _ma_signal, _tsmom_signal, register,
                          trend_long_only, vol_target_hold)

DAYS = 365
BOOK_VOL_FLOOR = 0.05          # annualized; the same floor asset_vol() uses for one asset
TREND_DEFAULTS = {"lookbacks": (21, 63, 126, 252),
                  "pairs": ((10, 50), (20, 100), (50, 200)),
                  "entry": 55, "exit_": 20}


def ensemble_signal(panel, closes: pd.DataFrame | None = None, **trend_kw) -> pd.DataFrame:
    """The trend ensemble's own signal in [-1, 1] (same arithmetic as
    strategies.trend_ensemble, default definitions unless overridden)."""
    closes = align(panel) if closes is None else closes
    p = {**TREND_DEFAULTS, **trend_kw}
    return (_tsmom_signal(closes, p["lookbacks"]) + _ma_signal(closes, p["pairs"])
            + _breakout_signal(panel, closes.index, p["entry"], p["exit_"])) / 3.0


def breadth(panel, closes: pd.DataFrame | None = None, **trend_kw) -> pd.Series:
    """Fraction of assets whose ensemble trend signal is > 0 at each close.
    Row t uses closes ≤ t only (rolling windows and shifts inside the signals)."""
    return (ensemble_signal(panel, closes, **trend_kw) > 0).mean(axis=1)


def book_realized_vol(weights: pd.DataFrame, closes: pd.DataFrame, window: int = 60,
                      floor: float = BOOK_VOL_FLOOR) -> pd.Series:
    """Trailing realized vol of a book's ex-post return proxy: yesterday's
    target weights × today's asset returns on the union calendar (metals
    holidays are zero returns, as the venue would show), gross of fees,
    annualized and floored. Row t uses weights ≤ t−1 and closes ≤ t."""
    rets = closes[weights.columns].pct_change()
    r = (weights.shift(1) * rets).sum(axis=1)
    return (r.rolling(window).std() * np.sqrt(DAYS)).clip(lower=floor)


@register("allocator_blend")
def allocator_blend(panel, target_vol: float = 0.12, blend: tuple = ("fixed", 0.5), **kw) -> pd.DataFrame:
    """Convex combination of vol_target_hold and trend_long_only target weights.

    ``blend``: ("fixed", w_trend) | ("gate",) | ("gate_inv",) | ("riskparity", window)
    | ("hold",) | ("trend",). Extra keyword arguments go to both books' sizing
    (vol_window, cov_window, max_gross, ...); the trend definitions
    (lookbacks, pairs, entry, exit_) go to the trend book and to the breadth
    gate so both read the same signal.
    """
    if isinstance(blend, str):
        blend = (blend,)
    mode = blend[0]
    trend_kw = {k: kw.pop(k) for k in list(TREND_DEFAULTS) if k in kw}
    closes = align(panel)
    w_hold = vol_target_hold(panel, target_vol=target_vol, **kw)
    w_trend = trend_long_only(panel, target_vol=target_vol, **trend_kw, **kw)
    if mode == "fixed":
        wt = float(min(max(float(blend[1]), 0.0), 1.0))
    elif mode == "hold":
        wt = 0.0
    elif mode == "trend":
        wt = 1.0
    elif mode in ("gate", "gate_inv"):
        b = breadth(panel, closes, **trend_kw)
        wt = b if mode == "gate" else 1.0 - b
    elif mode == "riskparity":
        window = int(blend[1]) if len(blend) > 1 else 60
        inv_h = 1.0 / book_realized_vol(w_hold, closes, window)
        inv_t = 1.0 / book_realized_vol(w_trend, closes, window)
        wt = inv_t / (inv_h + inv_t)
    else:
        raise ValueError(f"unknown blend {blend!r}")
    if isinstance(wt, pd.Series):
        wt = wt.reindex(w_hold.index).fillna(0.5)     # before any window is full: 50/50
        return w_hold.mul(1.0 - wt, axis=0).add(w_trend.mul(wt, axis=0)).fillna(0.0)
    return ((1.0 - wt) * w_hold + wt * w_trend).fillna(0.0)


# ------------------------------------------------------------------ registration
TRIALS = {
    "allocator_blend": {
        "params": {"target_vol": 0.12},
        "grid": {"blend": [("fixed", 0.3), ("fixed", 0.5), ("gate",), ("gate_inv",), ("riskparity", 60)]},
    },
}

# Config 6 — the benchmark under the live drawdown ladder (risk.py balanced
# profile: dd_soft 0.08, dd_kill 0.15). Evaluated by run_ladder_trial because
# the CLI does not expose BacktestConfig.ladder_*.
LADDER_TRIAL = {"strategy": "vol_target_hold", "params": {"target_vol": 0.12},
                "cfg": {"ladder_soft": 0.08, "ladder_kill": 0.15}}
LADDER_NOTE = ("family=allocator_blend config 6: benchmark under live ladder (halve at -8%, flatten at -15%); "
               "snippet via families.allocator_blend.run_ladder_trial, CLI has no ladder flags")


def run_ladder_trial(panel=None, universe=("btc", "eth", "gold", "silver"), record_rows: bool = True) -> dict:
    """DEV only. Same folds as the CLI walk-forward (fixed params, hence
    labelled fixed_params like the benchmark's own tournament row), plus the
    2018→ fixed run with by-year returns, realized vol and the six stress
    cells. Every run is appended to the trial registry under a key that
    carries the ladder settings (params prefixed ``cfg.``)."""
    from .. import data as D
    from ..backtest import BacktestConfig, public, run_strategy, stress, walk_forward
    from ..registry import record
    from ..strategies import REGISTRY
    panel = panel or D.load_panel(tuple(universe))
    fn = REGISTRY[LADDER_TRIAL["strategy"]]
    params = dict(LADDER_TRIAL["params"])
    cfg = BacktestConfig(**LADDER_TRIAL["cfg"])
    reg_params = {**params, **{f"cfg.{k}": v for k, v in LADDER_TRIAL["cfg"].items()}}
    wf = walk_forward(panel, fn, params, cfg, grid=None, n_folds=6, warmup_days=550, dev_start="2016-06-01")
    fixed = run_strategy(panel, fn, params, cfg, start="2018-01-01", end=D.HOLDOUT_START)
    out = public(fixed)
    ret = fixed["_series"]["returns"]
    out["by_year"] = {str(y): round(float((1 + g).prod() - 1), 4) for y, g in ret.groupby(ret.index.year)}
    out["realized_vol"] = round(float(ret.std(ddof=1) * np.sqrt(DAYS)), 4)
    out["stress"] = stress(panel, fn, params, cfg, "2018-01-01", D.HOLDOUT_START)
    if record_rows:
        for f in wf["folds"]:
            record(LADDER_TRIAL["strategy"], reg_params, "dev",
                   {"net_sharpe": f["oos_sharpe"], "max_drawdown": f["max_drawdown"],
                    "ann_turnover": f["turnover"], "start": f["start"], "end": f["end"]},
                   source="snippet:walkforward", note=LADDER_NOTE)
        record(LADDER_TRIAL["strategy"], reg_params, "dev", out, source="snippet:backtest", note=LADDER_NOTE)
    return {"walk_forward": {k: v for k, v in wf.items() if not k.startswith("_")}, "fixed_2018": out}
