"""Calibration measurements from harvested 15M history.

Answers two pre-registered questions before any capital decision:
  1. Market calibration / favorite-longshot bias on METALS specifically:
     bucket the contract mid at fixed time-to-close, compare to realized
     win rate. (Whelan's maker/taker numbers are cross-category.)
  2. Model calibration: is N(ln(S/K)/(sigma*sqrt(tau))) well-calibrated on
     the same points, using the same causal vol estimator as the backtest?

Outputs a plain dict (the CLI prints/saves it as JSON).
"""

from __future__ import annotations

import math
from collections import defaultdict

from .backtest import METALS, Backtest
from .fair import VolEstimator, fair_yes


def calibration(bt: Backtest, taus=(600, 300, 120), n_price_bins=10,
                params=None) -> dict:
    from .strategy import Params
    p = params or Params()
    out = {}
    # causal vol per metal, driven by underlying bars (same as backtest)
    vol = {m: VolEstimator(halflife_min=p.vol_halflife_min, diurnal=p.diurnal)
           for m in bt.bars}
    bar_events = []
    for metal, bars in bt.bars.items():
        prev = None
        for ts in sorted(bars):
            if prev is not None and 0 < ts - prev[0] <= 120:
                bar_events.append((ts, metal, math.log(bars[ts] / prev[1])))
            prev = (ts, bars[ts])
    bar_events.sort()

    # decision points: (ts, metal, mid, model_fair, won)
    points = []
    for series, mkts in bt.markets.items():
        metal = METALS[series]
        cnds_all = bt.candles.get(series, {})
        bars = bt.bars.get(metal, {})
        for m in mkts:
            cnds = cnds_all.get(m["ticker"])
            if not cnds:
                continue
            f_open = bars.get(m["open_ts"])
            won = m["result"] == "yes"
            for tau in taus:
                T = m["close_ts"] - tau
                c = cnds.get(T)
                if not c or c["bid_close"] is None or c["ask_close"] is None:
                    continue
                bid, ask = c["bid_close"], c["ask_close"]
                if bid <= 0 and ask >= 1:
                    continue
                mid = (bid + ask) / 2
                fair = None
                f_now = bars.get(T)
                if f_now is not None and f_open:
                    s_now = f_now * (m["strike"] / f_open)
                    fair = ("pending", T, metal, s_now, m["strike"], tau)
                points.append((T, metal, tau, mid, fair, won))

    # interleave causally to compute model fair with the right vol state
    points.sort(key=lambda x: x[0])
    bi = 0
    rows = []
    for T, metal, tau, mid, fair, won in points:
        while bi < len(bar_events) and bar_events[bi][0] <= T:
            _, bm, lr = bar_events[bi]
            vol[bm].update(bar_events[bi][0], lr)
            bi += 1
        model = None
        if fair is not None:
            _, _, _, s_now, k, tau_ = fair
            model = fair_yes(s_now, k, vol[metal].sigma_1m(T), tau_ / 60.0)
        rows.append((metal, tau, mid, model, won))

    def curve(sel_rows, probfn):
        buckets = defaultdict(lambda: [0, 0, 0.0])
        for r in sel_rows:
            q = probfn(r)
            if q is None:
                continue
            b = min(int(q * n_price_bins), n_price_bins - 1)
            buckets[b][0] += 1
            buckets[b][1] += 1 if r[4] else 0
            buckets[b][2] += q
        return {f"{b/n_price_bins:.1f}-{(b+1)/n_price_bins:.1f}":
                {"n": v[0], "mean_prob": round(v[2] / v[0], 3),
                 "win_rate": round(v[1] / v[0], 3)}
                for b, v in sorted(buckets.items()) if v[0] >= 30}

    def brier(sel_rows, probfn):
        vals = [(probfn(r), 1.0 if r[4] else 0.0) for r in sel_rows
                if probfn(r) is not None]
        if not vals:
            return None
        return round(sum((q - y) ** 2 for q, y in vals) / len(vals), 4)

    for tau in taus:
        sel = [r for r in rows if r[1] == tau]
        out[f"tau_{tau}s"] = {
            "n": len(sel),
            "market_curve": curve(sel, lambda r: r[2]),
            "market_brier": brier(sel, lambda r: r[2]),
            "model_curve": curve(sel, lambda r: r[3]),
            "model_brier": brier(sel, lambda r: r[3]),
        }
    return out
