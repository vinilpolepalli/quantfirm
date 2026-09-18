#!/usr/bin/env python3
"""Paper tick for the OSS-clone Kalshi sleeve. No orders. Ever.

Marks a $257 counterfactual book (the Kalshi deposit) using the improved
FLB taker from research/kalshi_oss_skills.md. The cash stays in the
account. Incentive shadow and 15m desk_book are separate books.

    python3 scripts/kalshi_oss_paper.py
    python3 scripts/kalshi_oss_paper.py --capital 257

``--live`` is accepted only so we can refuse it in one place.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.oss_paper import (
    BANKROLL, WEATHER_SERIES, apply_settlements, flb_stats, intents_from_event,
    load_state, maybe_kill, open_positions, refuse_live, save_state,
    select_intents,
)

BASE = "https://api.elections.kalshi.com/trade-api/v2"
S = requests.Session()
S.headers["User-Agent"] = "quantfirm-research/0.1 (kalshi-oss-paper)"


def get(path, params=None, tries=5):
    for i in range(tries):
        try:
            r = S.get(BASE + path, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.8 * 2 ** i)
                continue
            return None
        except requests.RequestException:
            time.sleep(0.8 * 2 ** i)
    return None


def page_open(series, limit_pages=2):
    rows, cursor, pages = [], None, 0
    while pages < limit_pages:
        params = {"series_ticker": series, "status": "open", "limit": 200}
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
        time.sleep(0.05)
    return rows


def markets_by_event(series_list):
    by_ev = defaultdict(list)
    for series in series_list:
        for m in page_open(series):
            ev = m.get("event_ticker")
            if ev:
                by_ev[ev].append(m)
        time.sleep(0.06)
    return by_ev


def fetch_results(tickers):
    out = {}
    for tkr in tickers:
        d = get(f"/markets/{tkr}")
        time.sleep(0.05)
        m = (d or {}).get("market") or d or {}
        res = (m.get("result") or "").lower()
        if res in ("yes", "no"):
            out[tkr] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=BANKROLL)
    ap.add_argument("--state", default=os.path.join(REPO, "state", "kalshi_oss_paper.json"))
    ap.add_argument("--live", action="store_true",
                    help="refused. Present so a copied live flag dies here.")
    ap.add_argument("--series", default=",".join(WEATHER_SERIES))
    args = ap.parse_args()
    refuse_live(args.live)

    st = load_state(args.state, capital=args.capital)
    st["capital"] = args.capital
    st["live"] = False
    now = datetime.now(timezone.utc)

    # 1. settle anything the venue has resolved
    open_tk = [p["ticker"] for p in st.get("positions") or []]
    settled = []
    if open_tk:
        settled = apply_settlements(st, fetch_results(open_tk))

    # 2. scan weather books, paper-take executable FLB
    by_ev = markets_by_event([s.strip() for s in args.series.split(",") if s.strip()])
    candidates, dutch_hits, watches = [], [], []
    books = []
    for ev, mkts in sorted(by_ev.items()):
        flb, meta = intents_from_event(ev, mkts)
        candidates.extend(flb)
        watches.extend(meta.get("maker_watch") or [])
        if meta.get("dutch"):
            dutch_hits.append(meta["dutch"])
        books.append({"event": ev, "n_legs": meta["n_legs"],
                      "sum_ask": meta.get("sum_ask"), "n_flb": len(flb)})

    take, skip = select_intents(candidates, st, args.capital)
    opened = open_positions(st, take)

    st["ticks"] = int(st.get("ticks") or 0) + 1
    st["last_tick"] = now.isoformat()
    st["skipped"] = (st.get("skipped") or [])[-200:] + skip
    st["maker_watch"] = watches[:40]
    st["dutch_watch"] = dutch_hits
    maybe_kill(st)
    stats = flb_stats(st.get("settled") or [])
    st["history"] = (st.get("history") or [])[-200:] + [{
        "t": now.isoformat(),
        "opened": len(opened),
        "settled": len(settled),
        "open": len(st.get("positions") or []),
        "cash": st["cash"],
        "n_flb_seen": len(candidates),
        "n_books": len(books),
    }]
    save_state(st, args.state)

    lines = [
        f"Kalshi OSS paper sleeve — ${args.capital:,.0f} notional, PAPER ONLY",
        f"tick {st['ticks']}  ·  {now.strftime('%Y-%m-%d %H:%M')}Z",
        "",
        f"  cash                 ${st['cash']:.2f}",
        f"  open positions       {len(st.get('positions') or [])}",
        f"  opened this tick     {len(opened)}",
        f"  settled this tick    {len(settled)}",
        f"  flb candidates       {len(candidates)}  (took {len(take)}, sat {len(skip)})",
        f"  dutch tradeable      {len(dutch_hits)}",
        f"  weather events       {len(books)}",
        "",
        f"  settled fades n={stats['n']}  pnl=${stats['pnl']:.2f}  "
        f"hits={stats['hits']}  hit_rate={stats['hit_rate']}",
        f"  VERDICT: {st['verdict']} — {st['verdict_reason']}",
        "",
        "The $257 deposit is NOT deployed. No credentials used. No orders.",
        "15m desk_book and the incentive shadow book are unchanged.",
    ]
    if opened:
        lines.append("")
        for p in opened:
            lines.append(f"  OPEN  {p['ticker']}  NO@{p['px']:.2f}  ask={p['yes_ask']}")
    if settled:
        lines.append("")
        for t in settled:
            lines.append(f"  SETTLE {t['ticker']}  result={t['result']}  pnl={t['pnl']:+.2f}")
    digest = "\n".join(lines)
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
