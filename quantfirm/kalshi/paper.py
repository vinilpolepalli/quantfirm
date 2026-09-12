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

Signals: Kalshi event live_data (settlement-aligned) for every live
commodity series; Swissquote XAU/XAG is fallback for gold/silver only.

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
from .universe import (BANKROLL, PAPER_ASSETS, LIVE_SERIES as _SERIES,
                       YF_SYMBOLS)

SERIES = {v: k for k, v in _SERIES.items()}


def decision_bankroll(cash: dict, live: bool) -> float:
    """Size against the book that is actually at risk.

    Live orders used to inherit the shadow yolo hole and put 4% of
    that depleted paper cash into real clips (~$8). When live, size
    off the live ledger.
    """
    if live:
        v = float(cash.get("live") or 0.0)
        if v > 0:
            return v
    return float(cash.get("shadow") or 0.0)


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
    def __init__(self, path: str, bankroll0: float = BANKROLL):
        self.path = path
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
        else:
            d = {"bankroll0": bankroll0, "cash": {"shadow": bankroll0, "demo": bankroll0},
                 "open": [], "n_settled": 0, "realized": {"shadow": 0.0, "demo": 0.0},
                 "fees": {"shadow": 0.0, "demo": 0.0}, "started": _now_iso()}
        for book in ("shadow", "demo", "maker", "live"):
            d.setdefault("cash", {}).setdefault(book, bankroll0)
            d.setdefault("realized", {}).setdefault(book, 0.0)
            d.setdefault("fees", {}).setdefault(book, 0.0)
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


class MakerQuote:
    """One resting shadow quote. side is the OUTCOME we would end up long."""

    def __init__(self, ticker: str, metal: str, side: str, price: float,
                 count: int, fair: float, placed_ts: float, close_ts: int):
        self.ticker, self.metal, self.side = ticker, metal, side
        self.price, self.count, self.fair = price, count, fair
        self.placed_ts, self.close_ts = placed_ts, close_ts


class PaperEngine:
    def __init__(self, params: Params, state_path: str, log_path: str,
                 decisions_path: str | None = None,
                 metals: tuple[str, ...] = PAPER_ASSETS,
                 use_demo: bool = True, bankroll0: float = BANKROLL,
                 maker: bool = True, maker_margin: float = 0.04,
                 maker_fade: float = 0.02, decide_fn=None,
                 tape_path: str | None = None, live: bool = False,
                 strategy: str | None = None):
        from .feeds import KalshiLiveFeed, SwissquoteFeed
        self.params = params
        self.metals = metals
        self.decide_fn = decide_fn or decide
        self.prod = KalshiClient("prod")
        self.demo = KalshiClient("demo")
        self.use_demo = use_demo and self.demo.can_trade
        # Live prod orders: explicit flag + prod key + no kill switch.
        # Shadow economics still run either way.
        from .halt import kill_switch_tripped
        self.use_live = bool(live and self.prod.can_trade and not kill_switch_tripped())
        self.state = PaperState(state_path, bankroll0)
        self.log_path = log_path
        self.decisions_path = decisions_path
        self.tape_path = tape_path
        self._tape_seen: set[str] = set()
        # Settlement-aligned Kalshi live_data for every commodity series.
        # Swissquote XAU/XAG is the fallback if live_data is empty.
        self.feeds = {}
        self._fallback = {}
        for metal in metals:
            series = SERIES.get(metal)
            if series:
                self.feeds[metal] = KalshiLiveFeed(self.prod, series)
            if metal == "gold":
                self._fallback[metal] = SwissquoteFeed("XAU")
            elif metal == "silver":
                self._fallback[metal] = SwissquoteFeed("XAG")
        self.vol = {m: VolEstimator(halflife_min=params.vol_halflife_min,
                                    diurnal=params.diurnal) for m in metals}
        self.state.d["metals"] = list(metals)
        if strategy:
            self.state.d["strategy"] = strategy
        self.state.d["live"] = self.use_live
        self.state.save()
        self._last_1m: dict[str, tuple[int, float]] = {}
        self._mkt_cache: dict[str, dict] = {}
        self._mkt_cache_ts: dict[str, float] = {}
        # per-ticker (ts, mid, fair) samples for the 3-min regime lookback
        self._hist: dict[str, list[tuple[float, float, float]]] = {}
        # maker shadow leg (zero-fee passive quotes on the favorite side)
        self.maker = maker
        self.maker_margin = maker_margin
        self.maker_fade = maker_fade
        self._quotes: dict[str, MakerQuote] = {}
        self._day: dict = {}
        self._open_px: dict[str, float] = {}

    # ------------------------------------------------------------ vol warmup
    def warm_vol_from_bars(self, metal: str, sym: str, minutes: int = 400):
        """Seed the EWMA from recent 1-min underlying bars — the SAME estimator
        the backtest uses (review finding: warming from 15-min prints gave a
        ~2-4 d.o.f. estimate that swung 20% on a single print and diverged from
        the backtest clock). Falls back to prints if yfinance is unavailable."""
        try:
            import datetime as dt
            import pandas as pd
            import yfinance as yf
            import yfinance._http as yh
            yh.HAS_CURL_CFFI = False
            df = yf.download(sym, period="7d", interval="1m", progress=False,
                             auto_adjust=False, prepost=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0].lower() for c in df.columns]
            else:
                df.columns = [c.lower() for c in df.columns]
            closes = df["close"].dropna()
            prev = None
            for tsp, v in list(closes.items())[-minutes:]:
                ts = int(tsp.timestamp()) + 60
                v = float(v)
                if prev and prev[1] > 0 and v > 0 and 0 < ts - prev[0] <= 120:
                    self.vol[metal].update(ts, math.log(v / prev[1]))
                prev = (ts, v)
            return
        except Exception:
            pass
        self._warm_vol_from_prints(SERIES[metal], metal)

    def _warm_vol_from_prints(self, series: str, metal: str, n: int = 400):
        """Fallback seeding from settled-window 15-min prints."""
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
                lr1 = math.log(v / prev) / math.sqrt(15.0)
                ts = parse_market_times(m)[1]
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

    # ------------------------------------------------------------- daily stop
    def _entries_allowed(self) -> dict:
        """Per-book daily loss stop, mirroring the backtest gate. The day
        baseline is PERSISTED in state (review finding: an in-memory baseline
        re-arms from depleted equity on every restart, defeating the stop)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        eq = {}
        for book in ("shadow", "maker", "live"):
            eq[book] = self.state.d["cash"][book] + sum(
                p.count * p.fill_price for p in self.state.open
                if p.adapter == book)
        day = self.state.d.setdefault("day_stop", {})
        if day.get("date") != today:
            day.clear()
            day.update({"date": today, "start": dict(eq)})
        lim = 1.0 - self.params.daily_stop_frac
        return {b: eq[b] >= lim * day["start"].get(b, eq[b]) for b in eq}

    # ------------------------------------------------------------- maker leg
    def _maker_tick(self, metal: str, tkr: str, now: float, fair: float,
                    bid: float | None, ask: float | None, close_ts: int,
                    allowed: bool) -> list[str]:
        notes = []
        tau = close_ts - now
        quote = self._quotes.get(tkr)
        if quote is not None:
            try:
                trades = self.prod.get_trades(tkr, limit=100)
            except Exception:
                trades = []
            if self._maker_filled(quote, trades):
                cost = quote.count * quote.price
                if cost <= self.state.d["cash"]["maker"]:
                    self.state.d["cash"]["maker"] -= cost
                    self.state.open.append(PaperPosition(
                        ticker=quote.ticker, metal=quote.metal, side=quote.side,
                        count=quote.count, fill_price=quote.price, fee=0.0,
                        fair=quote.fair, entry_ts=int(now), close_ts=quote.close_ts,
                        adapter="maker", tag="maker"))
                    notes.append(f"MAKER FILL {quote.side} {quote.count} {tkr}"
                                 f" @ {quote.price:.2f} fair@quote={quote.fair:.3f}")
                del self._quotes[tkr]
            elif (tau < 180
                  or (quote.side == "yes" and fair < quote.fair - self.maker_fade)
                  or (quote.side == "no" and fair > quote.fair + self.maker_fade)):
                notes.append(f"maker cancel {tkr} tau={int(tau)}")
                del self._quotes[tkr]
            return notes

        if not allowed or not (180 <= tau <= 660) or bid is None or ask is None:
            return notes
        if ask - bid <= 0.01:
            pass  # 1c book: joining the touch is still fine
        if any(p.ticker == tkr and p.adapter == "maker" for p in self.state.open):
            return notes
        m = self.maker_margin
        side = px = None
        if fair >= 0.55:  # rest a YES bid below fair (favorite side long yes)
            px = min(round(fair - m, 2), round(bid + 0.01, 2), 0.90)
            if px >= ask:  # never cross
                px = round(ask - 0.01, 2)
            if px >= bid and px >= 0.35 and fair - px >= m:
                side = "yes"
        elif fair <= 0.45:  # rest a NO bid ⇔ YES ask at 1-px
            fair_no = 1.0 - fair
            no_bid = round(1.0 - ask, 2)
            px = min(round(fair_no - m, 2), round(no_bid + 0.01, 2), 0.90)
            if 1.0 - px <= bid:  # would cross the yes bid
                px = round(1.0 - bid - 0.01, 2)
            if px >= no_bid and px >= 0.35 and fair_no - px >= m:
                side = "no"
        if side is None or px is None or px <= 0:
            return notes
        from .fair import kelly_fraction
        q_side = fair if side == "yes" else 1.0 - fair
        f = self.params.kelly_mult * kelly_fraction(q_side, px)
        stake = min(f, self.params.max_stake_frac) * self.state.d["cash"]["maker"]
        count = int(stake / px)
        if count < self.params.min_count:
            return notes
        self._quotes[tkr] = MakerQuote(tkr, metal, side, px, count, fair,
                                       now, close_ts)
        notes.append(f"maker quote {side} {count} {tkr} @ {px:.2f} fair={fair:.3f}")
        return notes

    @staticmethod
    def _maker_filled(q: MakerQuote, trades: list[dict]) -> bool:
        """Conservative tape-based fill: the book must trade THROUGH our
        price (strictly better for the taker than our level), or sweep 3x
        our size exactly at it. Queue priority is unknowable publicly."""
        thru = at = 0.0
        for t in trades:  # newest first
            ct = t.get("created_time")
            try:
                ts = datetime.fromisoformat(ct.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if ts <= q.placed_ts:
                break
            try:
                yp = float(t["yes_price_dollars"])
                c = float(t["count_fp"])
            except (KeyError, TypeError, ValueError):
                continue
            taker = t.get("taker_outcome_side") or t.get("taker_side")
            if q.side == "yes" and taker == "no":
                if yp < q.price - 1e-9:
                    thru += c
                elif abs(yp - q.price) < 1e-9:
                    at += c
            elif q.side == "no" and taker == "yes":
                ask_lvl = 1.0 - q.price
                if yp > ask_lvl + 1e-9:
                    thru += c
                elif abs(yp - ask_lvl) < 1e-9:
                    at += c
        return thru >= q.count or at >= 3 * q.count

    # ------------------------------------------------------------------ tick
    def tick(self) -> list[str]:
        notes = []
        now = int(time.time())
        allowed = self._entries_allowed()
        for metal in self.metals:
            feed = self.feeds.get(metal)
            px = feed.price() if feed is not None else None
            if px is None:
                fb = self._fallback.get(metal)
                px = fb.price() if fb is not None else None
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
            # per-adapter dedupe: a maker or demo fill must NOT silence the
            # shadow taker record for the rest of the window (review finding).
            shadow_here = any(p.ticker == tkr and p.adapter == "shadow"
                              for p in self.state.open)
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
            _cl = self.params.prob_clamp
            fair_now = min(max(fair_now, _cl), 1.0 - _cl)  # same cap as decide()
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
            if tkr not in self._open_px:
                self._open_px[tkr] = s_now
            intent = None
            if allowed["shadow"] and not shadow_here:
                intent = self.decide_fn(
                    ticker=tkr, ts=now, s=s_now, k=k, sigma_1m=sigma,
                    close_ts=close_ts, yes_bid=bid, yes_ask=ask,
                    bankroll=decision_bankroll(self.state.d["cash"], self.use_live),
                    open_positions=len(shadow_open), params=self.params,
                    recent_fair_move=fair_move, recent_mkt_move=mkt_move,
                    f_now=s_now, f_open=self._open_px[tkr], open_ts=open_ts,
                    metal=metal)
            if self.decisions_path:
                self._log_decision(now, metal, tkr, s_now, k, sigma, bid, ask,
                                   close_ts, intent)
            if self.maker:
                notes.extend(self._maker_tick(metal, tkr, now, fair_now, bid,
                                              ask, close_ts, allowed["maker"]))
            if self.tape_path:
                self._persist_tape(tkr)
            if intent is None:
                continue
            from .halt import blocked_by_corr
            if blocked_by_corr(metal, intent.side, shadow_open):
                continue
            notes.extend(self._execute(intent, metal, m, q, now, close_ts))
        notes.extend(self.settle_due())
        return notes

    # -------------------------------------------------------------- execution
    def _execute(self, intent, metal, m, q, now, close_ts) -> list[str]:
        notes = []
        # Two-phase shadow fill (review finding): the decision used quote q;
        # a real taker's order lands ~latency later, so RE-FETCH the book and
        # require the limit to still be marketable with size >= count. This
        # measures the race-loss the single-snapshot fill hid. The re-fetch
        # RTT (~0.2-0.6s) IS the latency; no artificial sleep needed.
        try:
            q2 = self.prod.get_quote(intent.ticker)
        except Exception:
            q2 = q
        if intent.side == "yes":
            still = (q2.yes_ask is not None
                     and float(q2.yes_ask) <= intent.limit_price + 1e-9)
            size_at_touch = q2.yes_ask_size
        else:
            no_bid = (1.0 - float(q2.yes_ask)) if q2.yes_ask is not None else None
            # our NO fill = 1 - yes_bid; still marketable if yes_bid unchanged low
            still = (q2.yes_bid is not None
                     and (1.0 - float(q2.yes_bid)) <= intent.limit_price + 1e-9)
            size_at_touch = q2.yes_bid_size
        if not still:
            notes.append(f"shadow race-loss (repriced) {intent.ticker}")
            return notes + self._demo_leg(intent, metal, now, close_ts) \
                + self._live_leg(intent, metal, now, close_ts)
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
        return notes + self._demo_leg(intent, metal, now, close_ts) \
            + self._live_leg(intent, metal, now, close_ts)

    def _place_ioc(self, client, adapter: str, intent, metal, now, close_ts) -> list[str]:
        """Shared IOC path for demo plumbing and gated live prod orders."""
        if any(p.ticker == intent.ticker and p.adapter == adapter
               for p in self.state.open):
            return []
        notes = []
        try:
            side = "bid" if intent.side == "yes" else "ask"
            yes_price = (intent.limit_price if intent.side == "yes"
                         else 1.0 - intent.limit_price)
            resp = client.create_order(
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
                self.state.d["cash"][adapter] -= filled * side_fill + fee
                self.state.open.append(PaperPosition(
                    ticker=intent.ticker, metal=metal, side=intent.side,
                    count=int(filled), fill_price=side_fill, fee=fee,
                    fair=intent.fair, entry_ts=now, close_ts=close_ts,
                    adapter=adapter, tag=intent.tag,
                    order_id=order.get("order_id")))
                notes.append(f"{adapter.upper()} FILL {intent.side} {filled} {intent.ticker}")
            else:
                notes.append(f"{adapter} IOC no-fill {intent.ticker}")
        except Exception as e:
            notes.append(f"{adapter} order error {intent.ticker}: {e}")
        return notes

    def _demo_leg(self, intent, metal, now, close_ts) -> list[str]:
        if not self.use_demo:
            return []
        return self._place_ioc(self.demo, "demo", intent, metal, now, close_ts)

    def _live_leg(self, intent, metal, now, close_ts) -> list[str]:
        """Real-money IOC. Off unless --live and a prod key are both set."""
        if not self.use_live:
            return []
        if os.environ.get("KALSHI_LIVE", "0") not in ("1", "true", "TRUE", "yes"):
            return ["live blocked: set KALSHI_LIVE=1 to actually send prod orders"]
        return self._place_ioc(self.prod, "live", intent, metal, now, close_ts)

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

    def _persist_tape(self, ticker: str):
        """Append new public prints so maker fills can be replayed offline.

        This is the #1 open item in docs/HANDOFF.md. Without the tape, the
        3x-size-at-level fill guess cannot be audited.
        """
        try:
            trades = self.prod.get_trades(ticker, limit=50)
        except Exception:
            return
        new_rows = []
        for t in trades:
            tid = t.get("trade_id") or t.get("created_time")
            if not tid or tid in self._tape_seen:
                continue
            self._tape_seen.add(tid)
            new_rows.append({
                "logged_at": _now_iso(),
                "ticker": ticker,
                "trade_id": t.get("trade_id"),
                "created_time": t.get("created_time"),
                "yes_price_dollars": t.get("yes_price_dollars"),
                "count_fp": t.get("count_fp"),
                "taker_side": t.get("taker_outcome_side") or t.get("taker_side"),
            })
        if not new_rows or not self.tape_path:
            return
        with open(self.tape_path, "a") as f:
            for row in new_rows:
                f.write(json.dumps(row) + "\n")

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
        import dataclasses
        self.state.d["effective_params"] = dataclasses.asdict(self.params)
        for metal in self.metals:
            if metal in self.feeds and metal in YF_SYMBOLS:
                self.warm_vol_from_bars(metal, YF_SYMBOLS[metal])
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
