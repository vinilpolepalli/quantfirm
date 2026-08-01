"""CAL-TOMOPEX — Turn-of-Month + OpEx-week calendar composite (ETF track).

IDEA_BACKLOG 1.3. Two documented long-only calendar effects with
non-overlapping windows, traded on SPY only (bias-free ETF track):

  Leg 1 (TOM):  buy SPY at the close of month-day T-`tom_entry` (trading days
                before month end) and exit at the close of T+`tom_exit`
                (trading days into the new month). Default T-4 .. T+3
                (SSRN 917884). Window edges are the declared sweep surface.
  Leg 2 (OpEx): buy SPY at the prior-Friday close before the 3rd Friday and
                exit at the OpEx-Friday close (SSRN 1571786).
  Otherwise: cash (optionally parked in a cash-proxy ETF, e.g. BIL — note the
  panel is price-only, so BIL carries ~no yield here and mostly adds tickets).

Execution semantics under the desk backtester ("weight row t is traded at
t+1's close", so row t earns the return of bar t+2): the weight row for a
window opens two trading days before the first captured return bar. With
defaults this buys at the close of T-4 and captures returns T-3..T+3, and
buys at the prior-Friday close capturing Mon..Fri of expiry week — exactly
the brief's windows. The trading-day calendar is deterministic and known
ex-ante, so the mapping is causal; the tail of the panel is padded with
business days only to classify the final (incomplete) month.

The two windows never overlap by construction (TOM hugs the month turn,
OpEx week sits mid-month); this is asserted at runtime.

Declared variants (all registered trials):
  mode: "tom" | "opex" | "composite"
  gate_sma: optional trend gate — a window is only taken if SPY > its
      `gate_sma`-day SMA at the window's decision close (0 = no gate).
  cash_symbol: park idle capital in this ETF ("" = true cash).
  stock_sub: optional 4th registered trial from the brief — in TOM windows
      substitute the incumbent's top-`top_n` vol-adjusted 6-1 momentum stocks
      (scoring copied from xsec_refined; that module is never touched) for
      SPY. This variant leaves the bias-free ETF track (survivorship-biased
      stock universe) and is flagged as such.

Pre-declared kills (from the brief, checked by the designer, reported
honestly): OpEx alone dies if it shows no post-2013 edge on dev folds; the
composite dies if deflated Sharpe on the low observation count cannot
distinguish it from SPY buy-and-hold.

Account fit: one SPY ticket per window (~24 round trips/yr), 1 position
(<=15), fractional-friendly ($250 in one ETF).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

# Copied from xsec_refined (the incumbent is never edited): the 25 bias-free
# ETFs excluded from the stock ranking universe for the stock_sub variant.
ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP",
    "XLY", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF", "SHY", "GLD", "DBC",
    "EFA", "EEM", "VNQ", "HYG", "LQD",
}


def _third_friday(year: int, month: int) -> pd.Timestamp:
    first = pd.Timestamp(year, month, 1)
    return first + pd.Timedelta(days=(4 - first.weekday()) % 7 + 14)


def _window_masks(ext: pd.DatetimeIndex, tom_entry: int, tom_exit: int):
    """Boolean arrays over `ext` marking bars whose RETURN each leg captures.

    TOM captures returns of the last (tom_entry - 1) trading days of each
    month and the first tom_exit of the next (buy close T-entry, sell close
    T+exit). OpEx captures returns of trading days in (prev-Friday, 3rd
    Friday] — expiry moves to Thursday automatically when Friday is a
    holiday, since only actual trading days <= the calendar 3rd Friday exist.
    """
    tom = np.zeros(len(ext), dtype=bool)
    opex = np.zeros(len(ext), dtype=bool)
    pos = pd.Series(np.arange(len(ext)), index=ext)
    for (y, m), grp in pos.groupby([ext.year, ext.month]):
        p = grp.to_numpy()
        n_m = len(p)
        offs_start = np.arange(1, n_m + 1)          # T+1 .. T+n
        offs_end = np.arange(-n_m, 0)               # T-n .. T-1
        tom[p[(offs_end >= -(tom_entry - 1)) | (offs_start <= tom_exit)]] = True
        tf = _third_friday(int(y), int(m))
        pf = tf - pd.Timedelta(days=7)
        in_week = np.asarray((grp.index > pf) & (grp.index <= tf))
        opex[p[in_week]] = True
    return tom, opex


@register("cal_tomopex")
def cal_tomopex(closes: pd.DataFrame,
                mode: str = "composite",
                tom_entry: int = 4,
                tom_exit: int = 3,
                gate_sma: int = 0,
                cash_symbol: str = "",
                stock_sub: bool = False,
                formation: int = 189,
                skip: int = 21,
                vol_days: int = 63,
                top_n: int = 6) -> pd.DataFrame:
    idx = closes.index
    n = len(idx)
    # Pad the tail with business days so the final (incomplete) month can be
    # classified; the pad is only ever used for calendar arithmetic.
    pad = pd.bdate_range(idx[-1] + pd.Timedelta(days=1), periods=40)
    ext = idx.append(pad)

    tom, opex = _window_masks(ext, tom_entry, tom_exit)
    # Brief requirement: the two windows never overlap by construction.
    # (Checked over every position that can influence a weight row, i.e.
    # [0, n+2); months deep in the synthetic pad are partial and would
    # misclassify, but they can never reach a weight row.)
    assert not (tom[:n + 2] & opex[:n + 2]).any(), "TOM/OpEx windows overlap"

    if mode == "tom":
        captured = tom
    elif mode == "opex":
        captured = opex
    else:
        captured = tom | opex

    # Weight row i earns the return of bar i+2 (decide close i, trade close
    # i+1) => row i is active iff ext[i+2] is a captured-return bar.
    active = captured[2:n + 2]

    # Optional trend gate, evaluated once per window at its decision close.
    if gate_sma and "SPY" in closes.columns:
        spy = closes["SPY"]
        sma = spy.rolling(gate_sma).mean()
        gate = ((spy > sma) | sma.isna()).to_numpy()   # no gate before SMA
    else:
        gate = None

    # Momentum scoring for the stock-substitution variant (copied in spirit
    # from xsec_refined; causal: pct_change/rolling/shift look backward only).
    score = vol = mom = None
    if stock_sub:
        stocks = [c for c in closes.columns if c not in ETFS]
        mom = closes[stocks].pct_change(formation - skip).shift(skip)
        rets = closes[stocks].pct_change(fill_method=None)
        vol = rets.rolling(vol_days).std()
        score = mom / vol.replace(0.0, np.nan)

    w = pd.DataFrame(0.0, index=idx, columns=closes.columns)
    a = active.astype(int)
    starts = np.where(np.diff(np.concatenate(([0], a))) == 1)[0]
    ends = np.where(np.diff(np.concatenate((a, [0]))) == -1)[0]  # inclusive

    spy_j = w.columns.get_loc("SPY")
    for st, en in zip(starts, ends):
        if gate is not None and not gate[st]:
            continue                                  # window skipped -> cash
        is_tom_window = bool(tom[min(st + 2, len(ext) - 1)])
        placed = False
        if stock_sub and is_tom_window:
            d = idx[st]
            s_row = score.loc[d].dropna()
            m_row = mom.loc[d]
            picks = [s for s in s_row.sort_values(ascending=False).index
                     if pd.notna(m_row.get(s)) and m_row[s] > 0][:top_n]
            if len(picks) == top_n:
                iv = (1.0 / vol.loc[d].reindex(picks)).replace(
                    [np.inf, -np.inf], np.nan).dropna()
                if len(iv):
                    ww = iv / iv.sum()
                    for s, x in ww.items():
                        w.iloc[st:en + 1, w.columns.get_loc(s)] = float(x)
                else:
                    for s in picks:
                        w.iloc[st:en + 1, w.columns.get_loc(s)] = 1.0 / top_n
                placed = True
        if not placed:
            w.iloc[st:en + 1, spy_j] = 1.0

    if cash_symbol and cash_symbol in closes.columns:
        cj = w.columns.get_loc(cash_symbol)
        idle = (w.sum(axis=1).to_numpy() == 0.0) & \
            closes[cash_symbol].notna().to_numpy()
        w.iloc[idle, cj] = 1.0

    return w
