"""Train-split microstructure diagnostics for 15-minute commodities.

These measurements REGISTER which strategies are even plausible. They are
computed on the train window only; looking at test here is a protocol break.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from .backtest import METALS, Backtest
from .fair import VolEstimator, fair_yes
from .strategy import Params


def _bucket(p: float, edges=(0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90)):
    for e in edges:
        if p < e:
            return f"<{e:.2f}"
    return ">=0.90"


def run_diagnostics(bt: Backtest, start_ts: int | None, end_ts: int | None,
                    params: Params | None = None) -> dict:
    p = params or Params()
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

    flb = defaultdict(lambda: [0, 0])          # bucket -> [n, wins]
    late = defaultdict(lambda: [0, 0])         # |z| bucket -> [n, favorite_wins]
    open_move = defaultdict(lambda: [0, 0.0, 0])  # sign -> [n, sum rest ret, n_up]
    hour = defaultdict(lambda: [0, 0])         # utc hour -> [n, yes]
    agree = {"same": 0, "diff": 0, "n": 0}

    # gold/silver same-window results
    by_window = defaultdict(dict)
    bi = 0

    points = []
    for series, mkts in bt.markets.items():
        metal = METALS[series]
        cnds_all = bt.candles.get(series, {})
        bars = bt.bars.get(metal, {})
        for m in mkts:
            if start_ts and m["close_ts"] < start_ts:
                continue
            if end_ts and m["close_ts"] >= end_ts:
                continue
            won = m["result"] == "yes"
            hour[datetime.fromtimestamp(m["close_ts"], tz=timezone.utc).hour][0] += 1
            hour[datetime.fromtimestamp(m["close_ts"], tz=timezone.utc).hour][1] += int(won)
            by_window[m["open_ts"]][metal] = won
            f_open = bars.get(m["open_ts"])
            f_3 = bars.get(m["open_ts"] + 180)
            f_end = bars.get(m["close_ts"])
            if f_open and f_3 and f_end and f_open > 0 and f_3 > 0:
                first = f_3 / f_open - 1.0
                rest = f_end / f_3 - 1.0
                sign = "up" if first >= 0.0015 else ("down" if first <= -0.0015 else "flat")
                open_move[sign][0] += 1
                open_move[sign][1] += rest
                open_move[sign][2] += int(rest > 0)
            cnds = cnds_all.get(m["ticker"]) or {}
            for tau in (600, 300, 120):
                T = m["close_ts"] - tau
                c = cnds.get(T)
                if not c or c["bid_close"] is None or c["ask_close"] is None:
                    continue
                mid = (c["bid_close"] + c["ask_close"]) / 2
                points.append((T, metal, tau, mid, won, m, f_open))

    points.sort(key=lambda x: x[0])
    for T, metal, tau, mid, won, m, f_open in points:
        while bi < len(bar_events) and bar_events[bi][0] <= T:
            _, bm, lr = bar_events[bi]
            vol[bm].update(bar_events[bi][0], lr)
            bi += 1
        flb[(tau, _bucket(mid))][0] += 1
        flb[(tau, _bucket(mid))][1] += int(won)
        bars = bt.bars.get(metal, {})
        f_now = bars.get(T)
        if f_now and f_open and f_open > 0:
            s = f_now * (m["strike"] / f_open)
            sig = vol[metal].sigma_1m(T)
            fair = fair_yes(s, m["strike"], sig, tau / 60.0)
            z = abs(fair - 0.5) * 2  # 0..1 certainty
            zb = "z>=0.8" if z >= 0.8 else ("z>=0.5" if z >= 0.5 else "z<0.5")
            fav_yes = fair >= 0.5
            late[(tau, zb)][0] += 1
            late[(tau, zb)][1] += int(won == fav_yes)

    for ts, res in by_window.items():
        if "gold" in res and "silver" in res:
            agree["n"] += 1
            if res["gold"] == res["silver"]:
                agree["same"] += 1
            else:
                agree["diff"] += 1

    def _rate(pair):
        n, w = pair
        return {"n": n, "rate": round(w / n, 3) if n else None}

    flb_out = {}
    for (tau, b), v in sorted(flb.items()):
        flb_out.setdefault(f"tau_{tau}s", {})[b] = _rate(v)
    late_out = {}
    for (tau, b), v in sorted(late.items()):
        late_out.setdefault(f"tau_{tau}s", {})[b] = _rate(v)
    om = {}
    for sign, (n, srest, nup) in open_move.items():
        om[sign] = {
            "n": n,
            "mean_rest_return_bp": round(1e4 * srest / n, 2) if n else None,
            "rest_up_rate": round(nup / n, 3) if n else None,
        }
    hour_out = {f"{h:02d}Z": _rate(v) for h, v in sorted(hour.items()) if v[0] >= 20}
    return {
        "n_windows": sum(v[0] for v in hour.values()),
        "favorite_longshot": flb_out,
        "late_certainty_hit": late_out,
        "open_3min_then_rest": om,
        "gold_silver_same_window": {
            "n": agree["n"],
            "agree_rate": round(agree["same"] / agree["n"], 3) if agree["n"] else None,
        },
        "yes_rate_by_utc_hour": hour_out,
        "reading": _reading(flb_out, om, late_out),
    }


def _reading(flb, om, late) -> list[str]:
    notes = []
    # FLB: favorites should win more than priced
    fav = (flb.get("tau_300s") or {}).get(">=0.90")
    longshot = (flb.get("tau_300s") or {}).get("<0.10")
    if fav and fav["n"] and fav["rate"] is not None:
        notes.append(f"At τ=5min, contracts mid≥90c won {fav['rate']:.0%} (n={fav['n']}). "
                     f"{'Supports favorite harvest.' if fav['rate'] >= 0.90 else 'Favorites are NOT reliable.'}")
    if longshot and longshot["n"] and longshot["rate"] is not None:
        notes.append(f"At τ=5min, contracts mid<10c won {longshot['rate']:.0%} (n={longshot['n']}). "
                     f"{'Longshots overpriced — do not buy them.' if longshot['rate'] <= 0.12 else 'No FLB in the left tail.'}")
    up = om.get("up")
    down = om.get("down")
    if up and down and up["n"] and down["n"]:
        # fade works if rest_up_rate after an UP open is < 0.5
        if up["rest_up_rate"] is not None and up["rest_up_rate"] < 0.45:
            notes.append("First-3-minute UP windows mean-revert in the rest — open_fade is plausible.")
        elif up["rest_up_rate"] is not None and up["rest_up_rate"] > 0.55:
            notes.append("First-3-minute UP windows continue — open_follow is plausible.")
        else:
            notes.append("First-3-minute impulse does not predict the rest of the window.")
    lock = (late.get("tau_120s") or {}).get("z>=0.8")
    if lock and lock["n"] and lock["rate"] is not None:
        notes.append(f"At τ=2min, model-certain favorites (z≥0.8) hit {lock['rate']:.0%} "
                     f"(n={lock['n']}). {'late_lock is plausible.' if lock['rate'] >= 0.85 else 'late_lock is weak.'}")
    return notes
