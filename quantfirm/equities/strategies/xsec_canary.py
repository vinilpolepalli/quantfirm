"""XSEC-CANARY (IDEA_BACKLOG 1.1) — incumbent chassis + canary/momentum defense.

Takes `xsec_refined` exactly as it stands (chassis copied verbatim, incumbent
module untouched) and replaces ONLY the defensive-rotation module, in two
registered variants per the Tier-1.1 designer brief:

  Variant A (canary=True): TIP canary gate. 13612W = (r1+r3+r6+r12)/4
    computed on TIP from daily closes resampled monthly (Keller HAA,
    SSRN 4346906). When TIP 13612W <= 0 at a rebalance date, the whole book
    moves to the defensive destination; when > 0 (or before the canary has
    12 months of history), the incumbent runs unchanged.
  Variant B (def_select="13612w"): momentum-selected defensive destination
    (Keller BAA, SSRN 4166845). When the incumbent's existing risk-off
    condition frees capital, allocate it to the single best of
    {TIP, BIL, IEF} by 13612W momentum (positive-only, else cash) instead of
    the incumbent's best-63d-return pick from {IEF, TLT, GLD, SHY}.
  A+B: both at once.

Everything else — vol-scaled 189-21 momentum ranking, top-6, rank-band 3x,
inv-vol weights, per-name absolute-momentum filter, every=21 cadence — is
byte-identical logic to the incumbent. With canary=False and
def_select="ret" this module IS the incumbent (parity trial).

Causality: the monthly 13612W series is resampled to calendar month-ends
('ME' labels, each using only closes <= its label) and forward-filled onto
the daily index, so the value read at rebalance date t uses closes <= t
only. Chassis causality is inherited from the incumbent (signals at row t
look strictly backward; backtester trades row t at close t+1).

NOTE: TIP and BIL were added to data/equities/ for this brief; they are
excluded from the stock-ranking universe here (the incumbent's ETFS set
predates them).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import register

# 25 bias-free ETFs from universe.json + the two fetched for this brief
# (TIP, BIL) — all excluded from the stock ranking universe.
ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP",
    "XLY", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF", "SHY", "GLD", "DBC",
    "EFA", "EEM", "VNQ", "HYG", "LQD", "TIP", "BIL",
}

DEFAULT_DEF_MENU = ("IEF", "TLT", "GLD", "SHY")
DEF_MENU_B = ("TIP", "BIL", "IEF")


def _w13612_daily(closes: pd.DataFrame, symbols: list, idx) -> pd.DataFrame:
    """13612W momentum from daily closes resampled monthly, ffilled to the
    daily index. Causal: month-end labels only use closes <= label, and
    ffill at date t only picks labels <= t."""
    monthly = closes[symbols].resample("ME").last()
    w = (monthly.pct_change(1) + monthly.pct_change(3)
         + monthly.pct_change(6) + monthly.pct_change(12)) / 4.0
    return w.reindex(idx, method="ffill")


@register("xsec_canary")
def xsec_canary(closes: pd.DataFrame,
                formation: int = 189,
                skip: int = 21,
                vol_days: int = 63,
                top_n: int = 6,
                band_mult: float = 3.0,
                weighting: str = "inv_vol",
                every: int = 21,
                vol_scale: bool = True,
                abs_filter: bool = True,
                gate_sma: int = 200,
                gate_mode: str = "none",
                vol_window: int = 20,
                vol_cap: float = 0.25,
                def_menu: tuple = DEFAULT_DEF_MENU,
                def_lookback: int = 63,
                def_k: int = 1,
                canary: bool = False,
                canary_symbol: str = "TIP",
                def_select: str = "ret",
                def_menu_b: tuple = DEF_MENU_B) -> pd.DataFrame:
    """Incumbent chassis with optional TIP canary (Variant A) and
    13612W-selected defensive destination (Variant B).

    canary: when True, TIP 13612W <= 0 zeroes the offense sleeve for that
      rebalance (whole book to defensive destination). NaN canary (first 12
      months) = gate off, incumbent unchanged.
    def_select: "ret" = incumbent (best def_lookback return from def_menu);
      "13612w" = best of def_menu_b by 13612W, positive-only, else cash.
    """
    stocks = [c for c in closes.columns if c not in ETFS]
    mom = closes[stocks].pct_change(formation - skip).shift(skip)
    rets = closes[stocks].pct_change(fill_method=None)
    vol = rets.rolling(vol_days).std()
    if vol_scale:
        score = mom / vol.replace(0.0, np.nan)
    else:
        score = mom

    # --- regime gate (risk fraction per date) — incumbent, unchanged ---
    idx = closes.index
    if gate_mode != "none" and gate_sma and "SPY" in closes.columns:
        spy = closes["SPY"]
        sma = spy.rolling(gate_sma).mean()
        trend_on = spy > sma
        if gate_mode == "half":
            rv = spy.pct_change().rolling(vol_window).std() * np.sqrt(252)
            vol_ok = rv <= vol_cap
            risk_frac = pd.Series(0.0, index=idx)
            risk_frac[trend_on & vol_ok] = 1.0
            risk_frac[trend_on & ~vol_ok] = 0.5
        else:  # binary
            risk_frac = trend_on.astype(float)
        risk_frac[sma.isna()] = 1.0  # no gate before SMA exists
    else:
        risk_frac = pd.Series(1.0, index=idx)

    # --- Variant A: TIP 13612W canary gate ---
    if canary and canary_symbol in closes.columns:
        cw = _w13612_daily(closes, [canary_symbol], idx)[canary_symbol]
        canary_off = cw.notna() & (cw <= 0.0)   # NaN warmup -> gate off
        risk_frac = risk_frac.where(~canary_off, 0.0)

    # --- defensive-destination signals ---
    dmenu = [s for s in def_menu if s in closes.columns]
    dmom = closes[dmenu].pct_change(def_lookback) if dmenu else None
    if def_select == "13612w":
        bmenu = [s for s in def_menu_b if s in closes.columns]
        dmom = _w13612_daily(closes, bmenu, idx) if bmenu else None

    dates = idx[::every]
    w = pd.DataFrame(0.0, index=dates, columns=closes.columns)
    band = max(top_n, int(round(band_mult * top_n)))
    holdings: list = []

    for d in dates:
        s_row = score.loc[d].dropna()
        m_row = mom.loc[d]
        if len(s_row) < top_n:      # warmup — stay in cash
            holdings = []
            continue
        ranked = s_row.sort_values(ascending=False)
        band_set = set(ranked.index[:band])

        def _ok(sym):
            if not abs_filter:
                return True
            v = m_row.get(sym, np.nan)
            return pd.notna(v) and v > 0

        # keep incumbents still inside the band (and passing abs momentum)
        kept = [s for s in holdings
                if s in band_set and s in s_row.index and _ok(s)]
        # fill vacant slots with the best-ranked new names
        for s in ranked.index:
            if len(kept) >= top_n:
                break
            if s not in kept and _ok(s):
                kept.append(s)
        holdings = kept

        rf = float(risk_frac.at[d])
        offense_total = rf * len(kept) / top_n
        def_total = 1.0 - offense_total

        if kept and offense_total > 0:
            if weighting == "inv_vol":
                iv = 1.0 / vol.loc[d].reindex(kept)
                iv = iv.replace([np.inf, -np.inf], np.nan).dropna()
                if len(iv):
                    ww = iv / iv.sum() * offense_total
                    for s, x in ww.items():
                        w.at[d, s] = float(x)
                else:
                    for s in kept:
                        w.at[d, s] = offense_total / len(kept)
            else:                    # equal weight
                for s in kept:
                    w.at[d, s] = offense_total / len(kept)

        # --- defensive sleeve: best safe ETF(s) by the selected signal,
        #     positive-momentum-only, else cash ---
        if def_total > 1e-9 and dmom is not None:
            dv = dmom.loc[d].dropna().sort_values(ascending=False)
            dpicks = [s for s in dv.index[:def_k] if dv[s] > 0]
            for s in dpicks:
                w.at[d, s] = w.at[d, s] + def_total / def_k
            # any unfilled defensive share stays in cash
    return w
