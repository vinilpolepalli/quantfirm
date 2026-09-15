"""reversal_seasonality — short-horizon reversal and calendar effects, long-only.

REGISTERED BEFORE THE FIRST RUN (2026-09-15). Four ideas, one configuration
each (4 of the allowed 6). Every constant below is the textbook default for
its idea, fixed a priori; nothing was tuned on the data.

Hypothesis
----------
Short-horizon return reversal and calendar seasonalities documented in
equities (weekly reversal, turn-of-month) and claimed for crypto (weekend
returns lower and more volatile) tilt a vol-targeted long book toward the
days that pay and away from the days that do not. Bollinger-band dips
inside a long-run uptrend are buyable over-reactions that revert to the
20-day mean within days.

Mechanism (why it could work, and why the desk expects it to FAIL)
----------------------------------------------------------------
Liquidity provision (Lehmann 1990; Jegadeesh 1990; Lo–MacKinlay 1990) and
payroll/pension flow timing (Ogden 1990) are the classic explanations; the
crypto weekend story is thinner books and retail-driven order flow. All
four effects are worth a few basis points per day, and the venue's tier-0
round trip is 24–29 bps of notional (evidence_review.md §5;
strategies.py docstring): a tilt that trades every week or twice a week
must recover its own fee before it adds anything. For BTC the a-priori
sign is even wrong: Liu–Tsyvinski (2021, RFS "Risks and Returns of
Cryptocurrency") find 1–4 WEEK time-series MOMENTUM, i.e. the trailing
week predicts the same direction, not reversal. The family is run to put
that failure on the record with the same tools as everything else.

External evidence
-----------------
* Weekly reversal, equities: Lehmann (1990, QJE "Fads, Martingales and
  Market Efficiency"); Jegadeesh (1990, JF); Lo & MacKinlay (1990, RFS).
  Crypto counter-evidence: Liu & Tsyvinski (2021, RFS), 1–4 week momentum.
* Weekend / day-of-week in crypto: Caporale & Plastun (2019, Research in
  International Business and Finance "The day of the week effect in the
  cryptocurrency market"); Baur, Cahill, Godfrey & Liu (2019, Finance
  Research Letters "Bitcoin time-of-day, day-of-week and month-of-year
  effects in returns and trading volume": lower weekend VOLUME, no robust
  return effect); Kinateder & Papavassiliou (2021, Finance Research Letters
  "Calendar effects in Bitcoin returns and volatility"). Mixed at best.
* Turn-of-month: Ariel (1987, JFE); Lakonishok & Smidt (1988, RFS);
  McConnell & Xu (2008, FAJ); Ogden (1990, JF). Equities only — importing
  it to gold/silver futures is the weakest link and is registered as such.
* Bollinger mean reversion: Bollinger (2001); Lento, Gradojevic & Wright
  (2007, Applied Financial Economics Letters: bands do not beat costs);
  Hudson & Urquhart (2021, Annals of Operations Research "Technical trading
  and cryptocurrencies": ~15,000 rules, predictive power marginal after
  costs).
* Internal: evidence_review.md §5 (fast mean reversion, grade D at this
  size) and the 24–29 bps round-trip arithmetic in strategies.py.

The registered grid (verbatim; 4 configurations)
-----------------------------------------------
TRIALS = {
  "rs_weekly_reversal": {"params": {"target_vol": 0.12, "lookback": 5, "tilt": 0.5}, "grid": {}},
  "rs_weekend_half":    {"params": {"target_vol": 0.12, "weekend_weight": 0.5}, "grid": {}},
  "rs_turn_of_month":   {"params": {"target_vol": 0.12, "off_weight": 0.5, "last_days": 2, "first_days": 3}, "grid": {}},
  "rs_bollinger_mr":    {"params": {"target_vol": 0.12, "bb_window": 20, "bb_k": 2.0, "trend_window": 200}, "grid": {}},
}

Cadence (BacktestConfig.rebalance_every is the only default touched, and
only because the hypotheses are about timing):
  * rs_weekly_reversal  --every 7  (the signal is a weekly tilt)
  * rs_weekend_half     --every 1  (must trade Fri→Sat and Sun→Mon; that is
                                    two fee-paying trades per crypto asset
                                    per week — the cost consequence is the
                                    point of the test)
  * rs_turn_of_month    --every 1  (a 5-trading-day window cannot be timed
                                    with a weekly band check)
  * rs_bollinger_mr     --every 1  (entries/exits are day-level events)
The benchmark vol_target_hold is also scored at --every 1 (same registry
key as its existing rows, so no new trial) to separate the cost of daily
checking from the calendar effect itself.

Selection rule (fixed before running): the configuration with the highest
oos_sharpe_concat in its own walk-forward gets the dev-window
``backtest --yearly --stress`` and the ``robust`` run. If every idea loses
to the benchmark, the best failure is still documented in full.

Causality
---------
Rolling windows on each asset's NATIVE bars (metals do not trade weekends),
reindexed to the union calendar and forward-filled; row t uses closes ≤ t.
Calendar facts (weekday, position within the month) are known in advance,
so the weight decided at close t may use the calendar of day t+1, which is
the session that weight will be exposed to (the backtester executes at
t+1's open). No aux series is used.

Sizing
------
All four feed a signal into ``vol_target`` at the benchmark's 12% target.
The weekly-reversal tilt deliberately puts the signal in {0.5, 1, 1.5}
(weight = base × (1 + tilt·signal), as registered): the book is 1.5× the
benchmark after a down week and 0.5× after an up week; venue caps
(gross ≤ 1.5, per-asset ≤ 0.75, liquidation distance ≥ 35%) still apply
inside ``vol_target``. Everything is long-only (signal clipped at 0).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import align
from ..specs import SPECS
from ..strategies import register, vol_target


def _asset_class(a: str) -> str:
    return SPECS[a].asset_class if a in SPECS else "crypto"


def _on_native_bars(panel: dict[str, pd.DataFrame], idx: pd.DatetimeIndex, fn) -> pd.DataFrame:
    """Apply ``fn(asset_frame) -> Series`` per asset on its own bars, then put
    the result on the union calendar (ffill over metals weekends/holidays)."""
    return pd.DataFrame({a: fn(d).reindex(idx).ffill() for a, d in panel.items()})


def _turn_of_month_window(dates: pd.DatetimeIndex, last_days: int, first_days: int) -> np.ndarray:
    """True for calendar days inside the contiguous window running from the
    ``last_days``-th-last weekday of a month through the ``first_days``-th
    weekday of the next month (weekends inside the window included, so the
    position is not flipped and flipped back over a weekend). Pure calendar
    arithmetic — no price data, no exchange-holiday file (a holiday shifts
    the window by one weekday; the union calendar carries a zero-return
    metals bar on that day, so the miss is harmless)."""
    d = dates.tz_convert(None) if dates.tz is not None else dates
    d = d.normalize()
    days = d.values.astype("datetime64[D]")
    per = d.to_period("M")
    month_start = per.to_timestamp().values.astype("datetime64[D]")
    next_month_start = (per + 1).to_timestamp().values.astype("datetime64[D]")
    wd_before = np.busday_count(month_start, days)                          # weekdays in [month start, d)
    wd_after = np.busday_count(days + np.timedelta64(1, "D"), next_month_start)  # weekdays in (d, month end]
    return (wd_after < last_days) | (wd_before < first_days)


def _bollinger_position(d: pd.DataFrame, window: int, k: float, trend_window: int) -> pd.Series:
    """0/1 state: enter when close < MA(window) − k·SD(window) while close is
    above its MA(trend_window); exit when close ≥ MA(window). Population SD
    (ddof=0), as in Bollinger's definition. Long-only."""
    c = d["close"]
    ma = c.rolling(window).mean()
    lower = (ma - k * c.rolling(window).std(ddof=0)).to_numpy()
    trend = c.rolling(trend_window).mean().to_numpy()
    ma_ = ma.to_numpy()
    cc = c.to_numpy()
    pos = np.zeros(len(cc))
    p = 0.0
    for i in range(len(cc)):
        if np.isnan(ma_[i]) or np.isnan(trend[i]):
            pos[i] = p
            continue
        if p == 0.0:
            if cc[i] < lower[i] and cc[i] > trend[i]:
                p = 1.0
        elif cc[i] >= ma_[i]:
            p = 0.0
        pos[i] = p
    return pd.Series(pos, index=d.index)


# ------------------------------------------------------------------ (a)
@register("rs_weekly_reversal")
def rs_weekly_reversal(panel, target_vol: float = 0.12, lookback: int = 5, tilt: float = 0.5,
                       **kw) -> pd.DataFrame:
    """Weekly reversal tilt on the vol-targeted long book.

    signal_t = −sign(close_t / close_{t−lookback} − 1) on native bars;
    weight = base × (1 + tilt·signal) ∈ {0.5, 1, 1.5} × base. Run with
    --every 7 (the weekly band check executes the tilt once a week)."""
    idx = align(panel).index
    rev = _on_native_bars(panel, idx, lambda d: -np.sign(d["close"].pct_change(lookback)))
    sig = (1.0 + tilt * rev.fillna(0.0)).clip(lower=0.0)
    return vol_target(sig, panel, target_vol, **kw)


# ------------------------------------------------------------------ (b)
@register("rs_weekend_half")
def rs_weekend_half(panel, target_vol: float = 0.12, weekend_weight: float = 0.5, **kw) -> pd.DataFrame:
    """Crypto at ``weekend_weight`` × base over the UTC weekend.

    The weight decided at close t is exposed to day t+1. Decisions made on
    Friday and Saturday (UTC) therefore cover Saturday's and Sunday's
    sessions (Fri close → Mon 00:00 UTC); Sunday's decision restores full
    weight for Monday. Metals never trade weekends (their union-calendar bar
    is a zero-return forward-fill) and are left at the base weight. Needs
    --every 1: two fee-paying trades per crypto asset per week."""
    closes = align(panel)
    idx = closes.index
    dow = np.asarray(idx.dayofweek)
    weekend_decision = (dow == 4) | (dow == 5)
    sig = pd.DataFrame(1.0, index=idx, columns=closes.columns)
    for a in closes.columns:
        if _asset_class(a) == "crypto":
            sig.loc[weekend_decision, a] = weekend_weight
    return vol_target(sig.clip(lower=0.0), panel, target_vol, **kw)


# ------------------------------------------------------------------ (c)
@register("rs_turn_of_month")
def rs_turn_of_month(panel, target_vol: float = 0.12, off_weight: float = 0.5,
                     last_days: int = 2, first_days: int = 3, **kw) -> pd.DataFrame:
    """Metals at full base weight only around the turn of the month.

    Full weight on the last ``last_days`` and first ``first_days`` weekdays
    of each month (a contiguous window, weekends inside it included),
    ``off_weight`` × base otherwise. The decision at close t uses the
    calendar position of day t+1 (the session it is exposed to). Crypto is
    left at the base weight. Needs --every 1."""
    closes = align(panel)
    idx = closes.index
    in_window_next = _turn_of_month_window(idx + pd.Timedelta(days=1), last_days, first_days)
    sig = pd.DataFrame(1.0, index=idx, columns=closes.columns)
    for a in closes.columns:
        if _asset_class(a) == "metals":
            sig[a] = np.where(in_window_next, 1.0, off_weight)
    return vol_target(sig.clip(lower=0.0), panel, target_vol, **kw)


# ------------------------------------------------------------------ (d)
@register("rs_bollinger_mr")
def rs_bollinger_mr(panel, target_vol: float = 0.12, bb_window: int = 20, bb_k: float = 2.0,
                    trend_window: int = 200, **kw) -> pd.DataFrame:
    """Long an asset only while a Bollinger dip inside a 200-day uptrend is
    reverting: enter at close < MA20 − 2σ with close > MA200, exit at close
    ≥ MA20. Flat (earning collateral interest) otherwise. Needs --every 1."""
    idx = align(panel).index
    pos = _on_native_bars(panel, idx, lambda d: _bollinger_position(d, bb_window, bb_k, trend_window))
    sig = pos.fillna(0.0).clip(lower=0.0, upper=1.0)
    return vol_target(sig, panel, target_vol, **kw)


TRIALS = {
    "rs_weekly_reversal": {"params": {"target_vol": 0.12, "lookback": 5, "tilt": 0.5}, "grid": {}},
    "rs_weekend_half": {"params": {"target_vol": 0.12, "weekend_weight": 0.5}, "grid": {}},
    "rs_turn_of_month": {"params": {"target_vol": 0.12, "off_weight": 0.5, "last_days": 2, "first_days": 3},
                         "grid": {}},
    "rs_bollinger_mr": {"params": {"target_vol": 0.12, "bb_window": 20, "bb_k": 2.0, "trend_window": 200},
                        "grid": {}},
}
