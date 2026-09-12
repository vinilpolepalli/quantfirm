#!/usr/bin/env python3
"""Train-only lag-fill lock scan.

Protocol: TRAIN windows only (close < SPLIT_TS). Do not pass --split test
until the hypotheses are frozen in strategies.registry().

Walks every 1-minute snapshot, applies the same lag-fill rule as
quantfirm.kalshi.backtest, and scores sequential first-fill rules so we do
not double-count windows that stay locked.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.backtest import METALS, Backtest  # noqa: E402
from quantfirm.kalshi.fair import VolEstimator, fair_yes, taker_fee  # noqa: E402
from quantfirm.kalshi.universe import SPLIT_TS  # noqa: E402

COMMODITIES = {"gold", "silver", "copper", "wti", "natgas"}


def _lag_fill(side: str, lim: float, c_next: dict) -> tuple[str, float | None]:
    """Return (status, fill_price). status in filled/raced_out/gapped/no_candle."""
    if not c_next:
        return "no_candle", None
    if side == "yes":
        px_high, px_close = c_next["ask_high"], c_next["ask_close"]
    else:
        bl, bc = c_next["bid_low"], c_next["bid_close"]
        px_high = (1.0 - bl) if bl is not None else None
        px_close = (1.0 - bc) if bc is not None else None
    if px_high is not None and px_high > lim + 1e-9:
        return "raced_out", None
    if px_close is None or px_close > lim + 1e-9:
        return "gapped", None
    return "filled", px_close


def _px_band(p: float) -> str:
    for lo, hi, name in (
        (0.80, 0.84, "80-84"),
        (0.84, 0.88, "84-88"),
        (0.88, 0.90, "88-90"),
        (0.90, 0.92, "90-92"),
        (0.92, 0.94, "92-94"),
        (0.94, 0.96, "94-96"),
        (0.96, 0.98, "96-98"),
    ):
        if lo <= p < hi:
            return name
    return "other"


def _tau_band(tau: int) -> str:
    if tau < 120:
        return "t<2m"
    if tau < 180:
        return "t2-3m"
    if tau < 300:
        return "t3-5m"
    if tau < 420:
        return "t5-7m"
    if tau < 540:
        return "t7-9m"
    if tau < 660:
        return "t9-11m"
    return "t>11m"


def _disp_band(bp: float) -> str:
    if bp < 4:
        return "d<4bp"
    if bp < 8:
        return "d4-8"
    if bp < 16:
        return "d8-16"
    if bp < 32:
        return "d16-32"
    return "d>=32"


def _fair_band(q: float) -> str:
    if q < 0.60:
        return "q<60"
    if q < 0.70:
        return "q60-70"
    if q < 0.80:
        return "q70-80"
    if q < 0.88:
        return "q80-88"
    return "q>=88"


def _sigma_clock(bars: dict[int, float]) -> tuple[list[int], list[float]]:
    """Causal EWMA: parallel arrays of bar-close ts and sigma after that bar."""
    vol = VolEstimator(halflife_min=30.0, diurnal=True)
    ts_out: list[int] = []
    sig_out: list[float] = []
    prev = None
    for ts in sorted(bars):
        px = bars[ts]
        if prev is not None and prev[1] > 0 and px > 0 and 0 < ts - prev[0] <= 120:
            vol.update(ts, math.log(px / prev[1]))
        ts_out.append(ts)
        sig_out.append(vol.sigma_1m(ts))
        prev = (ts, px)
    return ts_out, sig_out


def _sigma_at(clock: tuple[list[int], list[float]], ts: int) -> float:
    import bisect
    keys, sigs = clock
    i = bisect.bisect_right(keys, ts) - 1
    return sigs[i] if i >= 0 else 0.0009


def collect(bt: Backtest, start_ts, end_ts) -> list[dict]:
    sigma = {m: _sigma_clock(b) for m, b in bt.bars.items()}
    rows = []
    for series, mkts in bt.markets.items():
        metal = METALS[series]
        cnds_all = bt.candles.get(series, {})
        bars = bt.bars.get(metal, {})
        clock = sigma.get(metal, {})
        for m in mkts:
            if start_ts and m["close_ts"] < start_ts:
                continue
            if end_ts and m["close_ts"] >= end_ts:
                continue
            tkr = m["ticker"]
            cnds = cnds_all.get(tkr) or {}
            o, c = m["open_ts"], m["close_ts"]
            won_yes = m["result"] == "yes"
            persist_yes = persist_no = 0
            first_lock_ts = None
            for T in range(o + 60, c, 60):
                c_now = cnds.get(T)
                if not c_now or c_now["bid_close"] is None or c_now["ask_close"] is None:
                    persist_yes = persist_no = 0
                    continue
                bid, ask = c_now["bid_close"], c_now["ask_close"]
                if bid <= 0 and ask >= 1:
                    persist_yes = persist_no = 0
                    continue
                no_px = 1.0 - bid
                tau = c - T
                f_now, f_open = bars.get(T), bars.get(o)
                if f_now is None or f_open is None or f_open <= 0:
                    continue
                s = f_now * (m["strike"] / f_open)
                sig = _sigma_at(clock, T)
                fair = fair_yes(s, m["strike"], sig, tau / 60.0)
                disp = abs(math.log(s / m["strike"])) * 1e4 if s > 0 and m["strike"] > 0 else 0.0
                hour = datetime.fromtimestamp(T, tz=timezone.utc).hour
                vol3 = sum((cnds.get(T - 60 * j, {}) or {}).get("volume") or 0.0
                           for j in range(3))
                c_prev = cnds.get(T - 60)
                prev_yes = (c_prev["ask_close"] if c_prev else None)
                prev_no = ((1.0 - c_prev["bid_close"]) if c_prev and c_prev.get("bid_close") is not None else None)

                yes_in = 0.80 <= ask <= 0.97
                no_in = 0.80 <= no_px <= 0.97
                if yes_in:
                    persist_yes += 1
                    persist_no = 0
                elif no_in:
                    persist_no += 1
                    persist_yes = 0
                else:
                    persist_yes = persist_no = 0
                if first_lock_ts is None and (yes_in or no_in):
                    first_lock_ts = T

                for side, cost, in_band, persist, spot_ok, q_side in (
                    ("yes", ask, yes_in, persist_yes, s >= m["strike"], fair),
                    ("no", no_px, no_in, persist_no, s < m["strike"], 1.0 - fair),
                ):
                    if not in_band:
                        continue
                    status, fill = _lag_fill(side, cost, cnds.get(T + 60))
                    win = (side == "yes") == won_yes
                    fee1 = taker_fee(1, fill) if fill is not None else None
                    pnl1 = ((1.0 if win else 0.0) - fill - fee1) if fill is not None else None
                    fade_side = "no" if side == "yes" else "yes"
                    fade_lim = (1.0 - bid) if side == "yes" else ask
                    fade_status, fade_fill = _lag_fill(fade_side, fade_lim, cnds.get(T + 60))
                    fade_win = not win
                    fade_fee = taker_fee(1, fade_fill) if fade_fill is not None else None
                    fade_pnl = ((1.0 if fade_win else 0.0) - fade_fill - fade_fee) if fade_fill is not None else None
                    prev_in = False
                    if side == "yes" and prev_yes is not None:
                        prev_in = 0.80 <= prev_yes <= 0.97
                    if side == "no" and prev_no is not None:
                        prev_in = 0.80 <= prev_no <= 0.97
                    rows.append({
                        "metal": metal, "ticker": tkr, "ts": T, "tau": tau,
                        "side": side, "cost": cost, "fill": fill, "status": status,
                        "win": win, "pnl1": pnl1, "spot_ok": spot_ok,
                        "persist": persist, "prev_in": prev_in,
                        "disp_bp": disp, "fair_side": q_side, "fair_yes": fair,
                        "hour": hour, "vol3": vol3, "px_band": _px_band(cost),
                        "tau_band": _tau_band(tau), "disp_band": _disp_band(disp),
                        "fair_band": _fair_band(q_side),
                        "first_lock": first_lock_ts == T,
                        "london_ny": 12 <= hour < 21,
                        "commodity": metal in COMMODITIES,
                        "fade_status": fade_status, "fade_fill": fade_fill,
                        "fade_pnl": fade_pnl, "fade_win": fade_win,
                    })
    return rows


def summarize(snaps, pred, min_n=20) -> dict | None:
    """Sequential first-fill: one trade per ticker (earliest qualifying fill)."""
    by_tkr = defaultdict(list)
    raced = filled = 0
    for r in snaps:
        if not pred(r):
            continue
        by_tkr[r["ticker"]].append(r)
    pnls = []
    hits = 0
    metals = defaultdict(lambda: [0, 0.0])
    for tkr, rs in by_tkr.items():
        rs.sort(key=lambda x: x["ts"])
        chosen = None
        for r in rs:
            if r["status"] == "raced_out":
                raced += 1
                continue
            if r["status"] == "filled":
                chosen = r
                break
        if chosen is None:
            continue
        filled += 1
        pnls.append(chosen["pnl1"])
        hits += int(chosen["win"])
        metals[chosen["metal"]][0] += 1
        metals[chosen["metal"]][1] += chosen["pnl1"]
    n = len(pnls)
    if n < min_n:
        return None
    pnl = sum(pnls)
    mu = pnl / n
    sd = (sum((x - mu) ** 2 for x in pnls) / (n - 1)) ** 0.5 if n > 1 else 0.0
    t = mu / (sd / n ** 0.5) if sd > 0 else 0.0
    return {
        "n": n, "pnl1": round(pnl, 3), "hit": round(hits / n, 3),
        "t": round(t, 2), "avg": round(mu, 4),
        "raced_seen": raced,
        "by_metal": {k: {"n": v[0], "pnl1": round(v[1], 2)} for k, v in metals.items()},
    }


def summarize_fade(snaps, pred, min_n=20) -> dict | None:
    """Sequential first-fill of the LONGSHOT against a qualifying favorite.

    The snapshot `cost` is the favorite price. We try to buy 1-cost. The
    lag-fill test uses the next candle on that cheap side. Winner's curse
    is the point: uncontested cheap fills may be the ones that never reverse.
    """
    by_tkr = defaultdict(list)
    for r in snaps:
        if not pred(r):
            continue
        by_tkr[r["ticker"]].append(r)
    pnls = []
    hits = 0
    metals = defaultdict(lambda: [0, 0.0])
    raced = 0
    for tkr, rs in by_tkr.items():
        rs.sort(key=lambda x: x["ts"])
        chosen = None
        for r in rs:
            if r["fade_status"] == "raced_out":
                raced += 1
                continue
            if r["fade_status"] != "filled" or r["fade_pnl"] is None:
                continue
            chosen = r
            break
        if chosen is None:
            continue
        pnls.append(chosen["fade_pnl"])
        hits += int(chosen["fade_win"])
        metals[chosen["metal"]][0] += 1
        metals[chosen["metal"]][1] += chosen["fade_pnl"]
    n = len(pnls)
    if n < min_n:
        return None
    pnl = sum(pnls)
    mu = pnl / n
    sd = (sum((x - mu) ** 2 for x in pnls) / (n - 1)) ** 0.5 if n > 1 else 0.0
    t = mu / (sd / n ** 0.5) if sd > 0 else 0.0
    return {
        "n": n, "pnl1": round(pnl, 3), "hit": round(hits / n, 3),
        "t": round(t, 2), "avg": round(mu, 4), "raced_seen": raced,
        "by_metal": {k: {"n": v[0], "pnl1": round(v[1], 2)} for k, v in metals.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(REPO, "data/kalshi"))
    ap.add_argument("--split", choices=["train"], default="train",
                    help="train only — looking at test here is a protocol break")
    args = ap.parse_args()
    if args.split != "train":
        raise SystemExit("train only")
    bt = Backtest(args.data)
    print(f"loaded series={list(bt.markets)} metals={list(bt.bars)}", flush=True)
    rows = collect(bt, None, SPLIT_TS)
    n_win = len({r["ticker"] for r in rows})
    print(f"train snapshots={len(rows)} windows_with_80_97={n_win}", flush=True)

    rules = [
        ("spot 88-94 t3-11 first",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660),
        ("spot 88-94 t5-11 first",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 300 <= r["tau"] <= 660),
        ("spot 88-94 t3-7 first",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 420),
        ("spot 90-94 t3-11 first",
         lambda r: r["spot_ok"] and 0.90 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660),
        ("spot 88-92 t3-11 first",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.92 and 180 <= r["tau"] <= 660),
        ("held 88-94 persist>=2 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["persist"] >= 2),
        ("held 88-94 persist>=3 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["persist"] >= 3),
        ("held 88-94 persist>=2 t5-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 300 <= r["tau"] <= 660 and r["persist"] >= 2),
        ("disp>=8bp 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["disp_bp"] >= 8),
        ("disp>=16bp 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["disp_bp"] >= 16),
        ("disp>=16bp 88-94 persist>=2",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["persist"] >= 2 and r["disp_bp"] >= 16),
        ("fair>=70 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["fair_side"] >= 0.70),
        ("fair>=80 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["fair_side"] >= 0.80),
        ("fair>=88 80-94 t2-6 (model_fav-ish)",
         lambda r: r["spot_ok"] and 0.80 <= r["cost"] <= 0.94 and 120 <= r["tau"] <= 360 and r["fair_side"] >= 0.88),
        ("fair>=80 persist>=2 88-94",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["persist"] >= 2 and r["fair_side"] >= 0.80),
        ("london_ny 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["london_ny"]),
        ("not london_ny 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and not r["london_ny"]),
        ("vol3>=150 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["vol3"] >= 150),
        ("gold/silver 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["metal"] in ("gold", "silver")),
        ("gold only 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["metal"] == "gold"),
        ("silver only 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["metal"] == "silver"),
        ("skip-first 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and not r["first_lock"]),
        ("FLB no-spot 88-94 t3-11",
         lambda r: 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660),
        ("held persist>=2 90-94 t3-11",
         lambda r: r["spot_ok"] and 0.90 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["persist"] >= 2),
        ("disp>=8 persist>=2 88-94",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["persist"] >= 2 and r["disp_bp"] >= 8),
        ("fair>=70 persist>=2 88-94 t5-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 300 <= r["tau"] <= 660 and r["persist"] >= 2 and r["fair_side"] >= 0.70),
        ("NO-side 88-94 t3-11",
         lambda r: r["spot_ok"] and r["side"] == "no" and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660),
        ("YES-side 88-94 t3-11",
         lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["side"] == "yes"),
    ]

    print(f"\n{'rule':<48} {'n':>4} {'pnl1':>8} {'hit':>6} {'t':>6}  metals")
    scored = []
    for name, pred in rules:
        s = summarize(rows, pred, min_n=15)
        if s is None:
            print(f"{name:<48} n<15")
            continue
        scored.append((name, s))
        print(f"{name:<48} {s['n']:4} {s['pnl1']:+8.2f} {s['hit']:6.3f} {s['t']:6.2f}  {s['by_metal']}")

    print("\n--- sequential 88-94 t3-11 spot-agree by UTC hour ---")
    for h in range(24):
        s = summarize(
            rows,
            lambda r, hour=h: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94
            and 180 <= r["tau"] <= 660 and r["hour"] == hour,
            min_n=8)
        if s:
            print(f"  {h:02d}Z n={s['n']:3} pnl1={s['pnl1']:+6.2f} hit={s['hit']:.3f} t={s['t']:+5.2f}")

    print("\n--- sequential 88-94 t3-11 spot-agree by week ---")
    def week(r):
        return datetime.fromtimestamp(r["ts"], tz=timezone.utc).strftime("%G-W%V")
    weeks = sorted({week(r) for r in rows})
    for w in weeks:
        for label, extra in (
            ("all", lambda r: True),
            ("offhours", lambda r: not r["london_ny"]),
            ("liqhrs", lambda r: r["london_ny"]),
        ):
            s = summarize(
                rows,
                lambda r, w=w, extra=extra: extra(r) and r["spot_ok"]
                and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660
                and week(r) == w,
                min_n=5)
            if s:
                print(f"  {w} {label:<8} n={s['n']:3} pnl1={s['pnl1']:+6.2f} hit={s['hit']:.3f} t={s['t']:+5.2f}")

    print("\n--- overnight variants ---")
    for name, pred in (
        ("off 12-21 (asia+late)", lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and not (12 <= r["hour"] < 21)),
        ("off 13-20 (tight COMEX)", lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and not (13 <= r["hour"] < 20)),
        ("asia 21-12", lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and (r["hour"] >= 21 or r["hour"] < 12)),
        ("asia 00-08", lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["hour"] < 8),
        ("off + persist>=2", lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and not (12 <= r["hour"] < 21) and r["persist"] >= 2),
        ("off + gold/silver", lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and not (12 <= r["hour"] < 21) and r["metal"] in ("gold", "silver")),
        ("off + NO-side", lambda r: r["spot_ok"] and r["side"] == "no" and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and not (12 <= r["hour"] < 21)),
        ("liq 12-21 persist>=2", lambda r: r["spot_ok"] and 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and (12 <= r["hour"] < 21) and r["persist"] >= 2),
    ):
        s = summarize(rows, pred, min_n=15)
        if s is None:
            print(f"{name:<32} n<15")
        else:
            print(f"{name:<32} n={s['n']:3} pnl1={s['pnl1']:+6.2f} hit={s['hit']:.3f} t={s['t']:+5.2f} {s['by_metal']}")

    print("\n--- FADE: buy the longshot against an 88-94 favorite (train) ---")
    for name, pred in (
        ("fade 88-94 always t3-11",
         lambda r: 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660),
        ("fade 88-94 liquid 12-21",
         lambda r: 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["london_ny"]),
        ("fade 88-94 offhours",
         lambda r: 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and not r["london_ny"]),
        ("fade 88-94 persist>=2 liquid",
         lambda r: 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["london_ny"] and r["persist"] >= 2),
        ("fade 88-94 persist>=2 always",
         lambda r: 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["persist"] >= 2),
        ("fade 90-94 liquid",
         lambda r: 0.90 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["london_ny"]),
        ("fade 88-94 t3-5 liquid",
         lambda r: 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 300 and r["london_ny"]),
        ("fade 88-94 gold/silver liquid",
         lambda r: 0.88 <= r["cost"] <= 0.94 and 180 <= r["tau"] <= 660 and r["london_ny"] and r["metal"] in ("gold", "silver")),
    ):
        # reuse snaps but invert: a fade fill is the OTHER side of this favorite
        s = summarize_fade(rows, pred, min_n=15)
        if s is None:
            print(f"{name:<36} n<15")
        else:
            print(f"{name:<36} n={s['n']:3} pnl1={s['pnl1']:+6.2f} hit={s['hit']:.3f} t={s['t']:+5.2f} {s['by_metal']}")

    print("\n--- pooled (not sequential) lag-filled 88-94 spot-agree by tau ---")
    bucket = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        if r["status"] != "filled":
            continue
        if not (r["spot_ok"] and 0.88 <= r["cost"] <= 0.94):
            continue
        b = r["tau_band"]
        bucket[b][0] += 1
        bucket[b][1] += int(r["win"])
        bucket[b][2] += r["pnl1"]
    for b, (n, w, p) in sorted(bucket.items()):
        print(f"  {b:<8} n={n:4} hit={w/n:.3f} pnl1={p:+.2f}")


if __name__ == "__main__":
    main()
