"""Live paper-trading engine for the 15M metals desk.

PAPER ONLY: economics are simulated. Two execution adapters run together:

  * ShadowAdapter — the ECONOMIC record. Decisions are priced against the
    PRODUCTION public orderbook (where the real liquidity is); a taker
    intent "fills" only if prod top-of-book size at the touch covers the
    order. This is the number the desk is judged on.
  * DemoAdapter — the PLUMBING record. The same intents are sent as real
    IOC limit orders to the Kalshi DEMO exchange when demo credentials are
    configured (env KALSHI_DEMO_KEY_ID + KALSHI_DEMO_PRIVATE_KEY[_PATH]).
    Demo books are empty/fake, so demo fills prove the order path works,
    not that the strategy earns.

Signals: Swissquote XAU/XAG (measured ~1 bp from the Pyth settlement feed).
Copper has no keyless realtime feed and stays DISABLED for entries.

State lives in state/kalshi_paper_state.json + state/kalshi_paper_trades.csv
(repo convention); every decision tick can be logged for later calibration.
The engine is single-shot: run N minutes, persist, exit — safe to rerun.
"""

from __future__ import annotations

import csv
import json
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .client import KalshiClient, parse_market_times
from .fair import VolEstimator, taker_fee
from .strategy import Params, decide

SERIES = {"gold": "KXGOLD15M", "silver": "KXSILVER15M", "copper": "KXCOPPER15M"}


@dataclass
class PaperPosition:
    ticker: str
    metal: str
    side: str
    count: int
    fill_price: float
    fee: float
    fair: float
    entry_ts: int
    close_ts: int
    adapter: str          # 'shadow' | 'demo'
    tag: str = "stale"
    order_id: str | None = None


class PaperState:
    def __init__(self, path: str, bankroll0: float = 500.0):
        self.path = path
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
        else:
            d = {"bankroll0": bankroll0, "cash": {"shadow": bankroll0, "demo": bankroll0},
                 "open": [], "n_settled": 0, "realized": {"shadow": 0.0, "demo": 0.0},
                 "fees": {"shadow": 0.0, "demo": 0.0}, "started": _now_iso()}
        self.d = d
        self.open: list[PaperPosition] = [PaperPosition(**p) for p in d.get("open", [])]

    def save(self):
        self.d["open"] = [asdict(p) for p in self.open]
        self.d["updated"] = _now_iso()
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.d, f, indent=1)
        os.replace(tmp, self.path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_trade_log(path: str, row: dict):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


class PaperEngine:
    def __init__(self, params: Params, state_path: str, log_path: str,
                 decisions_path: str | None = None,
                 metals: tuple[str, ...] = ("gold", "silver"),
                 use_demo: bool = True, bankroll0: float = 500.0):
        from .feeds import SwissquoteFeed
        self.params = params
        self.metals = metals
        self.prod = KalshiClient("prod")
        self.demo = KalshiClient("demo")
        self.use_demo = use_demo and self.demo.can_trade
        self.state = PaperState(state_path, bankroll0)
        self.log_path = log_path
        self.decisions_path = decisions_path
        self.feeds = {}
        if "gold" in metals:
            self.feeds["gold"] = SwissquoteFeed("XAU")
        if "silver" in metals:
            self.feeds["silver"] = SwissquoteFeed("XAG")
        # copper: no entry-grade keyless feed; excluded from entries
        self.vol = {m: VolEstimator(halflife_min=params.vol_halflife_min,
                                    diurnal=params.diurnal) for m in metals}
        self._last_1m: dict[str, tuple[int, float]] = {}
        self._mkt_cache: dict[str, dict] = {}
        self._mkt_cache_ts: dict[str, float] = {}
        # per-ticker (ts, mid, fair) samples for the 3-min regime lookback
        self._hist: dict[str, list[tuple[float, float, float]]] = {}

    # ------------------------------------------------------------ vol warmup
    def warm_vol_from_prints(self, series: str, metal: str, n: int = 400):
        """Seed the EWMA from recent settled-window prints (15-min returns)."""
        try:
            d = self.prod.get_markets(series_ticker=series, status="settled", limit=n)
        except Exception:
            return
        mkts = sorted(d.get("markets", []), key=lambda m: m["close_time"])
        prev = None
        for m in mkts:
            v = m.get("expiration_value")
            if not v:
                continue
            v = float(v)
            if prev and prev > 0 and v > 0:
                lr15 = math.log(v / prev)
                # spread one 15-min return over 15 one-minute updates
                ts = parse_market_times(m)[1]
                lr1 = lr15 / math.sqrt(15.0)
                for k in range(15):
                    self.vol[metal].update(ts - 60 * (14 - k), lr1)
            prev = v

    # ------------------------------------------------------------- market ref
    def current_market(self, series: str) -> dict | None:
        now = time.time()
        m = self._mkt_cache.get(series)
        if m is not None:
            _, close_ts = parse_market_times(m)
            if close_ts > now and now - self._mkt_cache_ts.get(series, 0) < 300:
                return m
        try:
            m = self.prod.open_market_for_series(series)
        except Exception:
            return self._mkt_cache.get(series)
        if m:
            self._mkt_cache[series] = m
            self._mkt_cache_ts[series] = now
        return m

    # ------------------------------------------------------------------ tick
    def tick(self) -> list[str]:
        notes = []
        now = int(time.time())
        for metal in self.metals:
            feed = self.feeds.get(metal)
            if feed is None:
                continue
            px = feed.price()
            if px is None:
                continue
            ts_px, s_now = px
            if now - ts_px > self.params.signal_max_age_s:
                continue
            # update 1-min vol clock from the feed
            lm = self._last_1m.get(metal)
            minute = now - now % 60
            if lm is None:
                self._last_1m[metal] = (minute, s_now)
            elif minute > lm[0]:
                if s_now > 0 and lm[1] > 0:
                    self.vol[metal].update(minute, math.log(s_now / lm[1]))
                self._last_1m[metal] = (minute, s_now)

            series = SERIES[metal]
            m = self.current_market(series)
            if not m or m.get("floor_strike") is None:
                continue
            open_ts, close_ts = parse_market_times(m)
            if not (open_ts <= now < close_ts):
                continue
            tkr = m["ticker"]
            if any(p.ticker == tkr for p in self.state.open):
                continue
            try:
                q = self.prod.get_quote(tkr)
            except Exception:
                continue
            bid = float(q.yes_bid) if q.yes_bid is not None else None
            ask = float(q.yes_ask) if q.yes_ask is not None else None
            sigma = self.vol[metal].sigma_1m(now)
            k = float(m["floor_strike"])
            # 3-min regime lookback from the sample history
            from .fair import fair_yes
            fair_now = fair_yes(s_now, k, sigma, (close_ts - now) / 60.0)
            mid_now = (bid + ask) / 2 if (bid is not None and ask is not None) else None
            hist = self._hist.setdefault(tkr, [])
            mkt_move = fair_move = 0.0
            past = [h for h in hist if h[0] <= now - 170]
            if past and mid_now is not None:
                _, mid_p, fair_p = past[-1]
                mkt_move, fair_move = mid_now - mid_p, fair_now - fair_p
            if mid_now is not None:
                hist.append((now, mid_now, fair_now))
                self._hist[tkr] = [h for h in hist if h[0] > now - 330]
            shadow_open = [p for p in self.state.open if p.adapter == "shadow"]
            intent = decide(ticker=tkr, ts=now, s=s_now, k=k, sigma_1m=sigma,
                            close_ts=close_ts, yes_bid=bid, yes_ask=ask,
                            bankroll=self.state.d["cash"]["shadow"],
                            open_positions=len(shadow_open), params=self.params,
                            recent_fair_move=fair_move, recent_mkt_move=mkt_move)
            if self.decisions_path:
                self._log_decision(now, metal, tkr, s_now, k, sigma, bid, ask,
                                   close_ts, intent)
            if intent is None:
                continue
            # correlated-direction cap (gold/silver same direction share a slot)
            if metal in ("gold", "silver") and any(
                    p.metal in ("gold", "silver") and p.side == intent.side
                    for p in shadow_open):
                continue
            notes.extend(self._execute(intent, metal, m, q, now, close_ts))
        notes.extend(self.settle_due())
        return notes

    # -------------------------------------------------------------- execution
    def _execute(self, intent, metal, m, q, now, close_ts) -> list[str]:
        notes = []
        # shadow fill against prod top-of-book size
        size_at_touch = q.yes_ask_size if intent.side == "yes" else q.yes_bid_size
        size_ok = size_at_touch is not None and float(size_at_touch) >= intent.count
        if size_ok:
            fee = taker_fee(intent.count, intent.limit_price)
            cost = intent.count * intent.limit_price + fee
            if cost <= self.state.d["cash"]["shadow"]:
                self.state.d["cash"]["shadow"] -= cost
                self.state.open.append(PaperPosition(
                    ticker=intent.ticker, metal=metal, side=intent.side,
                    count=intent.count, fill_price=intent.limit_price, fee=fee,
                    fair=intent.fair, entry_ts=now, close_ts=close_ts,
                    adapter="shadow", tag=intent.tag))
                notes.append(f"SHADOW FILL {intent.side} {intent.count} {intent.ticker}"
                             f" @ {intent.limit_price:.3f} fair={intent.fair:.3f}")
        else:
            notes.append(f"shadow no-fill (size at touch) {intent.ticker}")

        if self.use_demo:
            try:
                side = "bid" if intent.side == "yes" else "ask"
                yes_price = (intent.limit_price if intent.side == "yes"
                             else 1.0 - intent.limit_price)
                resp = self.demo.create_order(
                    ticker=intent.ticker, side=side, count=intent.count,
                    price=Decimal(str(round(yes_price, 4))),
                    time_in_force="immediate_or_cancel",
                    client_order_id=str(uuid.uuid4()))
                order = resp.get("order", resp)
                filled = float(order.get("fill_count") or 0)
                if filled > 0:
                    afp = order.get("average_fill_price")
                    yes_fill = float(afp) if afp else yes_price
                    side_fill = yes_fill if intent.side == "yes" else 1.0 - yes_fill
                    fee = float(order.get("average_fee_paid") or 0) * filled \
                        or taker_fee(filled, side_fill)
                    self.state.d["cash"]["demo"] -= filled * side_fill + fee
                    self.state.open.append(PaperPosition(
                        ticker=intent.ticker, metal=metal, side=intent.side,
                        count=int(filled), fill_price=side_fill, fee=fee,
                        fair=intent.fair, entry_ts=now, close_ts=close_ts,
                        adapter="demo", tag=intent.tag,
                        order_id=order.get("order_id")))
                    notes.append(f"DEMO FILL {intent.side} {filled} {intent.ticker}")
                else:
                    notes.append(f"demo IOC no-fill {intent.ticker}")
            except Exception as e:
                notes.append(f"demo order error {intent.ticker}: {e}")
        return notes

    # ------------------------------------------------------------- settlement
    def settle_due(self) -> list[str]:
        notes = []
        now = time.time()
        still = []
        for p in self.state.open:
            if now < p.close_ts + 60:
                still.append(p)
                continue
            try:
                m = self.prod.get_market(p.ticker)
            except Exception:
                still.append(p)
                continue
            res = m.get("result")
            if res not in ("yes", "no"):
                still.append(p)
                continue
            win = (p.side == res)
            payout = p.count * (1.0 if win else 0.0)
            pnl = payout - p.count * p.fill_price - p.fee
            self.state.d["cash"][p.adapter] += payout
            self.state.d["realized"][p.adapter] += pnl
            self.state.d["fees"][p.adapter] += p.fee
            self.state.d["n_settled"] += 1
            append_trade_log(self.log_path, {
                "settled_at": _now_iso(), "adapter": p.adapter, "ticker": p.ticker,
                "metal": p.metal, "side": p.side, "count": p.count,
                "fill_price": round(p.fill_price, 4), "fee": round(p.fee, 4),
                "fair_at_entry": round(p.fair, 4), "result": res,
                "pnl": round(pnl, 4), "tag": p.tag,
                "cash_after": round(self.state.d["cash"][p.adapter], 2)})
            notes.append(f"SETTLE {p.adapter} {p.ticker} {res} pnl={pnl:+.2f}")
        self.state.open = still
        return notes

    def _log_decision(self, ts, metal, tkr, s, k, sigma, bid, ask, close_ts, intent):
        from .fair import fair_yes
        rec = {"ts": ts, "metal": metal, "ticker": tkr, "s": s, "k": k,
               "sigma_1m": sigma, "bid": bid, "ask": ask,
               "tau_s": close_ts - ts,
               "fair": fair_yes(s, k, sigma, (close_ts - ts) / 60.0),
               "intent": (intent.side if intent else None)}
        with open(self.decisions_path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    # ------------------------------------------------------------------- run
    def run(self, minutes: float, poll_s: float = 2.0):
        t_end = time.time() + minutes * 60
        n = 0
        for metal in self.metals:
            if metal in self.feeds:
                self.warm_vol_from_prints(SERIES[metal], metal)
        print(f"paper engine: metals={self.metals} demo={'ON' if self.use_demo else 'off'}"
              f" cash={self.state.d['cash']}", flush=True)
        while time.time() < t_end:
            t0 = time.time()
            try:
                for note in self.tick():
                    print(f"[{_now_iso()}] {note}", flush=True)
            except Exception as e:
                print(f"[{_now_iso()}] tick error: {e}", flush=True)
            n += 1
            if n % 30 == 0:
                self.state.save()
            time.sleep(max(0.0, poll_s - (time.time() - t0)))
        self.state.save()
        print(f"paper engine done: cash={self.state.d['cash']} "
              f"realized={self.state.d['realized']} open={len(self.state.open)}",
              flush=True)
