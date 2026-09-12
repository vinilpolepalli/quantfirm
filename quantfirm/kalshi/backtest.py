"""Event-driven backtest for the 15M metals desk.

Data:
  * settled markets (JSONL from /markets): strike K, open/close ts, result
  * per-market 1-min contract candles: yes_bid / yes_ask OHLC
  * underlying 1-min futures bars (GC=F / SI=F / HG=F via Yahoo)

Causality contract (the whole point of this file):
  * The vol EWMA and diurnal profile see bars strictly before the decision.
  * A decision at minute-boundary T uses: underlying bar closing at T, the
    contract candle covering (T-60, T] (its close = the resting quote at T),
    and the strike K (public at window open).
  * The fill is NOT the decision quote: we send a limit at the decision-time
    touch, and it fills only if the NEXT candle's side-price OPEN is at or
    inside our limit — paying that open. If the book gapped away, no fill.
  * Positions are held to settlement (result field); cash is credited
    settle_lag_s after window close (Kalshi settles ~5-8 min later).
  * Basis: within a window, S_t = F_t * (K / F_open) — the futures path is
    re-anchored to the settlement index at every window open, so the only
    basis error is intra-window drift (~1-2 bp over <=15 min).

Fills, fees and delays here are deliberately conservative, but a 1-minute
grid cannot see sub-minute sniping competition: treat backtest results as an
UPPER BOUND and confirm live in shadow mode before believing them.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .fair import VolEstimator, taker_fee
from .strategy import Intent, Params, decide
from .universe import LIVE_SERIES as METALS, BANKROLL
TICK_BODY = 0.01
SETTLE_LAG_S = 300


def _ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def _open(path: str):
    """Open path or path.gz, whichever exists, as text."""
    if os.path.exists(path):
        return open(path)
    if os.path.exists(path + ".gz"):
        return gzip.open(path + ".gz", "rt")
    raise FileNotFoundError(path)


def _exists(path: str) -> bool:
    return os.path.exists(path) or os.path.exists(path + ".gz")


# --------------------------------------------------------------------- load
def _num(v):
    """Parse Kalshi numeric fields; some expiration_value strings use commas."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(",", "").replace("_", "").strip())


def load_markets(path: str) -> list[dict]:
    out = []
    with _open(path) as f:
        for line in f:
            m = json.loads(line)
            if m.get("floor_strike") is None or m.get("result") not in ("yes", "no"):
                continue
            out.append({
                "ticker": m["ticker"],
                "open_ts": _ts(m["open_time"]),
                "close_ts": _ts(m["close_time"]),
                "strike": _num(m["floor_strike"]),
                "result": m["result"],
                "settle_value": _num(m.get("expiration_value")),
            })
    return out


def load_candles(path: str) -> dict[str, dict[int, dict]]:
    """{ticker: {end_period_ts: candle}} with float fields."""
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    with _open(path) as f:
        for row in csv.DictReader(f):
            try:
                ts = int(row["end_period_ts"])
            except (ValueError, TypeError):
                continue

            def g(k):
                v = row.get(k)
                return float(v) if v not in (None, "") else None

            out[row["market_ticker"]][ts] = {
                "bid_open": g("yes_bid_open"), "bid_high": g("yes_bid_high"),
                "bid_low": g("yes_bid_low"), "bid_close": g("yes_bid_close"),
                "ask_open": g("yes_ask_open"), "ask_high": g("yes_ask_high"),
                "ask_low": g("yes_ask_low"), "ask_close": g("yes_ask_close"),
                # last-TRADE price OHLC — the only evidence of a real print,
                # and therefore the only honest basis for a maker fill test
                "px_open": g("price_open"), "px_high": g("price_high"),
                "px_low": g("price_low"), "px_close": g("price_close"),
                "volume": g("volume"),
            }
    return dict(out)


def load_underlying(path: str) -> dict[int, float]:
    """{bar_close_ts: close} from a yfinance CSV (index = bar start)."""
    import pandas as pd
    if not os.path.exists(path) and os.path.exists(path + ".gz"):
        path = path + ".gz"
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    closes = df["close"].dropna()
    return {int(ts.timestamp()) + 60: float(v) for ts, v in closes.items()}


# ------------------------------------------------------------------- engine
@dataclass
class Trade:
    ticker: str
    metal: str
    entry_ts: int
    side: str
    count: int
    fill_price: float
    fee: float
    fair: float
    edge_at_decision: float
    tag: str
    tau_s: float
    contested: bool = False
    result: str | None = None
    pnl: float | None = None
    settle_ts: int | None = None


class Backtest:
    def __init__(self, data_dir: str, bankroll: float = BANKROLL, series: dict | None = None):
        self.data_dir = data_dir
        self.bankroll0 = bankroll
        self.markets: dict[str, list[dict]] = {}
        self.candles: dict[str, dict[str, dict[int, dict]]] = {}
        self.bars: dict[str, dict[int, float]] = {}
        wanted = series or METALS
        for series_ticker, metal in wanted.items():
            mp = os.path.join(data_dir, f"markets_{series_ticker}.jsonl")
            cp = os.path.join(data_dir, f"candles_{series_ticker}.csv")
            bp = os.path.join(data_dir, f"yf_{metal}_1m.csv")
            if all(_exists(p) for p in (mp, cp, bp)):
                self.markets[series_ticker] = load_markets(mp)
                self.candles[series_ticker] = load_candles(cp)
                self.bars[metal] = load_underlying(bp)

    def run(self, params: Params, start_ts: int | None = None,
            end_ts: int | None = None, decide_fn=None) -> dict:
        decide_fn = decide_fn or decide
        events: list[tuple] = []
        # underlying bars drive the vol clock
        for metal, bars in self.bars.items():
            prev = None
            for ts in sorted(bars):
                if prev is not None and 0 < ts - prev[0] <= 120:
                    lr = math.log(bars[ts] / prev[1])
                    events.append((ts, 0, "bar", metal, lr))
                prev = (ts, bars[ts])
        # decision + settle events per market
        for series, mkts in self.markets.items():
            metal = METALS[series]
            for m in mkts:
                if start_ts and m["close_ts"] < start_ts:
                    continue
                if end_ts and m["close_ts"] >= end_ts:  # windows partition [start,end)
                    continue
                o, c = m["open_ts"], m["close_ts"]
                for T in range(o + 60, c, 60):
                    tau = c - T
                    if params.tau_min_s <= tau <= params.tau_max_s:
                        events.append((T, 1, "decide", series, m))
                events.append((c + SETTLE_LAG_S, 2, "settle", series, m))
        events.sort(key=lambda e: (e[0], e[1]))

        vol = {metal: VolEstimator(halflife_min=params.vol_halflife_min,
                                   diurnal=params.diurnal)
               for metal in self.bars}
        cash = self.bankroll0
        open_pos: dict[str, Trade] = {}
        trades: list[Trade] = []
        daily_pnl: dict[str, float] = defaultdict(float)
        day_start_equity: dict[str, float] = {}
        equity_curve: list[tuple[int, float]] = []
        skipped = defaultdict(int)

        def day(ts):
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

        for ev in events:
            ts, _, kind = ev[0], ev[1], ev[2]
            if kind == "bar":
                _, _, _, metal, lr = ev
                vol[metal].update(ts, lr)
                continue

            if kind == "settle":
                _, _, _, series, m = ev
                tr = open_pos.pop(m["ticker"], None)
                if tr is None:
                    continue
                win = (tr.side == "yes") == (m["result"] == "yes")
                payout = tr.count * (1.0 if win else 0.0)
                cash += payout
                tr.result = m["result"]
                tr.pnl = payout - tr.count * tr.fill_price - tr.fee
                tr.settle_ts = ts
                daily_pnl[day(ts)] += tr.pnl
                equity_curve.append((ts, cash + sum(
                    p.count * p.fill_price for p in open_pos.values())))
                continue

            # ---- decide
            _, _, _, series, m = ev
            metal = METALS[series]
            tkr = m["ticker"]
            if tkr in open_pos:
                continue
            if len(open_pos) >= params.max_open:
                skipped["concurrency"] += 1
                continue
            d = day(ts)
            if d not in day_start_equity:
                day_start_equity[d] = cash + sum(
                    p.count * p.fill_price for p in open_pos.values())
            if daily_pnl[d] <= -params.daily_stop_frac * day_start_equity[d]:
                skipped["daily_stop"] += 1
                continue

            bars = self.bars[metal]
            f_now, f_open = bars.get(ts), bars.get(m["open_ts"])
            if f_now is None or f_open is None:
                skipped["no_underlying"] += 1
                continue
            s_now = f_now * (m["strike"] / f_open)

            cnds = self.candles.get(series, {}).get(tkr, {})
            c_now = cnds.get(ts)
            if not c_now or c_now["bid_close"] is None or c_now["ask_close"] is None:
                skipped["no_quote"] += 1
                continue
            bid, ask = c_now["bid_close"], c_now["ask_close"]
            if bid <= 0.0 and ask >= 1.0:
                skipped["empty_book"] += 1
                continue

            recent_vol = sum((cnds.get(ts - 60 * j, {}) or {}).get("volume") or 0.0
                             for j in range(3))
            # 3-min lookback: how much did the contract move vs the model fair?
            mkt_move = fair_move = 0.0
            c_prev = cnds.get(ts - 180)
            f_prev = bars.get(ts - 180)
            if (c_prev and c_prev["bid_close"] is not None
                    and c_prev["ask_close"] is not None and f_prev is not None):
                mid_now = (bid + ask) / 2
                mid_prev = (c_prev["bid_close"] + c_prev["ask_close"]) / 2
                mkt_move = mid_now - mid_prev
                from .fair import fair_yes as _fy
                sig = vol[metal].sigma_1m(ts)
                s_prev = f_prev * (m["strike"] / f_open)
                fair_move = (_fy(s_now, m["strike"], sig, (m["close_ts"] - ts) / 60.0)
                             - _fy(s_prev, m["strike"], sig,
                                   (m["close_ts"] - ts + 180) / 60.0))
            # correlated-direction gate: gold+silver same direction share a slot
            intent = decide_fn(
                ticker=tkr, ts=ts, s=s_now, k=m["strike"],
                sigma_1m=vol[metal].sigma_1m(ts), close_ts=m["close_ts"],
                yes_bid=bid, yes_ask=ask, bankroll=cash,
                open_positions=len(open_pos), params=params,
                recent_volume=recent_vol,
                recent_fair_move=fair_move, recent_mkt_move=mkt_move,
                f_now=f_now, f_open=f_open, open_ts=m["open_ts"],
                metal=metal)
            if intent is None:
                continue
            from .halt import blocked_by_corr
            if blocked_by_corr(metal, intent.side, open_pos.values()):
                skipped["corr_cap"] += 1
                continue

            # ---- fill model. The fill candle covers (T, T+60]; its side-price
            # OPEN is a carry-forward of the decision-minute close (verified
            # ~97-99% identical), so "touch" mode is a ZERO-LATENCY CEILING,
            # not a conservative bound. "lag" mode is the realistic floor: a
            # slow taker (arriving within 60s) only wins fills the fast bots
            # left behind — i.e. levels that survived the whole fill minute
            # (uncontested) — and pays that minute's side-price close, capped
            # at the minute's traded volume. "contested" fills (level breached
            # mid-minute) are exactly where the race lives; a latency-bound
            # taker misses them, so lag mode skips them (raced_out).
            c_next = cnds.get(ts + 60)
            if not c_next:
                skipped["no_fill_candle"] += 1
                continue
            lim = intent.limit_price
            if intent.side == "yes":
                px_open, px_high, px_close = (c_next["ask_open"],
                                              c_next["ask_high"], c_next["ask_close"])
                contested = px_high is not None and px_high > lim + 1e-9
            else:
                # NO leg: we pay 1 - yes_bid; "worse for us" = yes_bid LOWER,
                # so the contested test is on bid_low.
                bo, bl, bc = c_next["bid_open"], c_next["bid_low"], c_next["bid_close"]
                px_open = (1.0 - bo) if bo is not None else None
                px_high = (1.0 - bl) if bl is not None else None  # our worst price
                px_close = (1.0 - bc) if bc is not None else None
                contested = px_high is not None and px_high > lim + 1e-9

            count = intent.count
            if params.fill_mode == "lag":
                if contested:
                    skipped["raced_out"] += 1
                    continue
                if px_close is None or px_close > lim + 1e-9:
                    skipped["gapped_away"] += 1
                    continue
                fill = px_close
                cap = int(recent_vol)  # depth proxy: minute's traded volume
                if cap < params.min_count:
                    skipped["thin_depth"] += 1
                    continue
                count = min(count, cap)
            else:  # "touch"
                if px_open is None or px_open > lim + 1e-9:
                    skipped["gapped_away"] += 1
                    continue
                fill = min(px_open, lim)
            fill += params.slippage_extra
            cost = count * fill
            fee = taker_fee(count, fill)
            if cost + fee > cash:
                skipped["no_cash"] += 1
                continue
            cash -= cost + fee
            tr = Trade(ticker=tkr, metal=metal, entry_ts=ts + 60,
                       side=intent.side, count=count, fill_price=fill,
                       fee=fee, fair=intent.fair, edge_at_decision=intent.edge,
                       tag=intent.tag, tau_s=intent.tau_s, contested=contested)
            open_pos[tkr] = tr
            trades.append(tr)

        # any still-open positions: mark at fill (shouldn't happen with settle events)
        final_equity = cash + sum(p.count * p.fill_price for p in open_pos.values())
        return self._metrics(trades, equity_curve, final_equity, daily_pnl, dict(skipped))

    def _metrics(self, trades, curve, final_equity, daily_pnl, skipped) -> dict:
        settled = [t for t in trades if t.pnl is not None]
        n = len(settled)
        pnl = sum(t.pnl for t in settled)
        fees = sum(t.fee for t in settled)
        wins = sum(1 for t in settled if t.pnl > 0)
        if n > 1:
            mu_t = pnl / n
            sd_t = (sum((t.pnl - mu_t) ** 2 for t in settled) / (n - 1)) ** 0.5
            t_stat = mu_t / (sd_t / math.sqrt(n)) if sd_t > 0 else 0.0
        else:
            t_stat = 0.0
        # daily series: calendar days from first to last settlement, flat days
        # count as zero (defaultdict access during gating creates spurious keys)
        active = sorted(d for d, v in daily_pnl.items() if v != 0.0)
        if active:
            from datetime import date, timedelta
            d0 = date.fromisoformat(active[0])
            d1 = date.fromisoformat(active[-1])
            days = []
            while d0 <= d1:
                days.append(d0.isoformat())
                d0 += timedelta(days=1)
        else:
            days = []
        dser = [daily_pnl.get(d, 0.0) for d in days]
        mu = sum(dser) / len(dser) if dser else 0.0
        sd = (sum((x - mu) ** 2 for x in dser) / len(dser)) ** 0.5 if len(dser) > 1 else 0.0
        sharpe_d = mu / sd * math.sqrt(252) if sd > 0 else 0.0
        peak, mdd = self.bankroll0, 0.0
        for _, eq in curve:
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak)
        by = lambda key: {
            k: {"n": len(v), "pnl": round(sum(t.pnl for t in v), 2),
                "hit": round(sum(1 for t in v if t.pnl > 0) / len(v), 3) if v else 0}
            for k, v in _group(settled, key).items()}
        return {
            "n_trades": n,
            "final_equity": round(final_equity, 2),
            "net_pnl": round(pnl, 2),
            "return_pct": round(100 * pnl / self.bankroll0, 2),
            "fees": round(fees, 2),
            "hit_rate": round(wins / n, 3) if n else None,
            "avg_pnl_per_trade": round(pnl / n, 3) if n else None,
            "avg_fill": round(sum(t.fill_price for t in settled) / n, 3) if n else None,
            "t_stat": round(t_stat, 2),
            "daily_sharpe_ann": round(sharpe_d, 2),
            "max_drawdown_pct": round(100 * mdd, 2),
            "trading_days": len(days),
            "by_metal": by(lambda t: t.metal),
            "by_side": by(lambda t: t.side),
            "by_tag": by(lambda t: t.tag),
            # contested/uncontested split (the review's key diagnostic): in
            # "touch" mode the uncontested subset is the certain-fill floor a
            # slow taker actually gets — its P&L is the honest headline.
            "by_fill": by(lambda t: "contested" if t.contested else "uncontested"),
            "by_week": by(lambda t: datetime.fromtimestamp(
                t.entry_ts, tz=timezone.utc).strftime("%G-W%V")),
            "skipped": skipped,
            "trades": settled,
        }


def _group(items, key):
    out = defaultdict(list)
    for it in items:
        out[key(it)].append(it)
    return dict(out)
