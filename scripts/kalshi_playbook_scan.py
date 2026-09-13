#!/usr/bin/env python3
"""Score the Sep 2026 playbook ideas on our 1-min lag-fill harvest.

Does not change live desk_book. 2-10s imbalance / BTC-bleed and Kalshi
perps are not in this tape (REST + 1-min candles). Pair-arb as a taker
is yes_ask + (1-yes_bid) = 1 + spread, so it only exists on a crossed book.

Reproduce: python3 scripts/kalshi_playbook_scan.py
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, ".")

from quantfirm.kalshi.backtest import Backtest, taker_fee
from quantfirm.kalshi.universe import BANKROLL, SPLIT_TS

SINCE_7D = int(datetime(2026, 9, 5, tzinfo=timezone.utc).timestamp())
STAKE = 0.04
MIN_COUNT = 4
OUT = os.path.join("research", "kalshi_playbook.json")


def _lag(side: str, lim: float, c_next: dict) -> float | None:
    if not c_next:
        return None
    if side == "yes":
        px_high, px_close = c_next.get("ask_high"), c_next.get("ask_close")
    else:
        bl, bc = c_next.get("bid_low"), c_next.get("bid_close")
        px_high = (1.0 - bl) if bl is not None else None
        px_close = (1.0 - bc) if bc is not None else None
    if px_high is not None and px_high > lim + 1e-9:
        return None
    if px_close is None or px_close > lim + 1e-9:
        return None
    return float(px_close)


def _size(cost: float, bankroll: float) -> int:
    if cost <= 0 or cost >= 1:
        return 0
    cap = STAKE * bankroll
    count = int(cap / cost)
    while count >= MIN_COUNT and count * cost + taker_fee(count, cost) > cap + 1e-9:
        count -= 1
    return count if count >= MIN_COUNT else 0


def _pnl(side: str, fill: float, count: int, result: str) -> float:
    win = (result == "yes" and side == "yes") or (result == "no" and side == "no")
    return count * ((1.0 if win else 0.0) - fill) - taker_fee(count, fill)


def _summ(rows: list[dict], split: str, start: int | None, end: int | None) -> dict:
    xs = [r for r in rows if (start is None or r["ts"] >= start)
          and (end is None or r["ts"] < end)]
    n = len(xs)
    pnl = sum(r["pnl"] for r in xs)
    hits = sum(1 for r in xs if r["pnl"] > 0)
    by = defaultdict(float)
    n_by = defaultdict(int)
    for r in xs:
        by[r["metal"]] += r["pnl"]
        n_by[r["metal"]] += 1
    t_stat = 0.0
    if n > 1:
        mu = pnl / n
        sd = (sum((r["pnl"] - mu) ** 2 for r in xs) / (n - 1)) ** 0.5
        t_stat = mu / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {
        "split": split, "n": n, "pnl": round(pnl, 2),
        "hit": round(hits / n, 3) if n else None,
        "t": round(t_stat, 2),
        "btc": round(by.get("btc", 0.0), 2),
        "eth": round(by.get("eth", 0.0), 2),
        "cmdty": round(sum(v for k, v in by.items() if k not in ("btc", "eth")), 2),
        "n_btc": n_by.get("btc", 0), "n_eth": n_by.get("eth", 0),
        "both": bool(n_by.get("btc") and n_by.get("eth")
                     and by.get("btc", 0) > 0 and by.get("eth", 0) > 0),
    }


def _splits(rows: list[dict]) -> dict:
    return {
        "train": _summ(rows, "train", None, SPLIT_TS),
        "test": _summ(rows, "test", SPLIT_TS, None),
        "last7d": _summ(rows, "last7d", SINCE_7D, None),
    }


def main() -> None:
    bt = Backtest("data/kalshi", bankroll=BANKROLL)
    pair = {"minutes": 0, "empty": 0, "crossed": 0, "sum_lt_1": 0,
             "sum_lt_0_99": 0, "min_sum": None, "examples": []}
    panic_yes: list[dict] = []
    fade_97: list[dict] = []
    btc_lead: list[dict] = []
    taken = defaultdict(set)  # spec -> tickers already filled this window

    for series, metal in bt.series.items():
        for m in bt.markets[series]:
            tkr = m["ticker"]
            cnds = bt.candles.get(series, {}).get(tkr, {})
            bars = bt.bars[metal]
            f_open = bars.get(m["open_ts"])
            for ts in range(m["open_ts"] + 60, m["close_ts"], 60):
                c = cnds.get(ts)
                if not c or c.get("bid_close") is None or c.get("ask_close") is None:
                    continue
                bid, ask = c["bid_close"], c["ask_close"]
                pair["minutes"] += 1
                if bid <= 0.0 and ask >= 0.99:
                    pair["empty"] += 1
                    continue
                taker_sum = ask + (1.0 - bid)
                if pair["min_sum"] is None or taker_sum < pair["min_sum"]:
                    pair["min_sum"] = round(taker_sum, 4)
                if ask + 1e-9 < bid:
                    pair["crossed"] += 1
                    if len(pair["examples"]) < 8:
                        pair["examples"].append(
                            {"ticker": tkr, "ts": ts, "bid": bid, "ask": ask})
                if taker_sum < 1.0:
                    pair["sum_lt_1"] += 1
                if taker_sum < 0.99:
                    pair["sum_lt_0_99"] += 1

                tau = m["close_ts"] - ts
                c_next = cnds.get(ts + 60)
                c_prev = cnds.get(ts - 180)
                mid = (bid + ask) / 2
                mkt_move = 0.0
                if (c_prev and c_prev.get("bid_close") is not None
                        and c_prev.get("ask_close") is not None):
                    mid_prev = (c_prev["bid_close"] + c_prev["ask_close"]) / 2
                    mkt_move = mid - mid_prev

                # Turbine-style: YES dumped ≥15¢ over 3 min, still 15-55¢.
                if (180 <= tau <= 720 and tkr not in taken["panic_yes"]
                        and mkt_move <= -0.15 and 0.15 <= ask <= 0.55):
                    fill = _lag("yes", ask, c_next)
                    count = _size(ask, BANKROLL)
                    if fill is not None and count:
                        panic_yes.append({
                            "ts": ts, "metal": metal, "ticker": tkr,
                            "pnl": _pnl("yes", fill, count, m["result"]),
                            "fill": fill, "result": m["result"]})
                        taken["panic_yes"].add(tkr)

                # End-window 97¢+ favorite while spot still near strike.
                f_now = bars.get(ts)
                atm = False
                if f_now is not None and f_open:
                    s_now = f_now * (m["strike"] / f_open)
                    atm = abs(s_now / m["strike"] - 1.0) < 0.0004
                fav_ask = ask if ask >= (1.0 - bid) else (1.0 - bid)
                fade_side = "no" if ask >= (1.0 - bid) else "yes"
                fade_lim = (1.0 - bid) if fade_side == "no" else ask
                if (60 <= tau <= 300 and tkr not in taken["fade_97"]
                        and fav_ask >= 0.97 and atm):
                    fill = _lag(fade_side, fade_lim, c_next)
                    count = _size(fade_lim, BANKROLL)
                    if fill is not None and count:
                        fade_97.append({
                            "ts": ts, "metal": metal, "ticker": tkr,
                            "pnl": _pnl(fade_side, fill, count, m["result"]),
                            "fill": fill, "result": m["result"]})
                        taken["fade_97"].add(tkr)

            # BTC-lead: 1-min BTC mid jump, take ETH same side next minute.
            if metal != "eth":
                continue
            other = "KXBTC15M"
            for om in bt.markets.get(other, ()):
                if om["open_ts"] != m["open_ts"]:
                    continue
                ocnds = bt.candles.get(other, {}).get(om["ticker"], {})
                for ts in range(m["open_ts"] + 120, m["close_ts"], 60):
                    if m["ticker"] in taken["btc_lead"]:
                        break
                    tau = m["close_ts"] - ts
                    if not (180 <= tau <= 720):
                        continue
                    bc = ocnds.get(ts - 60)
                    bc0 = ocnds.get(ts - 120)
                    ec = cnds.get(ts)
                    if not (bc and bc0 and ec):
                        continue
                    if None in (bc.get("bid_close"), bc.get("ask_close"),
                                bc0.get("bid_close"), bc0.get("ask_close"),
                                ec.get("bid_close"), ec.get("ask_close")):
                        continue
                    bmid = (bc["bid_close"] + bc["ask_close"]) / 2
                    bmid0 = (bc0["bid_close"] + bc0["ask_close"]) / 2
                    jump = bmid - bmid0
                    if abs(jump) < 0.08:
                        continue
                    side = "yes" if jump > 0 else "no"
                    ebid, eask = ec["bid_close"], ec["ask_close"]
                    cost = eask if side == "yes" else (1.0 - ebid)
                    if not (0.55 <= cost <= 0.94):
                        continue
                    fill = _lag(side, cost, cnds.get(ts + 60))
                    count = _size(cost, BANKROLL)
                    if fill is None or not count:
                        continue
                    btc_lead.append({
                        "ts": ts, "metal": "eth", "ticker": m["ticker"],
                        "pnl": _pnl(side, fill, count, m["result"]),
                        "fill": fill, "result": m["result"], "jump": round(jump, 3)})
                    taken["btc_lead"].add(m["ticker"])
                    break

    report = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "lag-fill, $250, 4% cap, first fill per window. Not live.",
        "pair_arb": pair,
        "panic_yes": _splits(panic_yes),
        "fade_97_atm": _splits(fade_97),
        "btc_lead_eth_1m": _splits(btc_lead),
    }
    os.makedirs("research", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
