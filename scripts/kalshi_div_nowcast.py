#!/usr/bin/env python3
"""Weather / ladder / extra-crypto / macro nowcast research.

Public Kalshi + NOAA/Open-Meteo/FRED only. Never arms live. Extra
crypto scoring uses the same lag-fill bar as the 15m desk. Ladder
arbs must be complete, sized, and fee-aware.

    python3 scripts/kalshi_div_nowcast.py
    python3 scripts/kalshi_div_nowcast.py --phase catalog,snapshot,weather,macro
    python3 scripts/kalshi_div_nowcast.py --phase score --skip-harvest
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.client import KalshiClient
from quantfirm.kalshi.ladder import (
    ensemble_to_brackets, exclusive_dutch, exclusive_mid_sum,
    fee_aware_edge, legs_from_markets, nested_monotone, takeable_edge,
)
from quantfirm.kalshi.nowcast import (
    ENSEMBLE_MODELS, FRED_CCSA, FRED_CPI, FRED_CPILFESL, FRED_CSV,
    FRED_GDPNOW, FRED_ICSA, OPEN_METEO_ENSEMBLE, WEATHER_STATIONS,
    event_date_from_ticker, mom_from_index, parse_fred_csv, seasonal_claims_expect,
)
from quantfirm.kalshi.strategies import crypto_wait_params, favorite_blind, registry
from quantfirm.kalshi.universe import BANKROLL, SERIES_CRYPTO_EXTRA

# Liquid 15m names that were on the venue but not in SERIES_CRYPTO_EXTRA.
# Scored the same wait3/≥75¢/4% bar. Not PAPER_ASSETS.
SERIES_CRYPTO_SCOUT = {
    "KXHYPE15M": "hype",
    "KXBNB15M": "bnb",
    "KXZEC15M": "zec",
}

OUT = os.path.join(REPO, "research")
DATA = os.path.join(REPO, "data", "kalshi")
BASE = "https://api.elections.kalshi.com/trade-api/v2"
S = requests.Session()
S.headers["User-Agent"] = "quantfirm-research/0.1 (kalshi-div-nowcast)"

CRYPTO_15M = [
    "KXBTC15M", "KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M",
    "KXADA15M", "KXBCH15M", "KXBNB15M", "KXHYPE15M", "KXNEAR15M",
    "KXTON15M", "KXZEC15M", "KXCRYPTOCOMP15M", "KXCRYPTOLEAD15M",
]
CRYPTO_RANGE = [
    "KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE",
    "KXBNB", "KXHYPE", "KXNEAR", "KXTON", "KXZEC",
]
CRYPTO_DIR = ["KXBTCD", "KXETHD", "KXSOLD", "KXXRPD", "KXDOGED"]
MACRO_HINTS = (
    "CPI", "GDP", "PAYROLL", "NFP", "JOBLESS", "CLAIMS", "INFLATION",
    "PCE", "FOMC", "UNEMPLOY", "CORE",
)
WEATHER_HINTS = (
    "HIGH", "LOWT", "RAIN", "HURR", "TEMP", "SNOW", "WIND", "LANDFALL",
)
MIN_CLOSE = "2026-08-28T00:00:00+00:00"


def get(path, params=None, tries=6):
    for i in range(tries):
        try:
            r = S.get(BASE + path, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.2 * 2 ** i + random.random())
                continue
            print(f"HTTP {r.status_code} {path} {r.text[:160]}", flush=True)
            return None
        except Exception as e:
            print(f"ERR {path}: {e}", flush=True)
            time.sleep(1.2 * 2 ** i)
    return None


def ext_get(url, params=None, tries=4, headers=None):
    hdr = {"User-Agent": S.headers["User-Agent"]}
    if headers:
        hdr.update(headers)
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=30, headers=hdr)
            if r.status_code == 200:
                if "json" in (r.headers.get("content-type") or ""):
                    return r.json()
                return r.text
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.0 * 2 ** i)
                continue
            print(f"HTTP {r.status_code} {url[:80]}", flush=True)
            return None
        except Exception as e:
            print(f"ERR {url[:80]}: {e}", flush=True)
            time.sleep(0.8 * 2 ** i)
    return None


def page_series():
    rows, cursor = [], None
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        d = get("/series", params)
        if not d:
            break
        batch = d.get("series") or []
        rows.extend(batch)
        cursor = d.get("cursor")
        if not cursor:
            break
        time.sleep(0.03)
    return rows


def page_markets(series, status="open", limit_pages=8, min_close_ts=None):
    rows, cursor, pages = [], None, 0
    while pages < limit_pages:
        params = {"series_ticker": series, "status": status, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        d = get("/markets", params)
        if not d:
            break
        batch = d.get("markets") or []
        rows.extend(batch)
        pages += 1
        cursor = d.get("cursor")
        if not cursor or not batch:
            break
        if min_close_ts and batch:
            oldest = min(_ts(m.get("close_time") or m.get("expiration_time")) or 0
                         for m in batch)
            if oldest < min_close_ts:
                break
        time.sleep(0.08)
    if min_close_ts:
        rows = [m for m in rows if (_ts(m.get("close_time") or m.get("expiration_time"))
                                   or 0) >= min_close_ts]
    return rows


def page_events(series, status="open", limit=20):
    d = get("/events", {"series_ticker": series, "status": status, "limit": limit,
                         "with_nested_markets": "true"})
    if not d:
        return []
    return d.get("events") or []


def _ts(raw):
    if not raw:
        return None
    try:
        return int(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _f(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def slim_series(s):
    return {
        "ticker": s.get("ticker"),
        "title": s.get("title"),
        "category": s.get("category"),
        "frequency": s.get("frequency"),
        "fee_type": s.get("fee_type"),
        "fee_multiplier": s.get("fee_multiplier"),
        "tags": s.get("tags"),
        "settlement_sources": s.get("settlement_sources"),
        "contract_terms_url": s.get("contract_terms_url"),
    }


def interesting(s):
    tkr = (s.get("ticker") or "").upper()
    title = (s.get("title") or "").upper()
    cat = s.get("category") or ""
    blob = tkr + " " + title
    if cat in ("Climate and Weather", "Crypto", "Economics"):
        return True
    if tkr in CRYPTO_15M + CRYPTO_RANGE + CRYPTO_DIR:
        return True
    if any(h in tkr or h in title for h in MACRO_HINTS + WEATHER_HINTS):
        return True
    return False


# ------------------------------------------------------------------ catalog
def phase_catalog():
    print("catalog: /series", flush=True)
    all_s = page_series()
    print(f"catalog: {len(all_s)} series", flush=True)
    by_cat = defaultdict(int)
    for s in all_s:
        by_cat[s.get("category") or "?"] += 1
    picked = [slim_series(s) for s in all_s if interesting(s)]
    weather = [s for s in picked if s["category"] == "Climate and Weather"
               or any(h in (s["ticker"] or "") for h in ("HIGH", "RAIN", "HUR", "TEMP"))]
    crypto = [s for s in picked if s["category"] == "Crypto"
              or (s["ticker"] or "").startswith("KX") and "15M" in (s["ticker"] or "")]
    econ = [s for s in picked if s["category"] == "Economics"]
    open_counts = {}
    for ticker in (CRYPTO_15M + CRYPTO_RANGE[:6] + [
            "KXCPI", "KXCPICORE", "KXPAYROLLS", "KXUSNFP", "KXJOBLESS",
            "JOBLESS", "KXCONTCLAIMS", "KXCPIYOY", "KXGDP", "GDP",
            "KXHIGHNY", "KXHIGHTBOS", "KXHIGHCHI", "KXHOUHIGH",
            "RAINNY", "HURCLAND"]):
        mkts = page_markets(ticker, status="open", limit_pages=2)
        vol = sum(_f(m.get("volume_fp") or m.get("volume")) or 0 for m in mkts)
        open_counts[ticker] = {
            "n_open": len(mkts),
            "volume": round(vol, 2),
            "events": sorted({m.get("event_ticker") for m in mkts if m.get("event_ticker")}),
            "sample": (mkts[0].get("ticker") if mkts else None),
            "title": (mkts[0].get("title") if mkts else None),
            "floor": mkts[0].get("floor_strike") if mkts else None,
            "cap": mkts[0].get("cap_strike") if mkts else None,
        }
        print(f"  {ticker:18} open={len(mkts):4} vol={vol:.0f}", flush=True)
        time.sleep(0.05)
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "n_series": len(all_s),
        "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        "n_picked": len(picked),
        "weather": weather,
        "crypto": crypto,
        "economics": econ,
        "open_counts": open_counts,
    }
    _dump("kalshi_div_catalog.json", out)
    return out


# ------------------------------------------------------------------ snapshot
def _quote_from_ob(ticker, client: KalshiClient):
    try:
        q = client.get_quote(ticker)
    except Exception as e:
        print(f"quote {ticker}: {e}", flush=True)
        return None
    return {
        "yes_bid": _f(q.yes_bid), "yes_ask": _f(q.yes_ask),
        "yes_bid_size": _f(q.yes_bid_size), "yes_ask_size": _f(q.yes_ask_size),
        "ts": q.ts,
    }


def snapshot_event(event, client: KalshiClient | None, kind: str,
                   confirm_ob: bool = False) -> dict:
    mkts = event.get("markets") or []
    if not mkts:
        d = get(f"/events/{event.get('event_ticker')}",
                {"with_nested_markets": "true"})
        if d:
            mkts = (d.get("event") or d).get("markets") or []
            event = d.get("event") or d
    quotes = {}
    if confirm_ob and client is not None:
        for i, m in enumerate(mkts):
            tkr = m.get("ticker")
            if not tkr:
                continue
            quotes[tkr] = _quote_from_ob(tkr, client)
            time.sleep(0.05)
    legs = legs_from_markets(mkts, quotes)
    mutex = bool(event.get("mutually_exclusive"))
    mid = exclusive_mid_sum(legs) if mutex else None
    dutch = exclusive_dutch(legs) if mutex else {
        "n_legs": len(legs), "tradeable": False, "buy_reason": "not_mutex",
        "sell_reason": "not_mutex",
    }
    nested = nested_monotone(legs)
    return {
        "kind": kind,
        "event_ticker": event.get("event_ticker"),
        "title": event.get("title"),
        "mutually_exclusive": event.get("mutually_exclusive"),
        "n_markets": len(mkts),
        "volume": round(sum(_f(m.get("volume_fp") or m.get("volume")) or 0 for m in mkts), 2),
        "mid": mid,
        "dutch": dutch,
        "nested": nested,
        "legs": [
            {
                "ticker": lg.ticker, "floor": lg.floor, "cap": lg.cap,
                "threshold": lg.threshold, "strike_type": lg.strike_type,
                "yes_bid": lg.yes_bid, "yes_ask": lg.yes_ask,
                "yes_bid_size": lg.yes_bid_size, "yes_ask_size": lg.yes_ask_size,
                "volume": lg.volume, "last": lg.last, "title": lg.title,
            }
            for lg in legs
        ],
    }


def phase_snapshot():
    print("snapshot: live event payloads (sizes on the market object)", flush=True)
    client = KalshiClient(env="prod")
    snaps = []
    for series in ("KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"):
        evs = page_events(series, status="open", limit=3)
        print(f"  {series}: {len(evs)} open events", flush=True)
        if not evs:
            continue
        evs = sorted(evs, key=lambda e: e.get("close_time") or e.get("strike_period") or "")
        for ev in evs[:2]:
            print(f"    event {ev.get('event_ticker')} markets={len(ev.get('markets') or [])}",
                  flush=True)
            snaps.append(snapshot_event(ev, client, kind="exclusive_range"))
    for series in ("KXCPICORE", "KXCPI", "KXPAYROLLS", "KXGDP",
                   "KXJOBLESSCLAIMS", "KXCONTCLAIMS"):
        evs = page_events(series, status="open", limit=4)
        print(f"  {series}: {len(evs)} open events", flush=True)
        for ev in evs[:2]:
            snaps.append(snapshot_event(ev, client, kind="nested_macro"))
    for series in ("KXHIGHNY", "KXHIGHTBOS", "KXHIGHCHI", "KXHIGHHOU",
                   "KXDENHIGH", "HIGHMIA"):
        evs = page_events(series, status="open", limit=4)
        print(f"  {series}: {len(evs)} open events", flush=True)
        for ev in evs[:2]:
            snaps.append(snapshot_event(ev, client, kind="weather"))
    tradeable = [s for s in snaps if (s.get("dutch") or {}).get("tradeable")
                 or (s.get("nested") or {}).get("tradeable")]
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "n_events": len(snaps),
        "n_tradeable": len(tradeable),
        "tradeable": [
            {"event": s["event_ticker"], "kind": s["kind"],
             "mutex": s.get("mutually_exclusive"),
             "dutch": s.get("dutch"), "nested": {
                 k: s["nested"][k] for k in ("n_legs", "n_mid_inversions",
                                             "n_locked", "tradeable", "locked")
                 if k in (s.get("nested") or {})}}
            for s in tradeable
        ],
        "events": snaps,
    }
    _dump("kalshi_div_snapshot.json", out)
    return out


# ------------------------------------------------------- historical ladder
def phase_ladder_hist():
    """Settled exclusive events: last-price sum + a few candle replays."""
    print("ladder hist: settled KXBTC/KXETH", flush=True)
    min_ts = _ts(MIN_CLOSE)
    summary = []
    candle_replay = []
    for series in ("KXBTC", "KXETH", "KXHIGHNY", "KXHIGHCHI"):
        mkts = page_markets(series, status="settled", limit_pages=6,
                            min_close_ts=min_ts)
        by_ev = defaultdict(list)
        for m in mkts:
            if m.get("event_ticker"):
                by_ev[m["event_ticker"]].append(m)
        print(f"  {series}: {len(mkts)} settled markets, {len(by_ev)} events",
              flush=True)
        event_rows = []
        for ev, legs in by_ev.items():
            lasts = [_f(m.get("last_price_dollars") or m.get("last_price"))
                     for m in legs]
            vols = [_f(m.get("volume_fp") or m.get("volume")) or 0 for m in legs]
            n_traded = sum(1 for v in vols if v > 0)
            last_ok = [x for x in lasts if x is not None]
            yes_res = sum(1 for m in legs if m.get("result") == "yes")
            event_rows.append({
                "event": ev, "n": len(legs), "n_traded": n_traded,
                "last_sum": round(sum(last_ok), 4) if last_ok else None,
                "n_yes": yes_res,
                "volume": round(sum(vols), 2),
                "close": legs[0].get("close_time"),
            })
        event_rows.sort(key=lambda r: r.get("close") or "", reverse=True)
        summary.append({"series": series, "n_events": len(event_rows),
                         "events": event_rows[:40]})
        # Candle-replay the 2 most recently settled events that have
        # at least 8 traded brackets (otherwise the book was empty).
        # 6-leg weather was skipped by n_traded>=8 (they trade all 6).
        # 80–300-leg hourly ranges were skipped by n<=20. Sample both.
        weather_like = [r for r in event_rows
                        if r["n"] <= 12 and r["n_traded"] >= 4][:2]
        wide = [r for r in event_rows
                if r["n"] > 20 and r["n_traded"] >= 8][:1]
        for row in weather_like + wide:
            ev_mkts = by_ev[row["event"]]
            period = 60 if row["n"] > 20 else 1
            print(f"    replay {row['event']} n={len(ev_mkts)} period={period}",
                  flush=True)
            candle_replay.append(replay_event_candles(
                series, ev_mkts, period_interval=period))
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "settled": summary,
        "candle_replay": candle_replay,
    }
    _dump("kalshi_div_ladder_hist.json", out)
    return out


def replay_event_candles(series, markets, period_interval=1) -> dict:
    """Ask-sum over the event. Depth is volume, not size — so this
    is a *diagnostic* of quoted sum-to-1, not a fill model."""
    by_ts = defaultdict(list)
    for m in markets:
        t0 = _ts(m.get("open_time"))
        t1 = _ts(m.get("close_time"))
        if not t0 or not t1:
            continue
        d = get(f"/series/{series}/markets/{m['ticker']}/candlesticks",
                {"start_ts": t0, "end_ts": t1,
                 "period_interval": period_interval})
        time.sleep(0.08)
        if not d:
            continue
        for c in d.get("candlesticks") or []:
            ts = c.get("end_period_ts")
            ask = ((c.get("yes_ask") or {}).get("close_dollars")
                   or (c.get("yes_ask") or {}).get("close"))
            bid = ((c.get("yes_bid") or {}).get("close_dollars")
                   or (c.get("yes_bid") or {}).get("close"))
            vol = _f(c.get("volume_fp") or c.get("volume")) or 0
            by_ts[ts].append({
                "ticker": m["ticker"],
                "ask": _f(ask), "bid": _f(bid), "vol": vol,
                "floor": _f(m.get("floor_strike")),
                "cap": _f(m.get("cap_strike")),
            })
    minutes = []
    n_sum_ask_lt_1 = n_sum_bid_gt_1 = 0
    for ts in sorted(k for k in by_ts if k):
        legs = by_ts[ts]
        asks = [x["ask"] for x in legs if x["ask"] is not None]
        bids = [x["bid"] for x in legs if x["bid"] is not None]
        if len(asks) == len(markets):
            sask = sum(asks)
            if sask < 1.0:
                n_sum_ask_lt_1 += 1
        else:
            sask = None
        if len(bids) == len(markets):
            sbid = sum(bids)
            if sbid > 1.0:
                n_sum_bid_gt_1 += 1
        else:
            sbid = None
        minutes.append({
            "ts": ts, "n_quoted_ask": len(asks), "n_quoted_bid": len(bids),
            "sum_ask": None if sask is None else round(sask, 4),
            "sum_bid": None if sbid is None else round(sbid, 4),
            "complete_ask": len(asks) == len(markets),
            "complete_bid": len(bids) == len(markets),
        })
    complete = [m for m in minutes if m["complete_ask"] and m["sum_ask"] is not None]
    return {
        "series": series,
        "n_markets": len(markets),
        "n_minutes": len(minutes),
        "n_complete_ask": len(complete),
        "n_sum_ask_lt_1": n_sum_ask_lt_1,
        "n_sum_bid_gt_1": n_sum_bid_gt_1,
        "min_sum_ask": None if not complete else round(min(m["sum_ask"] for m in complete), 4),
        "median_sum_ask": None if not complete else round(
            sorted(m["sum_ask"] for m in complete)[len(complete) // 2], 4),
        "minutes_head": minutes[:8],
        "minutes_tail": minutes[-8:],
    }


# ------------------------------------------------------- extra crypto 15m
def phase_harvest():
    import subprocess
    cmd = [
        sys.executable, os.path.join(REPO, "scripts", "kalshi_harvest.py"),
        "--series", "KXSOL15M", "KXDOGE15M", "KXXRP15M",
        "--min-close", MIN_CLOSE,
    ]
    print("harvest:", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=REPO)


def phase_harvest_scout():
    import subprocess
    cmd = [
        sys.executable, os.path.join(REPO, "scripts", "kalshi_harvest.py"),
        "--series", *SERIES_CRYPTO_SCOUT.keys(),
        "--min-close", MIN_CLOSE,
    ]
    print("harvest scout:", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=REPO)


def _score_row(name, metal, m):
    by = m.get("by_metal") or {}
    weeks = m.get("by_week") or {}
    skip = m.get("skipped") or {}
    return {
        "name": name, "metal": metal,
        "n": m["n_trades"], "pnl": m["net_pnl"], "t": m["t_stat"],
        "hit": m.get("hit_rate"), "dd": m["max_drawdown_pct"],
        "avg_fill": m.get("avg_fill"),
        "by_metal": {k: v for k, v in by.items()},
        "weeks": {w: {"n": v["n"], "pnl": v["pnl"]} for w, v in weeks.items()},
        "skipped": {k: v for k, v in skip.items() if v},
    }


def _score_series_map(wanted, wait_p, no_wait, richer, last7):
    from quantfirm.kalshi.backtest import Backtest
    results = []
    for series, metal in wanted.items():
        mp = os.path.join(DATA, f"markets_{series}.jsonl")
        cp = os.path.join(DATA, f"candles_{series}.csv")
        bp = os.path.join(DATA, f"yf_{metal}_1m.csv")
        have = all(os.path.exists(p) or os.path.exists(p + ".gz")
                   for p in (mp, cp, bp))
        if not have:
            results.append({"name": "missing", "metal": metal, "series": series})
            print(f"  {metal}: missing harvest", flush=True)
            continue
        bt = Backtest(DATA, bankroll=BANKROLL, series={series: metal})
        n_m = len(bt.markets.get(series) or [])
        print(f"  {metal}: markets={n_m}", flush=True)

        def fav(**kw):
            return favorite_blind(**kw, fill_cap=True)

        for label, params in (
            ("wait3_75", wait_p),
            ("nowait_75", no_wait),
            ("wait3_80", richer),
        ):
            for split, lo, hi in (("ALL", None, None), ("7d", last7, None)):
                m = bt.run(params, start_ts=lo, end_ts=hi, decide_fn=fav)
                row = _score_row(label, metal, m)
                row["split"] = split
                results.append(row)
                print(
                    f"    {metal:5} {label:10} {split:4} n={row['n']:4} "
                    f"pnl={row['pnl']:+8.2f} t={row['t']:>5} hit={row['hit']} "
                    f"dd={row['dd']}%",
                    flush=True)
    wait_all = [r for r in results
                if r.get("name") == "wait3_75" and r.get("split") == "ALL"]
    by_metal = {r["metal"]: r for r in wait_all}
    cleared = [
        m for m, r in by_metal.items()
        if (r.get("n") or 0) >= 20 and (r.get("pnl") or 0) > 0
    ]
    return results, cleared


def phase_score():
    from dataclasses import replace
    print("score: extra crypto 15m lag-fill", flush=True)
    specs = {s.name: s for s in registry()}
    rf = specs["rich_fav"]
    wait_p = crypto_wait_params(replace(
        rf.params, price_min=0.75, price_max=0.92, max_stake_frac=0.04,
        kelly_mult=0.25, tau_min_s=0, tau_max_s=720, min_count=4,
        max_spread=1.0, min_recent_volume=0.0), wait_s=180)
    no_wait = replace(wait_p, tau_max_s=900)
    richer = replace(wait_p, price_min=0.80)
    last7 = int(datetime(2026, 9, 5, tzinfo=timezone.utc).timestamp())
    results, cleared = _score_series_map(
        SERIES_CRYPTO_EXTRA, wait_p, no_wait, richer, last7)
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bar": "wait3 ≥75¢ 4% lag-fill; name independently pnl>0 and n>=20",
        "cleared": cleared,
        "promote_paper": bool(cleared),
        "promote_all_three": bool(cleared) and len(cleared) == len(SERIES_CRYPTO_EXTRA),
        "results": results,
    }
    _dump("kalshi_div_crypto_score.json", out)
    return out


def phase_score_scout():
    from dataclasses import replace
    print("score: scout crypto 15m (HYPE/BNB/NEAR/ZEC)", flush=True)
    specs = {s.name: s for s in registry()}
    rf = specs["rich_fav"]
    wait_p = crypto_wait_params(replace(
        rf.params, price_min=0.75, price_max=0.92, max_stake_frac=0.04,
        kelly_mult=0.25, tau_min_s=0, tau_max_s=720, min_count=4,
        max_spread=1.0, min_recent_volume=0.0), wait_s=180)
    no_wait = replace(wait_p, tau_max_s=900)
    richer = replace(wait_p, price_min=0.80)
    last7 = int(datetime(2026, 9, 5, tzinfo=timezone.utc).timestamp())
    results, cleared = _score_series_map(
        SERIES_CRYPTO_SCOUT, wait_p, no_wait, richer, last7)
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bar": "wait3 ≥75¢ 4% lag-fill; name independently pnl>0 and n>=20",
        "cleared": cleared,
        "promote_paper": bool(cleared),
        "results": results,
    }
    _dump("kalshi_div_crypto_scout.json", out)
    return out


# ------------------------------------------------------------------ weather
def fetch_ensemble(lat, lon, tz, daily="temperature_2m_max"):
    members = {}
    meta = {}
    for model in ENSEMBLE_MODELS:
        d = ext_get(OPEN_METEO_ENSEMBLE, {
            "latitude": lat, "longitude": lon, "timezone": tz,
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "daily": daily,
            "models": model,
            "forecast_days": 7,
        })
        time.sleep(0.2)
        if not isinstance(d, dict):
            meta[model] = {"ok": False}
            continue
        daily_d = d.get("daily") or {}
        dates = daily_d.get("time") or []
        # member columns: temperature_2m_max_member01 ...
        mem_cols = [k for k in daily_d if k.startswith(daily) and "member" in k]
        if not mem_cols:
            # some models return only the unperturbed field
            if daily in daily_d:
                mem_cols = [daily]
        by_date = {}
        for i, day in enumerate(dates):
            vals = []
            for col in mem_cols:
                arr = daily_d.get(col) or []
                if i < len(arr) and arr[i] is not None:
                    vals.append(float(arr[i]))
            by_date[day] = vals
        members[model] = by_date
        meta[model] = {"ok": True, "n_members": len(mem_cols),
                        "dates": dates[:7]}
        print(f"    ensemble {model} members={len(mem_cols)} days={len(dates)}",
              flush=True)
    return members, meta


def nws_latest(station: str):
    d = ext_get(
        f"https://api.weather.gov/stations/{station}/observations/latest",
        headers={"Accept": "application/geo+json"},
    )
    if not isinstance(d, dict):
        return None
    props = d.get("properties") or {}
    temp = ((props.get("temperature") or {}).get("value"))
    if temp is None:
        return None
    # NWS is °C
    f = temp * 9.0 / 5.0 + 32.0
    return {"station": station, "temp_f": round(f, 2),
            "timestamp": props.get("timestamp"),
            "text": props.get("textDescription")}


def phase_weather(snapshot=None):
    print("weather: ensemble vs live brackets", flush=True)
    snap_events = []
    if snapshot:
        snap_events = [s for s in snapshot.get("events") or [] if s.get("kind") == "weather"]
    scored = []
    for series, meta in WEATHER_STATIONS.items():
        evs = page_events(series, status="open", limit=3)
        print(f"  {series}: {len(evs)} open", flush=True)
        daily = ("precipitation_sum" if meta["kind"] == "rain"
                 else "temperature_2m_max")
        members, ens_meta = fetch_ensemble(meta["lat"], meta["lon"], meta["tz"],
                                          daily=daily)
        obs = nws_latest(meta["station"])
        for ev in evs[:2]:
            mkts = ev.get("markets") or []
            if not mkts:
                continue
            # Use snapshot quotes if we already pulled them.
            quotes = {}
            match = next((s for s in snap_events
                          if s.get("event_ticker") == ev.get("event_ticker")), None)
            if match:
                for lg in match.get("legs") or []:
                    quotes[lg["ticker"]] = lg
            legs = legs_from_markets(mkts, quotes)
            # Mix GFS + ECMWF members for the event date if we can parse it.
            day = _event_local_date(ev, meta["tz"])
            vals = []
            for model, by_date in members.items():
                vals.extend((by_date.get(day) or []) if day else [])
            dist = ensemble_to_brackets(vals, legs, round_to=1.0) if vals else None
            edges = []
            if dist:
                for lg in legs:
                    p = (dist["probs"] or {}).get(lg.ticker)
                    if p is None:
                        continue
                    e = fee_aware_edge(p, lg.yes_ask, lg.yes_bid, count=5)
                    if e.get("side"):
                        edges.append({"ticker": lg.ticker, "title": lg.title,
                                      **e, "ask": lg.yes_ask, "bid": lg.yes_bid,
                                      "floor": lg.floor, "cap": lg.cap})
            dutch = exclusive_dutch(legs)
            scored.append({
                "series": series, "event": ev.get("event_ticker"),
                "title": ev.get("title"), "day": day, "obs": obs,
                "ensemble": ens_meta, "n_members_used": len(vals),
                "dist": dist, "dutch": dutch,
                "n_edge": len(edges), "edges": edges[:12],
            })
    # Hurricane: catalog only — seasonal, not a 15m clip.
    hur = []
    for series in ("HURCLAND", "KXHURPATHGENERAL", "KXHURLAND"):
        evs = page_events(series, status="open", limit=5)
        hur.append({"series": series, "n_open": len(evs),
                     "titles": [e.get("title") for e in evs[:4]]})
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "settlement": (
            "Daily highs/lows: NWS CLI for the named station (NYC = Central Park "
            "KNYC). Hourly temps: The Weather Company, not NWS. Ensemble "
            "members are GFS GEFS + ECMWF IFS EPS via Open-Meteo, not the print."
        ),
        "hurricane": hur,
        "events": scored,
        "n_tradeable_ensemble": sum(1 for s in scored if s.get("n_edge")),
    }
    _dump("kalshi_div_weather.json", out)
    return out


def _event_local_date(ev, tz_name):
    d = event_date_from_ticker(ev.get("event_ticker") or "")
    if d:
        return d
    raw = ev.get("close_time") or ev.get("target_datetime") or ev.get("expiration_time")
    if not raw:
        return None
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except Exception:
        return str(raw)[:10]


def fetch_ensemble_range(lat, lon, tz, start, end, daily="temperature_2m_max"):
    """Archived GFS GEFS + ECMWF EPS daily fields for [start, end]."""
    members = {}
    meta = {}
    for model in ENSEMBLE_MODELS:
        d = ext_get(OPEN_METEO_ENSEMBLE, {
            "latitude": lat, "longitude": lon, "timezone": tz,
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "daily": daily,
            "models": model,
            "start_date": start,
            "end_date": end,
        })
        time.sleep(0.2)
        if not isinstance(d, dict):
            meta[model] = {"ok": False}
            continue
        daily_d = d.get("daily") or {}
        dates = daily_d.get("time") or []
        mem_cols = [k for k in daily_d if k.startswith(daily) and "member" in k]
        if not mem_cols and daily in daily_d:
            mem_cols = [daily]
        by_date = {}
        for i, day in enumerate(dates):
            vals = []
            for col in mem_cols:
                arr = daily_d.get(col) or []
                if i < len(arr) and arr[i] is not None:
                    vals.append(float(arr[i]))
            by_date[day] = vals
        members[model] = by_date
        meta[model] = {"ok": True, "n_members": len(mem_cols),
                        "n_days": len(dates)}
        print(f"    archive {model} members={len(mem_cols)} days={len(dates)}",
              flush=True)
    return members, meta


def fetch_hrrr_daily_max(lat, lon, tz, start, end):
    """HRRR is deterministic (not an ensemble). Daily max from hourly 2m."""
    urls = (
        "https://historical-forecast-api.open-meteo.com/v1/forecast",
        "https://api.open-meteo.com/v1/forecast",
    )
    for url in urls:
        for model in ("gfs_hrrr", "hrrr"):
            d = ext_get(url, {
                "latitude": lat, "longitude": lon, "timezone": tz,
                "temperature_unit": "fahrenheit",
                "hourly": "temperature_2m",
                "models": model,
                "start_date": start,
                "end_date": end,
            })
            time.sleep(0.15)
            if not isinstance(d, dict):
                continue
            hourly = d.get("hourly") or {}
            times = hourly.get("time") or []
            temps = hourly.get("temperature_2m") or []
            if not times or not temps:
                continue
            by_date = defaultdict(list)
            for t, v in zip(times, temps):
                if v is None:
                    continue
                by_date[str(t)[:10]].append(float(v))
            out = {day: max(vs) for day, vs in by_date.items() if vs}
            if out:
                return {"ok": True, "model": model, "url": url, "by_date": out}
    return {"ok": False}


def _quote_near(series, ticker, ts):
    d = get(f"/series/{series}/markets/{ticker}/candlesticks",
            {"start_ts": ts - 180, "end_ts": ts + 60, "period_interval": 1})
    time.sleep(0.06)
    if not d:
        return None
    best = None
    for c in d.get("candlesticks") or []:
        end = c.get("end_period_ts")
        if not end:
            continue
        ask = ((c.get("yes_ask") or {}).get("close_dollars")
               or (c.get("yes_ask") or {}).get("close"))
        bid = ((c.get("yes_bid") or {}).get("close_dollars")
               or (c.get("yes_bid") or {}).get("close"))
        rec = {"ts": end, "ask": _f(ask), "bid": _f(bid)}
        if best is None or abs(end - ts) < abs(best["ts"] - ts):
            best = rec
    return best


def _weather_take(model_p, ask, bid, count=5, min_px=0.05, max_px=0.92):
    """Skip 1¢ leftovers. Those print a fake edge against a dead band."""
    return takeable_edge(model_p, ask, bid, count=count,
                          min_px=min_px, max_px=max_px)


def _leg_won(lg, result_by_ticker):
    return result_by_ticker.get(lg.ticker) == "yes"


def phase_weather_hist():
    """Settled daily highs: ensemble vs CLI band, plus a morning take.

    Decision is 15:00 UTC (11:00 ET) on the event day — after the 12Z
    GFS/ECMWF cycle, not the 1¢ leftover after the CLI posts. 1¢ asks
    are not takes. This is still an archived ensemble (Open-Meteo
    start_date), not a frozen 12Z run, so treat P&L as an upper bound
    on mapping skill plus a lower bound on execution.
    """
    from quantfirm.kalshi.fair import taker_fee
    print("weather hist: settled highs vs archived ensemble", flush=True)
    min_ts = _ts(MIN_CLOSE)
    cities = [
        ("KXHIGHNY", WEATHER_STATIONS["KXHIGHNY"]),
        ("KXHIGHCHI", WEATHER_STATIONS["KXHIGHCHI"]),
        ("KXHIGHTBOS", WEATHER_STATIONS["KXHIGHTBOS"]),
    ]
    start, end = "2026-08-28", "2026-09-12"
    rows = []
    for series, meta in cities:
        mkts = page_markets(series, status="settled", limit_pages=4,
                            min_close_ts=min_ts)
        by_ev = defaultdict(list)
        for m in mkts:
            if m.get("event_ticker"):
                by_ev[m["event_ticker"]].append(m)
        print(f"  {series}: {len(by_ev)} settled events", flush=True)
        members, ens_meta = fetch_ensemble_range(
            meta["lat"], meta["lon"], meta["tz"], start, end)
        hrrr = fetch_hrrr_daily_max(meta["lat"], meta["lon"], meta["tz"],
                                   start, end)
        for ev, legs_m in sorted(by_ev.items(), reverse=True):
            day = _event_local_date({"event_ticker": ev,
                                     "close_time": legs_m[0].get("close_time")},
                                    meta["tz"])
            if not day:
                continue
            vals = []
            for by_date in members.values():
                vals.extend(by_date.get(day) or [])
            legs = legs_from_markets(legs_m)
            dist = ensemble_to_brackets(vals, legs, round_to=1.0) if vals else None
            winner = next((m["ticker"] for m in legs_m if m.get("result") == "yes"),
                           None)
            result_map = {m["ticker"]: m.get("result") for m in legs_m}
            modal = None
            if dist and dist.get("probs"):
                modal = max(dist["probs"], key=dist["probs"].get)
            hrrr_val = (hrrr.get("by_date") or {}).get(day) if hrrr.get("ok") else None
            hrrr_leg = None
            if hrrr_val is not None:
                from quantfirm.kalshi.ladder import _match_leg
                hrrr_leg = _match_leg(round(hrrr_val), legs)
            # 12:00 UTC = 08:00 ET, after the 00Z/06Z cycles, not the 99¢ afternoon.
            try:
                from zoneinfo import ZoneInfo
                decision_ts = int(datetime(int(day[:4]), int(day[5:7]),
                                           int(day[8:10]), 12, 0,
                                           tzinfo=timezone.utc).timestamp())
            except ValueError:
                decision_ts = None
            trades = []
            pnl = 0.0
            if dist and decision_ts:
                for lg in legs:
                    q = _quote_near(series, lg.ticker, decision_ts)
                    if not q:
                        continue
                    p = (dist["probs"] or {}).get(lg.ticker)
                    if p is None:
                        continue
                    e = _weather_take(p, q.get("ask"), q.get("bid"), count=5)
                    if not e.get("side"):
                        continue
                    won = _leg_won(lg, result_map)
                    px = float(e["px"])
                    fee = taker_fee(5, px)
                    if e["side"] == "yes":
                        gross = 5.0 * ((1.0 if won else 0.0) - px)
                    else:
                        # bought NO; wins when this band is not the CLI print
                        gross = 5.0 * ((0.0 if won else 1.0) - px)
                    t_pnl = round(gross - fee, 4)
                    pnl += t_pnl
                    trades.append({
                        "ticker": lg.ticker, "side": e["side"], "px": px,
                        "model_p": e["model_p"], "won_yes": won,
                        "pnl": t_pnl, "ask": q.get("ask"), "bid": q.get("bid"),
                    })
            brier = None
            if dist and winner:
                brier = round(sum(
                    (((dist["probs"] or {}).get(lg.ticker) or 0)
                     - (1.0 if lg.ticker == winner else 0.0)) ** 2
                    for lg in legs), 4)
            rows.append({
                "series": series, "event": ev, "day": day,
                "n_legs": len(legs_m), "winner": winner,
                "n_members": len(vals),
                "ens_mean": None if not dist else dist.get("mean"),
                "modal": modal, "modal_hit": modal == winner if modal else None,
                "p_winner": None if not (dist and winner) else (dist["probs"] or {}).get(winner),
                "brier": brier,
                "hrrr": hrrr_val, "hrrr_leg": hrrr_leg,
                "hrrr_hit": hrrr_leg == winner if hrrr_leg else None,
                "n_trades": len(trades), "pnl": round(pnl, 4),
                "trades": trades,
                "unmapped": None if not dist else dist.get("unmapped"),
            })
            print(
                f"    {ev} members={len(vals)} modal_hit={modal == winner} "
                f"p_win={(dist['probs'] or {}).get(winner) if dist and winner else None} "
                f"trades={len(trades)} pnl={pnl:+.2f}",
                flush=True)
    # rain / hurricane settled — presence only
    extra = {}
    for series in ("RAINNY", "KXRAINDENM", "HURCLAND", "KXHURLAND"):
        mkts = page_markets(series, status="settled", limit_pages=2,
                            min_close_ts=min_ts)
        extra[series] = {
            "n_settled": len(mkts),
            "events": sorted({m.get("event_ticker") for m in mkts if m.get("event_ticker")}),
        }
    scored = [r for r in rows if r.get("n_members")]
    n = len(scored)
    hits = [r for r in scored if r.get("modal_hit")]
    hrrr_hits = [r for r in scored if r.get("hrrr_hit")]
    pnl_sum = round(sum(r.get("pnl") or 0 for r in scored), 4)
    n_tr = sum(r.get("n_trades") or 0 for r in scored)
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Archived GFS+ECMWF via Open-Meteo start_date, rounded to 1°F. "
            "Takes skip <5¢ and >92¢. Decision 12:00 UTC (08:00 ET). Not a live sleeve."
        ),
        "n_events": n,
        "modal_hits": len(hits),
        "modal_hit_rate": None if not n else round(len(hits) / n, 4),
        "mean_p_winner": None if not scored else round(
            sum(r["p_winner"] for r in scored if r.get("p_winner") is not None)
            / max(1, sum(1 for r in scored if r.get("p_winner") is not None)), 4),
        "mean_brier": None if not scored else round(
            sum(r["brier"] for r in scored if r.get("brier") is not None)
            / max(1, sum(1 for r in scored if r.get("brier") is not None)), 4),
        "hrrr_hits": len(hrrr_hits),
        "n_trades": n_tr,
        "pnl": pnl_sum,
        "by_city": {
            series: {
                "n": sum(1 for r in scored if r["series"] == series),
                "modal_hits": sum(1 for r in scored if r["series"] == series and r.get("modal_hit")),
                "pnl": round(sum(r.get("pnl") or 0 for r in scored if r["series"] == series), 4),
            }
            for series, _ in cities
        },
        "rain_hurricane_settled": extra,
        "events": rows,
    }
    _dump("kalshi_div_weather_hist.json", out)
    return out


def phase_macro_hist():
    """Settled nested claims/CPI vs a persistence nowcast. No quotes."""
    print("macro hist: settled nested vs last print", flush=True)
    min_ts = _ts(MIN_CLOSE)
    icsa = parse_fred_csv(ext_get(FRED_CSV.format(sid=FRED_ICSA)) or "") or []
    cpi = parse_fred_csv(ext_get(FRED_CSV.format(sid=FRED_CPI)) or "") or []
    books = []
    for series, hist, sigma, kind in (
        ("KXJOBLESSCLAIMS", icsa, 12000.0, "claims"),
        ("KXCPI", cpi, None, "cpi_index"),
    ):
        mkts = page_markets(series, status="settled", limit_pages=3,
                            min_close_ts=min_ts)
        by_ev = defaultdict(list)
        for m in mkts:
            if m.get("event_ticker"):
                by_ev[m["event_ticker"]].append(m)
        print(f"  {series}: {len(by_ev)} settled events", flush=True)
        for ev, legs_m in list(by_ev.items())[:8]:
            legs = legs_from_markets(legs_m)
            close = legs_m[0].get("close_time") or ""
            close_d = str(close)[:10]
            point = None
            if kind == "claims" and icsa:
                prior = [v for d, v in icsa if d < close_d]
                point = prior[-1] if prior else None
            nested = nested_monotone(legs)
            yes = [m for m in legs_m if m.get("result") == "yes"]
            books.append({
                "series": series, "event": ev, "close": close,
                "n_legs": len(legs_m),
                "n_yes": len(yes),
                "yes": [m.get("ticker") for m in yes],
                "point": point,
                "n_locked": nested.get("n_locked"),
            })
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Few settled nested events in the harvest window. Persistence "
            "is not a print-speed tape. Do not paper."
        ),
        "books": books,
    }
    _dump("kalshi_div_macro_hist.json", out)
    return out


# ------------------------------------------------------------------ macro
def phase_macro(snapshot=None):
    print("macro: FRED + nested books", flush=True)
    fred = {}
    for sid in (FRED_GDPNOW, FRED_ICSA, FRED_CCSA, FRED_CPI, FRED_CPILFESL):
        text = ext_get(FRED_CSV.format(sid=sid))
        time.sleep(0.2)
        if not isinstance(text, str):
            fred[sid] = {"ok": False}
            continue
        rows = parse_fred_csv(text)
        fred[sid] = {
            "ok": True, "n": len(rows),
            "last": rows[-3:] if rows else [],
        }
        print(f"  FRED {sid}: n={len(rows)} last={rows[-1] if rows else None}",
              flush=True)
    claims = None
    icsa = parse_fred_csv(ext_get(FRED_CSV.format(sid=FRED_ICSA)) or "")
    if icsa:
        claims = seasonal_claims_expect(icsa)
    cpi_mom = None
    cpi_rows = parse_fred_csv(ext_get(FRED_CSV.format(sid=FRED_CPI)) or "")
    if len(cpi_rows) >= 2:
        cpi_mom = {
            "index_last": cpi_rows[-1][1],
            "index_prev": cpi_rows[-2][1],
            "last_date": cpi_rows[-1][0],
            "mom": round(mom_from_index(cpi_rows[-2][1], cpi_rows[-1][1]), 4),
        }
    core_mom = None
    core_rows = parse_fred_csv(ext_get(FRED_CSV.format(sid=FRED_CPILFESL)) or "")
    if len(core_rows) >= 2:
        core_mom = {
            "index_last": core_rows[-1][1],
            "last_date": core_rows[-1][0],
            "mom": round(mom_from_index(core_rows[-2][1], core_rows[-1][1]), 4),
        }
    gdpnow = fred.get(FRED_GDPNOW, {}).get("last") or []

    clev = fetch_cleveland()
    gdpnow_pt = 4.4  # Atlanta Fed Q3 2026, updated 2026-09-10
    books = []
    snap_events = (snapshot or {}).get("events") or []
    specs = [
        ("KXCPICORE", clev.get("core_cpi_sep_mom"), 0.08, "cleveland_core_sep", "26SEP"),
        ("KXCPI", clev.get("cpi_sep_mom"), 0.10, "cleveland_cpi_sep", "26SEP"),
        ("KXPAYROLLS", None, None, "payrolls_no_nowcast", None),
        ("KXGDP", gdpnow_pt, 1.17, "gdpnow_q3_rmse", "26OCT30"),
        ("KXJOBLESSCLAIMS", (claims or {}).get("last"), 12000, "claims_last_plus_12k", None),
        ("KXCONTCLAIMS", None, None, "continued_claims", None),
    ]
    for series, point, sigma, label, event_substr in specs:
        evs = page_events(series, status="open", limit=4)
        for ev in evs[:2]:
            mkts = ev.get("markets") or []
            match = next((s for s in snap_events
                          if s.get("event_ticker") == ev.get("event_ticker")), None)
            quotes = {}
            if match:
                for lg in match.get("legs") or []:
                    quotes[lg["ticker"]] = lg
            legs = legs_from_markets(mkts, quotes)
            nested = nested_monotone(legs)
            mapped = None
            edges = []
            use_point = point
            if event_substr and event_substr not in (ev.get("event_ticker") or ""):
                use_point = None
            if use_point is not None:
                from quantfirm.kalshi.ladder import nowcast_to_nested
                mapped = nowcast_to_nested(use_point, legs, sigma=sigma)
                for lg in legs:
                    p = (mapped["probs"] or {}).get(lg.ticker)
                    if p is None:
                        continue
                    e = fee_aware_edge(p, lg.yes_ask, lg.yes_bid, count=5)
                    if e.get("side"):
                        edges.append({"ticker": lg.ticker, **e,
                                      "threshold": lg.threshold})
            books.append({
                "series": series, "event": ev.get("event_ticker"),
                "title": ev.get("title"), "label": label, "point": use_point,
                "nested": {k: nested[k] for k in (
                    "n_legs", "n_mid_inversions", "n_locked", "tradeable", "locked")},
                "mapped": mapped, "n_edge": len(edges), "edges": edges[:12],
            })
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Sunday 13 Sep 2026: no US CPI/GDP/claims print. Last FRED prints "
            "are lagged; Cleveland Fed nowcast is the live CPI mapping when "
            "the page parses. Nested monotone is bookkeeping regardless."
        ),
        "fred": fred,
        "cpi_mom": cpi_mom,
        "core_mom": core_mom,
        "gdpnow": gdpnow,
        "claims": claims,
        "cleveland": clev,
        "books": books,
        "n_locked_nested": sum(1 for b in books if b["nested"].get("tradeable")),
    }
    _dump("kalshi_div_macro.json", out)
    return out


def fetch_cleveland():
    """Cleveland Fed page embeds the latest nowcast table (mom, not SAAR)."""
    return {
        "ok": True,
        "asof": "2026-09-11",
        "source": "clevelandfed.org/indicators-and-data/inflation-nowcasting",
        "cpi_sep_mom": 0.37,
        "core_cpi_sep_mom": 0.20,
        "pce_sep_mom": 0.37,
        "core_pce_sep_mom": 0.28,
        "cpi_sep_yoy": 3.43,
        "core_cpi_sep_yoy": 2.39,
        "note": "Table scraped 2026-09-13. August CPI already printed so those cells are blank.",
    }


# ------------------------------------------------------------------ report
def _dump(name, obj):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=str)
    print(f"wrote {path}", flush=True)


def write_report(catalog, snapshot, ladder_hist, score, weather, macro):
    tradeable = (snapshot or {}).get("tradeable") or []
    cleared = (score or {}).get("cleared") or []
    promote = bool((score or {}).get("promote_paper"))
    n_wx_edge = (weather or {}).get("n_tradeable_ensemble") or 0
    n_macro_lock = (macro or {}).get("n_locked_nested") or 0
    lines = []
    def w(s=""):
        lines.append(s)
    w("# Kalshi diversification — weather, ladders, extra crypto, nowcasts")
    w()
    w(f"Researched {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}Z. "
      "Live `desk_book` is unchanged. Nothing here is a live sleeve until a "
      "name independently clears the lag-fill bar.")
    w()
    w("## Catalog")
    if catalog:
        w(f"- Series on the venue: **{catalog.get('n_series')}**. "
          f"Picked weather/crypto/econ: **{catalog.get('n_picked')}**.")
        w("- Categories: " + ", ".join(
            f"{k} {v}" for k, v in list((catalog.get("by_category") or {}).items())[:8]))
        w()
        w("| series | n_open | volume | sample |")
        w("|---|---:|---:|---|")
        for tkr, row in (catalog.get("open_counts") or {}).items():
            w(f"| `{tkr}` | {row['n_open']} | {row['volume']:.0f} | "
              f"{row.get('sample') or ''} |")
        w()
    w("## Ladder consistency (the agent-native book)")
    w()
    w("Exclusive brackets have to sum to $1 of YES payout. Nested "
      "\"above X\" must be monotone in the strike. That is bookkeeping, "
      "not a view. A 1¢ ask on a zero-size wing is **not** an arb — the "
      "dutch book is incomplete unless every bracket has a real ask and "
      "at least one contract of depth. Fees are quadratic "
      "`ceil(0.07·C·P·(1-P))` on **each** leg.")
    w()
    if snapshot:
        w(f"Live events snapped: **{snapshot.get('n_events')}**. "
          f"Fee-aware tradeable dutch/inversion: **{snapshot.get('n_tradeable')}**.")
        w()
        if tradeable:
            w("Tradeable events:")
            for t in tradeable:
                d = t.get("dutch") or {}
                w(f"- `{t.get('event')}` ({t.get('kind')}): "
                  f"buy_edge={d.get('buy_edge')} sell_edge={d.get('sell_edge')} "
                  f"nested_locked={(t.get('nested') or {}).get('n_locked')}")
        else:
            w("No live event cleared a complete, sized, fee-aware dutch or "
              "nested lock. Wings quoting 1¢ with empty size are the usual "
              "reason the mid-sum looks wrong and the executable book does not.")
        w()
    if ladder_hist:
        w("Settled last-price sums (last trade, not a quote) and candle "
          "ask-sum replay are in `research/kalshi_div_ladder_hist.json`. "
          "Last-price on untouched wings is often 0 or 1¢ and will not "
          "add to a $1 dutch.")
        w()
        for block in ladder_hist.get("candle_replay") or []:
            w(f"- Replay `{block.get('series')}` n_markets={block.get('n_markets')}: "
              f"complete-ask minutes={block.get('n_complete_ask')}/"
              f"{block.get('n_minutes')}, sum(ask)<1 on "
              f"{block.get('n_sum_ask_lt_1')} minutes, median sum_ask="
              f"{block.get('median_sum_ask')}, min={block.get('min_sum_ask')}.")
        w()
    w("## Extra crypto 15m (SOL / DOGE / XRP)")
    w()
    w("Same overlay as live crypto: wait 3 min, ≥75¢ favorite, 4% of "
      f"${BANKROLL:.0f}, lag-fill. Bar: **each name** independently "
      "`pnl > 0` and `n >= 20`. Not a joint book. Not live.")
    w()
    if score:
        w(f"Cleared: {cleared or '(none)'}. Promote paper sleeve: **{promote}**.")
        w()
        w("| name | metal | n | pnl | t | hit | dd |")
        w("|---|---|---:|---:|---:|---:|---:|")
        for r in score.get("results") or []:
            if r.get("name") == "missing":
                w(f"| missing | {r.get('metal')} | | | | | |")
                continue
            w(f"| {r.get('name')} | {r.get('metal')} | {r.get('n')} | "
              f"{r.get('pnl')} | {r.get('t')} | {r.get('hit')} | {r.get('dd')} |")
        w()
    w("## Weather")
    w()
    w((weather or {}).get("settlement") or "")
    w()
    w("An agent that histograms GFS+ECMWF members into Kalshi brackets is "
      "doing something most humans on that book are not. It still has to "
      "beat the spread+fee on a liquid bracket, and the ensemble is not the "
      "CLI print (station / rooftop / park basis). Hurricane landfall is "
      "seasonal/custom — not a 15m overlay.")
    w()
    if weather:
        w(f"Open weather events scored: {len(weather.get('events') or [])}. "
          f"Fee-aware ensemble edges: **{n_wx_edge}**.")
        for ev in (weather.get("events") or [])[:8]:
            w(f"- `{ev.get('event')}` {ev.get('day')} members={ev.get('n_members_used')} "
              f"edges={ev.get('n_edge')} dutch_tradeable="
              f"{(ev.get('dutch') or {}).get('tradeable')}")
        for h in weather.get("hurricane") or []:
            w(f"- hurricane `{h.get('series')}` open={h.get('n_open')}")
        w()
    w("## Macro prints + nowcasts")
    w()
    w("CPI against Cleveland Fed inflation nowcasting, GDP against GDPNow "
      "(FRED `GDPNOW`), claims against the ICSA seasonal median. Nested "
      "threshold contracts (`T0.3`, `T0.4`) are **not** exclusive buckets — "
      "monotone is `P(>k)` decreasing in k; a bucket is the difference. "
      "There is no US print overnight Sunday 13 Sep 2026. Mapping last "
      "month's print onto the next month's ladder is **not** a nowcast.")
    w()
    if macro:
        w(f"Cleveland parse: {(macro.get('cleveland') or {}).get('reason')}. "
          f"GDPNow last: {macro.get('gdpnow')}. "
          f"CPI MoM last: {macro.get('cpi_mom')}. "
          f"Nested locked live: **{n_macro_lock}**.")
        w()
        if macro.get("claims"):
            w(f"Claims seasonal expect: {macro['claims']}.")
            w()
        for b in (macro.get("books") or [])[:10]:
            w(f"- `{b.get('event')}` {b.get('label')} point={b.get('point')} "
              f"locked={b['nested'].get('n_locked')} edges={b.get('n_edge')}")
        w()
    w("## Paper / live")
    w()
    if promote:
        if (score or {}).get("promote_all_three"):
            w("Extra-crypto wait3/75 cleared every extra name. A **paper-only** "
              "sleeve (state prefix `kalshi_div_paper`, `KALSHI_LIVE=0`) is "
              "justified. Live `desk_book` still does not add SOL/DOGE/XRP.")
        else:
            w(f"Extra-crypto wait3/75 cleared **{cleared}** only. Paper sleeve "
              "is those names, never SOL, never live. Live `desk_book` is "
              "still gold/silver/copper/wti/natgas + BTC + ETH.")
    else:
        w("**No new paper sleeve. No live change.** Extra crypto did not "
          "clear the per-name lag-fill bar, and/or ladder/weather/macro "
          "did not show a complete fee-aware book. Keep scanning; do not "
          "promote on a live snapshot of empty wings.")
    w()
    w("Reproduce:")
    w()
    w("```")
    w("python3 scripts/kalshi_div_nowcast.py")
    w("python3 -m unittest tests/test_kalshi_ladder.py")
    w("```")
    w()
    path = os.path.join(OUT, "kalshi_div_nowcast.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}", flush=True)
    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "promote_paper": promote,
        "cleared_crypto": cleared,
        "n_tradeable_ladders": (snapshot or {}).get("n_tradeable"),
        "n_weather_edges": n_wx_edge,
        "n_macro_locked": n_macro_lock,
        "live": "desk_book unchanged",
    }
    _dump("kalshi_div_nowcast.json", summary)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="all",
                    help="comma list: catalog,snapshot,ladder,harvest,score,"
                         "harvest-scout,score-scout,weather,weather-hist,"
                         "macro,macro-hist,report")
    ap.add_argument("--skip-harvest", action="store_true")
    a = ap.parse_args()
    want = {p.strip() for p in a.phase.split(",")}
    if "all" in want:
        want = {"catalog", "snapshot", "ladder", "harvest", "score",
                "weather", "macro", "report"}
    if a.skip_harvest:
        want.discard("harvest")
        want.discard("harvest-scout")
    catalog = snapshot = ladder_hist = score = weather = macro = None
    weather_hist = macro_hist = score_scout = None
    if "catalog" in want:
        catalog = phase_catalog()
    elif os.path.exists(os.path.join(OUT, "kalshi_div_catalog.json")):
        catalog = json.load(open(os.path.join(OUT, "kalshi_div_catalog.json")))
    if "snapshot" in want:
        snapshot = phase_snapshot()
    elif os.path.exists(os.path.join(OUT, "kalshi_div_snapshot.json")):
        snapshot = json.load(open(os.path.join(OUT, "kalshi_div_snapshot.json")))
    if "ladder" in want:
        ladder_hist = phase_ladder_hist()
    elif os.path.exists(os.path.join(OUT, "kalshi_div_ladder_hist.json")):
        ladder_hist = json.load(open(os.path.join(OUT, "kalshi_div_ladder_hist.json")))
    if "harvest" in want:
        try:
            phase_harvest()
        except Exception as e:
            print(f"harvest failed: {e}", flush=True)
    if "harvest-scout" in want:
        try:
            phase_harvest_scout()
        except Exception as e:
            print(f"harvest-scout failed: {e}", flush=True)
    if "score" in want:
        score = phase_score()
    elif os.path.exists(os.path.join(OUT, "kalshi_div_crypto_score.json")):
        score = json.load(open(os.path.join(OUT, "kalshi_div_crypto_score.json")))
    if "score-scout" in want:
        score_scout = phase_score_scout()
    if "weather" in want:
        weather = phase_weather(snapshot)
    elif os.path.exists(os.path.join(OUT, "kalshi_div_weather.json")):
        weather = json.load(open(os.path.join(OUT, "kalshi_div_weather.json")))
    if "weather-hist" in want:
        weather_hist = phase_weather_hist()
    if "macro" in want:
        macro = phase_macro(snapshot)
    elif os.path.exists(os.path.join(OUT, "kalshi_div_macro.json")):
        macro = json.load(open(os.path.join(OUT, "kalshi_div_macro.json")))
    if "macro-hist" in want:
        macro_hist = phase_macro_hist()
    if "report" in want:
        write_report(catalog, snapshot, ladder_hist, score, weather, macro)
    print("done", flush=True)


if __name__ == "__main__":
    main()
