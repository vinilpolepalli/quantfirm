#!/usr/bin/env python3
"""Score OSS prediction-market skills against this desk. No orders.

The skills are doctrine, not a plug-in edge. This script recomputes the
pieces we can measure on our own tape and on the public book:

  * weather-hist forecast take (already in research/kalshi_div_weather_hist.json)
  * favorite-longshot fade of 5–20¢ YES brackets (the claim that survives
    their catalog) — taker at the recorded bid, maker as an UPPER BOUND
  * live public books: weather highs + one BTC hourly range (dutch + cheap tails)
  * incentive-paper verdict, recomputed from state, never inherited

    python3 scripts/kalshi_oss_skills_eval.py
    python3 scripts/kalshi_oss_skills_eval.py --offline
    python3 scripts/kalshi_oss_skills_eval.py --hist-candles

Nothing here arms a desk. Kill switches stay untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.fair import taker_fee
from quantfirm.kalshi.ladder import exclusive_dutch, exclusive_mid_sum, legs_from_markets
from quantfirm.kalshi.weather_brackets import (
    bracket_p_yes, parse_weather_ticker,
)

HIST = os.path.join(REPO, "research", "kalshi_div_weather_hist.json")
INCENTIVE = os.path.join(REPO, "state", "kalshi_incentive_paper.json")
OUT = os.path.join(REPO, "research", "kalshi_oss_skills.json")

WEATHER_SERIES = (
    "KXHIGHNY", "KXHIGHCHI", "KXHIGHTBOS", "KXHIGHHOU",
    "KXHIGHLAX", "KXHIGHMIA", "KXHIGHDEN",
)
RANGE_SERIES = ("KXBTC", "KXETH", "KXINX")
FLB_LO, FLB_HI = 0.05, 0.20
COUNT = 1


def _f(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def fade_taker(yes_ask, yes_bid, won_yes, count=COUNT):
    """Buy NO as a taker when YES is a cheap longshot.

    Pay the NO ask = 1 − yes_bid. If only the ask is known, refuse —
    crossing at 1−ask invents a fill.
    """
    bid = _f(yes_bid)
    if bid is None or not (0 < bid < 1):
        return None
    no_px = 1.0 - bid
    if no_px <= 0 or no_px >= 1:
        return None
    fee = taker_fee(count, no_px)
    gross = count * ((0.0 if won_yes else 1.0) - no_px)
    return {
        "mode": "taker_no",
        "no_px": round(no_px, 4),
        "fee": fee,
        "pnl": round(gross - fee, 4),
        "won_yes": bool(won_yes),
    }


def fade_maker_upper(yes_ask, won_yes, count=COUNT):
    """Print-replay maker: sold YES at the cheap ask. UPPER BOUND.

    Assumes the resting ask was filled. Real fills are the adversely
    selected subset of the tape.
    """
    px = _f(yes_ask)
    if px is None or not (FLB_LO <= px <= FLB_HI):
        return None
    pnl = count * ((-(1.0 - px)) if won_yes else px)
    return {
        "mode": "maker_yes_ask_upper",
        "px": px,
        "fee": 0.0,
        "pnl": round(pnl, 4),
        "won_yes": bool(won_yes),
    }


def in_flb_band(yes_ask):
    px = _f(yes_ask)
    return px is not None and FLB_LO <= px <= FLB_HI


def replay_hist(path=HIST):
    with open(path) as f:
        hist = json.load(f)
    events = hist.get("events") or []
    scored = [e for e in events if (e.get("n_members") or 0) > 0]
    ens_pnl = sum(_f(e.get("pnl")) or 0 for e in scored)
    ens_n = sum(int(e.get("n_trades") or 0) for e in scored)
    modal_hits = sum(1 for e in scored if e.get("modal_hit"))
    flb_taker = []
    flb_maker = []
    gauss_rows = []
    for e in scored:
        winner = e.get("winner")
        won_map = {}
        if winner:
            won_map[winner] = True
        for t in e.get("trades") or []:
            tkr = t.get("ticker")
            won = bool(t.get("won_yes"))
            won_map[tkr] = won
            if not in_flb_band(t.get("ask")):
                continue
            tk = fade_taker(t.get("ask"), t.get("bid"), won)
            mk = fade_maker_upper(t.get("ask"), won)
            rec = {"event": e.get("event"), "ticker": tkr, "ask": t.get("ask"),
                   "bid": t.get("bid"), "ens_side": t.get("side")}
            if tk:
                flb_taker.append({**rec, **tk})
            if mk:
                flb_maker.append({**rec, **mk})
        parsed = parse_weather_ticker(winner or "")
        if parsed.get("kind") == "bracket" and e.get("ens_mean"):
            try:
                gp = bracket_p_yes(parsed["floor"], parsed["cap"],
                                   float(e["ens_mean"]), 2.5)
            except (TypeError, ValueError):
                gp = None
            gauss_rows.append({
                "event": e.get("event"),
                "ens_p_winner": e.get("p_winner"),
                "gauss_p_winner_sigma2_5": None if gp is None else round(gp, 4),
                "modal_hit": e.get("modal_hit"),
            })
    def _sum(rows):
        return {
            "n": len(rows),
            "pnl": round(sum(r["pnl"] for r in rows), 4),
            "hits": sum(1 for r in rows if not r["won_yes"]),
            "longshot_hits": sum(1 for r in rows if r["won_yes"]),
        }
    return {
        "source": os.path.relpath(path, REPO),
        "n_events_in_file": len(events),
        "n_events": len(scored),
        "modal_hits": modal_hits,
        "modal_hit_rate": round(modal_hits / len(scored), 4) if scored else None,
        "ensemble_take": {"n": ens_n, "pnl": round(ens_pnl, 4)},
        "flb_taker_from_recorded_quotes": _sum(flb_taker),
        "flb_maker_upper_from_recorded_quotes": _sum(flb_maker),
        "note": (
            "FLB rows are only legs the ensemble script already quoted "
            "(ask 5–20¢). That is a selected subset, not a full-book fade. "
            "Maker P&L assumes every cheap ask filled — an upper bound."
        ),
        "gaussian_vs_ensemble_winner": gauss_rows,
        "trades": {"taker": flb_taker, "maker": flb_maker},
    }


def incentive_verdict_now(path=INCENTIVE):
    if not os.path.exists(path):
        return {"ok": False, "reason": "no state file"}
    # Import the desk's own gate — do not substitute a read.
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import kalshi_incentive_paper as lip
    with open(path) as f:
        st = json.load(f)
    now = datetime.now(timezone.utc)
    code, why = lip.verdict(st, now)
    started = lip._ts(st["started"])
    run_h = (now - started).total_seconds() / 3600.0
    r24 = lip.trailing_rate(st.get("history") or [], 24.0, now)
    last = (st.get("history") or [{}])[-1].get("t")
    return {
        "ok": True,
        "verdict": code,
        "reason": why,
        "run_hours": round(run_h, 2),
        "trailing_24h_per_day": None if r24 is None else round(r24, 4),
        "accrued_total_not_a_rate": st.get("accrued"),
        "capital": st.get("capital"),
        "last_tick": last,
        "gate_min_hours": lip.MIN_HOURS,
    }


def _public_get(path, params=None):
    import requests
    url = "https://api.elections.kalshi.com/trade-api/v2" + path
    r = requests.get(url, params=params, timeout=20,
                     headers={"User-Agent": "quantfirm-research/0.1 (oss-skills-eval)"})
    if r.status_code != 200:
        return None
    return r.json()


def page_open(series, limit_pages=3):
    rows, cursor, pages = [], None, 0
    while pages < limit_pages:
        params = {"series_ticker": series, "status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        d = _public_get("/markets", params)
        if not d:
            break
        batch = d.get("markets") or []
        rows.extend(batch)
        pages += 1
        cursor = d.get("cursor")
        if not cursor or not batch:
            break
        time.sleep(0.05)
    return rows


def score_event_books(markets):
    by_ev = defaultdict(list)
    for m in markets:
        ev = m.get("event_ticker")
        if ev:
            by_ev[ev].append(m)
    out = []
    for ev, mkts in by_ev.items():
        legs = legs_from_markets(mkts)
        dutch = exclusive_dutch(legs)
        mids = exclusive_mid_sum(legs)
        cheap = []
        for lg in legs:
            if in_flb_band(lg.yes_ask):
                cheap.append({
                    "ticker": lg.ticker,
                    "yes_ask": lg.yes_ask,
                    "yes_bid": lg.yes_bid,
                    "yes_ask_size": lg.yes_ask_size,
                    "volume": lg.volume,
                    "strike_type": lg.strike_type,
                })
        out.append({
            "event": ev,
            "n_legs": len(legs),
            "n_flb_asks": len(cheap),
            "flb_asks": cheap,
            "dutch_tradeable": bool(dutch.get("tradeable")),
            "sum_ask": dutch.get("sum_ask"),
            "buy_reason": dutch.get("buy_reason"),
            "sell_reason": dutch.get("sell_reason"),
            "mid_sum": mids.get("mid_sum"),
        })
    return out


def live_snapshot():
    weather, ranges = [], []
    for series in WEATHER_SERIES:
        mkts = page_open(series, limit_pages=2)
        scored = score_event_books(mkts)
        weather.extend(scored)
        time.sleep(0.08)
    for series in RANGE_SERIES:
        mkts = page_open(series, limit_pages=4)
        scored = score_event_books(mkts)
        # keep the fattest event only — hourly BTC has 80–300 legs
        scored.sort(key=lambda r: r["n_legs"], reverse=True)
        if scored:
            ranges.append({"series": series, **scored[0],
                           "n_open_events": len(scored)})
        time.sleep(0.08)
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "weather": weather,
        "ranges": ranges,
        "weather_n_events": len(weather),
        "weather_n_flb": sum(e["n_flb_asks"] for e in weather),
        "weather_dutch_tradeable": sum(1 for e in weather if e["dutch_tradeable"]),
        "range_dutch_tradeable": sum(1 for e in ranges if e["dutch_tradeable"]),
    }


def hist_candles_flb(hist_path=HIST, max_events=48):
    """Re-quote every settled hist leg at 12:00 UTC and fade 5–20¢ YES.

    Decision time matches research/kalshi_div_nowcast.md. Still a
    taker/maker print-replay, not a live fill. Uses every settled
    city-day in the file, including days with no archived ensemble.
    """
    with open(hist_path) as f:
        hist = json.load(f)
    rows = []
    events = [e for e in (hist.get("events") or []) if e.get("winner")]
    for e in events[:max_events]:
        series, ev, day = e.get("series"), e.get("event"), e.get("day")
        winner = e.get("winner")
        if not (series and ev and day):
            continue
        try:
            decision_ts = int(datetime(int(day[:4]), int(day[5:7]),
                                       int(day[8:10]), 12, 0,
                                       tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
        d = _public_get("/markets", {"event_ticker": ev, "limit": 200})
        mkts = (d or {}).get("markets") or []
        if not mkts:
            # settled events sometimes need status=
            d = _public_get("/markets",
                            {"event_ticker": ev, "status": "settled", "limit": 200})
            mkts = (d or {}).get("markets") or []
        time.sleep(0.08)
        for m in mkts:
            tkr = m.get("ticker")
            won = (m.get("result") == "yes") or (tkr == winner)
            sticks = _public_get(
                f"/series/{series}/markets/{tkr}/candlesticks",
                {"start_ts": decision_ts - 180, "end_ts": decision_ts + 60,
                 "period_interval": 1},
            )
            time.sleep(0.06)
            ask = bid = None
            best = None
            for c in (sticks or {}).get("candlesticks") or []:
                end = c.get("end_period_ts")
                a = ((c.get("yes_ask") or {}).get("close_dollars")
                     or (c.get("yes_ask") or {}).get("close"))
                b = ((c.get("yes_bid") or {}).get("close_dollars")
                     or (c.get("yes_bid") or {}).get("close"))
                rec = {"ts": end, "ask": _f(a), "bid": _f(b)}
                if best is None or abs(end - decision_ts) < abs(best["ts"] - decision_ts):
                    best = rec
            if best:
                ask, bid = best["ask"], best["bid"]
            if not in_flb_band(ask):
                continue
            tk = fade_taker(ask, bid, won)
            mk = fade_maker_upper(ask, won)
            rows.append({
                "event": ev, "ticker": tkr, "ask": ask, "bid": bid,
                "won_yes": won, "taker": tk, "maker": mk,
            })
    taker = [r["taker"] for r in rows if r.get("taker")]
    maker = [r["maker"] for r in rows if r.get("maker")]
    return {
        "n_cheap_legs": len(rows),
        "taker_n": len(taker),
        "taker_pnl": round(sum(x["pnl"] for x in taker), 4),
        "taker_longshot_hits": sum(1 for x in taker if x["won_yes"]),
        "maker_upper_n": len(maker),
        "maker_upper_pnl": round(sum(x["pnl"] for x in maker), 4),
        "maker_upper_longshot_hits": sum(1 for x in maker if x["won_yes"]),
        "legs": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="skip public-API snapshots")
    ap.add_argument("--hist-candles", action="store_true",
                    help="re-quote weather hist legs at 12:00 UTC")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "verdict": "DO_NOT_RUN_OSS_BOTS_LIVE",
        "hist": replay_hist(),
        "incentive": incentive_verdict_now(),
        "live": None,
        "hist_candles": None,
    }
    print("=== OSS skills eval (no orders) ===")
    h = out["hist"]
    print(f"weather hist events={h['n_events']} modal_hit={h['modal_hits']}/{h['n_events']} "
          f"ensemble_take n={h['ensemble_take']['n']} pnl={h['ensemble_take']['pnl']:+.2f}")
    ft = h["flb_taker_from_recorded_quotes"]
    fm = h["flb_maker_upper_from_recorded_quotes"]
    print(f"FLB on recorded 5–20¢ quotes: taker n={ft['n']} pnl={ft['pnl']:+.2f} "
          f"longshot_hits={ft['longshot_hits']} | maker_upper n={fm['n']} "
          f"pnl={fm['pnl']:+.2f} longshot_hits={fm['longshot_hits']}")
    inv = out["incentive"]
    if inv.get("ok"):
        print(f"incentive gate: {inv['verdict']} ({inv['reason']})")
        print(f"  run_hours={inv['run_hours']} trailing_24h/day="
              f"{inv['trailing_24h_per_day']} accrued_total="
              f"{inv['accrued_total_not_a_rate']}  (accrued is not a rate)")

    if not args.offline:
        try:
            out["live"] = live_snapshot()
            live = out["live"]
            print(f"live weather events={live['weather_n_events']} "
                  f"5–20¢ asks={live['weather_n_flb']} "
                  f"dutch_tradeable={live['weather_dutch_tradeable']}")
            for r in live["ranges"]:
                print(f"live {r['event']}: legs={r['n_legs']} "
                      f"sum_ask={r['sum_ask']} dutch={r['dutch_tradeable']} "
                      f"flb_asks={r['n_flb_asks']}")
        except Exception as e:
            out["live"] = {"error": repr(e)}
            print(f"live snapshot failed: {e}")
        if args.hist_candles:
            try:
                out["hist_candles"] = hist_candles_flb()
                c = out["hist_candles"]
                print(f"hist candles FLB: cheap_legs={c['n_cheap_legs']} "
                      f"taker {c['taker_n']} pnl={c['taker_pnl']:+.2f} "
                      f"maker_upper {c['maker_upper_n']} pnl={c['maker_upper_pnl']:+.2f}")
            except Exception as e:
                out["hist_candles"] = {"error": repr(e)}
                print(f"hist candles failed: {e}")

    # Drop bulky trade lists from the written file? Keep them — research.
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(f"wrote {os.path.relpath(args.out, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
