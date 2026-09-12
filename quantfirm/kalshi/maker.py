"""Historical backtest for the MAKER leg.

!! INVALID FOR VALIDATION — DO NOT QUOTE ITS P&L AS EVIDENCE. !!
Kept because the machinery is reusable and the failure is instructive.

This backtest reports ~+800%/t≈10 and it is an ARTIFACT. Proof (reproduce
with `python -m quantfirm.kalshi.cli maker-control --data data/kalshi`):
replacing the model's fair value with the MARKET'S OWN MID — i.e. removing
all predictive input — makes the result BETTER (+1268%, t=12.05 vs +793%,
t=10.36). A strategy with no model cannot beat one with a model unless the
P&L is not coming from prediction.

Root cause: 1-minute OHLC cannot support a maker fill test. Trade prices
swing widely inside a single minute (a 0.40/0.41 quote routinely sees prints
from 0.41 to 0.58). Testing "did a print touch my level" and then awarding a
fill AT OUR LIMIT grants us the intra-minute extreme on every fill — the
buy-the-low fallacy. Queue position and partial fills are also unmodellable
here, so `queue`/`adverse` modes barely bind.

What a valid version needs: the per-print trades tape
(GET /markets/trades: price, taker_side, timestamp), so a resting YES bid at
P fills only against actual SELL prints at <= P, after enough such volume has
cleared the queue ahead of it. Until that exists, the ONLY honest evidence
for the maker leg is the live shadow record in research/kalshi_backtest.md.

-- original description follows --

Why this file exists: the maker leg was judged on ~78 live shadow fills,
which is far too few to separate a 73%-hit edge from a 66%-hit break-even
run (its measured break-even hit rate). The same 1-min contract candles used
for the taker backtest can replay resting quotes over the full 6,655-market
history, turning n≈78 into n in the thousands — enough to actually answer it.

The quote lifecycle replayed here mirrors quantfirm/kalshi/paper.py exactly:
  * At each minute T inside a window, compute fair from the (re-anchored)
    underlying and the causal vol EWMA.
  * If fair is a clear favorite (>= favorite_hi, or <= favorite_lo), rest a
    passive quote on the favorite side at fair -/+ margin, never crossing the
    touch, subject to the same price floor and tau window as live.
  * Each subsequent minute: cancel if fair moves adversely by `fade`, or when
    tau drops below `min_tau_s`; otherwise test for a fill.
  * On fill, hold to settlement. Maker fee is $0 on all metals series.

FILL MODEL — the part that decides whether this is honest.
A resting quote is NOT filled just because the market touched its price;
that ignores queue position, which was the single biggest hole in the live
shadow record (it granted itself free priority). Three modes:

  "through"  : filled only if the book traded strictly THROUGH our level
               (someone swept past us). Optimistic-but-reasonable.
  "queue"    : DEFAULT. We join at the back of the queue. Filled only when
               cumulative volume printed at/through our level since posting
               exceeds `queue_ahead_mult` x our own size — i.e. enough flow
               to clear the people ahead of us AND us. Strictly harsher.
  "adverse"  : queue rules PLUS we only get the fills where the book kept
               moving against us afterwards (worst case: we are filled
               exactly when we are wrong). A deliberate lower bound.

Every mode holds to settlement, so there is no exit-side modelling error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from .backtest import METALS, Backtest, SETTLE_LAG_S
from .fair import VolEstimator, fair_yes


@dataclass(frozen=True)
class MakerParams:
    margin: float = 0.04          # quote this far below fair (in its own side's price)
    favorite_hi: float = 0.55     # fair >= this -> rest a YES bid
    favorite_lo: float = 0.45     # fair <= this -> rest a NO bid
    fade: float = 0.02            # cancel if fair moves this far against us
    min_tau_s: int = 180          # no resting quotes inside the last 3 minutes
    max_tau_s: int = 660          # do not quote before this much time remains
    min_price: float = 0.35       # never buy a side cheaper than this
    max_price: float = 0.90       # never buy a side richer than this
    vol_halflife_min: float = 30.0
    diurnal: bool = True
    prob_clamp: float = 0.02      # model is never more certain than this
    fill_mode: str = "queue"      # "through" | "queue" | "adverse"
    queue_ahead_mult: float = 3.0  # volume needed = mult x our size
    count: int = 25               # fixed size, so hit-rate stats aren't sizing-driven
    max_concurrent: int = 2
    min_recent_volume: float = 100.0


@dataclass
class MakerFill:
    ticker: str
    metal: str
    side: str          # 'yes' | 'no'
    price: float       # what we paid for that side
    count: int
    fair_at_quote: float
    quote_ts: int
    fill_ts: int
    tau_at_fill: float
    result: str | None = None
    pnl: float | None = None


class MakerBacktest:
    """Replays resting quotes over the harvested contract candles."""

    def __init__(self, data_dir: str, bankroll: float = 250.0):
        self._bt = Backtest(data_dir, bankroll=bankroll)
        self.bankroll0 = bankroll

    # ------------------------------------------------------------------ core
    def run(self, p: MakerParams, start_ts: int | None = None,
            end_ts: int | None = None) -> dict:
        bt = self._bt
        vol = {m: VolEstimator(halflife_min=p.vol_halflife_min, diurnal=p.diurnal)
               for m in bt.bars}

        # Interleave underlying bars (vol clock) with per-window quoting, in
        # strict time order, so the vol state never sees the future.
        events: list[tuple] = []
        for metal, bars in bt.bars.items():
            prev = None
            for ts in sorted(bars):
                if prev is not None and 0 < ts - prev[0] <= 120:
                    events.append((ts, 0, "bar", metal, math.log(bars[ts] / prev[1])))
                prev = (ts, bars[ts])
        windows = []
        for series, mkts in bt.markets.items():
            metal = METALS[series]
            for m in mkts:
                if start_ts and m["close_ts"] < start_ts:
                    continue
                if end_ts and m["close_ts"] >= end_ts:
                    continue
                windows.append((m["open_ts"], 1, "window", series, metal, m))
        events.extend(windows)
        events.sort(key=lambda e: (e[0], e[1]))

        fills: list[MakerFill] = []
        skipped: dict[str, int] = {}

        def skip(k):
            skipped[k] = skipped.get(k, 0) + 1

        for ev in events:
            if ev[2] == "bar":
                _, _, _, metal, lr = ev
                vol[metal].update(ev[0], lr)
                continue
            _, _, _, series, metal, m = ev
            f = self._quote_window(m, metal, series, vol[metal], p, skip)
            if f:
                fills.append(f)

        return self._metrics(fills, p, skipped)

    def _quote_window(self, m, metal, series, vol, p, skip) -> MakerFill | None:
        """Replay one 15-min window: post, manage, maybe fill. One quote max."""
        bt = self._bt
        cnds = bt.candles.get(series, {}).get(m["ticker"])
        if not cnds:
            skip("no_candles")
            return None
        bars = bt.bars.get(metal, {})
        f_open = bars.get(m["open_ts"])
        if f_open is None:
            skip("no_underlying")
            return None

        quote = None  # (side, price, fair_at_quote, quote_ts, vol_accum)
        for T in range(m["open_ts"] + 60, m["close_ts"], 60):
            tau = m["close_ts"] - T
            c = cnds.get(T)
            if not c:
                continue
            bid, ask = c.get("bid_close"), c.get("ask_close")
            f_now = bars.get(T)
            if f_now is None or bid is None or ask is None:
                continue
            if bid <= 0.0 and ask >= 1.0:
                continue

            s_now = f_now * (m["strike"] / f_open)
            sigma = vol.sigma_1m(T)
            fair = fair_yes(s_now, m["strike"], sigma, tau / 60.0)
            fair = min(max(fair, p.prob_clamp), 1.0 - p.prob_clamp)

            if quote is None:
                if not (p.min_tau_s <= tau <= p.max_tau_s):
                    continue
                recent_vol = sum((cnds.get(T - 60 * j, {}) or {}).get("volume") or 0.0
                                 for j in range(3))
                if recent_vol < p.min_recent_volume:
                    continue
                q = self._make_quote(fair, bid, ask, p)
                if q is None:
                    continue
                side, price = q
                quote = [side, price, fair, T, 0.0]
                continue

            side, price, fair_q, qts, vol_acc = quote
            # cancel: adverse fair move, or too close to expiry
            adverse = (fair < fair_q - p.fade) if side == "yes" else (fair > fair_q + p.fade)
            if adverse or tau < p.min_tau_s:
                skip("cancelled")
                quote = None
                continue

            filled, vol_acc = self._test_fill(c, side, price, vol_acc, p)
            quote[4] = vol_acc
            if filled:
                return MakerFill(ticker=m["ticker"], metal=metal, side=side,
                                 price=price, count=p.count, fair_at_quote=fair_q,
                                 quote_ts=qts, fill_ts=T, tau_at_fill=tau)
        if quote is not None:
            skip("expired_unfilled")
        return None

    @staticmethod
    def _make_quote(fair, bid, ask, p) -> tuple[str, float] | None:
        """Price a passive quote on the favorite side; never cross the touch."""
        if fair >= p.favorite_hi:
            # long YES: rest a bid below fair, at most 1c better than best bid
            px = min(round(fair - p.margin, 2), round(bid + 0.01, 2))
            if px >= ask:
                px = round(ask - 0.01, 2)
            if px < p.min_price or px > p.max_price or fair - px < p.margin:
                return None
            return ("yes", px)
        if fair <= p.favorite_lo:
            # long NO: our NO price is 1-yes_ask territory
            fair_no = 1.0 - fair
            no_bid = round(1.0 - ask, 2)
            px = min(round(fair_no - p.margin, 2), round(no_bid + 0.01, 2))
            if 1.0 - px <= bid:
                px = round(1.0 - bid - 0.01, 2)
            if px < p.min_price or px > p.max_price or fair_no - px < p.margin:
                return None
            return ("no", px)
        return None

    @staticmethod
    def _test_fill(c, side, price, vol_acc, p) -> tuple[bool, float]:
        """Did our resting quote fill during this candle?

        Tested against the last-TRADE price range, never the quote range.
        (Earlier versions tested the bid/ask range; because we post at
        best_bid+1c, `bid_low <= our_price` is true by construction, so every
        quote "filled" instantly and unconditionally — an artifact that
        produced a bogus +944%/t=11 result. Only a real print at our level is
        evidence someone traded with us.)

        YES bid at `price`: a seller must print at or below `price`.
        NO bid at `price` (≡ YES ask at 1-price): a buyer must print at or
        above `1-price`.
        """
        v = c.get("volume") or 0.0
        if v <= 0:
            return (False, vol_acc)
        if side == "yes":
            lo = c.get("px_low")
            touched = lo is not None and lo <= price + 1e-9
            through = lo is not None and lo < price - 1e-9
        else:
            hi = c.get("px_high")
            lvl = 1.0 - price
            touched = hi is not None and hi >= lvl - 1e-9
            through = hi is not None and hi > lvl + 1e-9

        if p.fill_mode == "through":
            return (bool(through), vol_acc)

        # queue modes: only volume printed while our level is actually in
        # play counts toward clearing the queue ahead of us
        if touched:
            vol_acc += v
        need = p.queue_ahead_mult * p.count
        if p.fill_mode == "queue":
            return (bool(touched and vol_acc >= need), vol_acc)
        # "adverse": queue cleared AND the tape kept going through our level
        return (bool(vol_acc >= need and through), vol_acc)

    # --------------------------------------------------------------- settle
    def _metrics(self, fills: list[MakerFill], p: MakerParams, skipped) -> dict:
        bt = self._bt
        res = {}
        for series, mkts in bt.markets.items():
            for m in mkts:
                res[m["ticker"]] = m["result"]
        settled = []
        for f in fills:
            r = res.get(f.ticker)
            if r not in ("yes", "no"):
                continue
            win = (f.side == r)
            f.result = r
            f.pnl = f.count * ((1.0 if win else 0.0) - f.price)  # maker fee = $0
            settled.append(f)

        n = len(settled)
        if n == 0:
            return {"n_fills": 0, "note": "no fills", "skipped": skipped}
        pnl = [f.pnl for f in settled]
        total = sum(pnl)
        wins = [x for x in pnl if x > 0]
        losses = [x for x in pnl if x <= 0]
        mu = total / n
        sd = (sum((x - mu) ** 2 for x in pnl) / (n - 1)) ** 0.5 if n > 1 else 0.0
        t = mu / (sd / math.sqrt(n)) if sd > 0 else 0.0
        avg_w = sum(wins) / len(wins) if wins else 0.0
        avg_l = sum(losses) / len(losses) if losses else 0.0
        be = abs(avg_l) / (avg_w + abs(avg_l)) if (avg_w + abs(avg_l)) > 0 else None

        # equity path on the starting bankroll, chronological
        settled.sort(key=lambda f: f.fill_ts)
        eq, peak, mdd = self.bankroll0, self.bankroll0, 0.0
        for f in settled:
            eq += f.pnl
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak)

        by = lambda key: {
            k: {"n": len(v), "pnl": round(sum(x.pnl for x in v), 2),
                "hit": round(sum(1 for x in v if x.pnl > 0) / len(v), 3)}
            for k, v in _group(settled, key).items()}

        return {
            "n_fills": n,
            "net_pnl": round(total, 2),
            "return_pct": round(100 * total / self.bankroll0, 2),
            "hit_rate": round(len(wins) / n, 4),
            "avg_win": round(avg_w, 2),
            "avg_loss": round(avg_l, 2),
            "breakeven_hit": round(be, 4) if be else None,
            "cushion_pp": round(100 * (len(wins) / n - be), 2) if be else None,
            "mean_pnl_per_fill": round(mu, 3),
            "sd_pnl": round(sd, 2),
            "t_stat": round(t, 2),
            "max_drawdown_pct": round(100 * mdd, 2),
            "by_metal": by(lambda f: f.metal),
            "by_side": by(lambda f: f.side),
            "skipped": skipped,
            "fills": settled,
        }


def _group(items, key):
    from collections import defaultdict
    out = defaultdict(list)
    for it in items:
        out[key(it)].append(it)
    return dict(out)


class MarketMidControl(MakerBacktest):
    """Null-model control: quote off the MARKET MID instead of the model.

    This strips out all predictive input while leaving the fill mechanics
    untouched. If the control earns as much as the real strategy, the P&L is
    mechanical and the backtest is invalid. It is the test that caught the
    maker artifact, so it stays in the codebase as a guard: any future change
    to the fill model must be re-run against this control, and the real
    strategy must beat it by a wide margin before any result is believed.
    """

    def _quote_window(self, m, metal, series, vol, p, skip):
        bt = self._bt
        cnds = bt.candles.get(series, {}).get(m["ticker"])
        if not cnds:
            return None
        quote = None
        for T in range(m["open_ts"] + 60, m["close_ts"], 60):
            tau = m["close_ts"] - T
            c = cnds.get(T)
            if not c:
                continue
            bid, ask = c.get("bid_close"), c.get("ask_close")
            if bid is None or ask is None or (bid <= 0.0 and ask >= 1.0):
                continue
            fair = min(max((bid + ask) / 2.0, p.prob_clamp), 1.0 - p.prob_clamp)
            if quote is None:
                if not (p.min_tau_s <= tau <= p.max_tau_s):
                    continue
                rv = sum((cnds.get(T - 60 * j, {}) or {}).get("volume") or 0.0
                         for j in range(3))
                if rv < p.min_recent_volume:
                    continue
                q = self._make_quote(fair, bid, ask, p)
                if q is None:
                    continue
                quote = [q[0], q[1], fair, T, 0.0]
                continue
            side, price, fair_q, qts, va = quote
            adverse = (fair < fair_q - p.fade) if side == "yes" else (fair > fair_q + p.fade)
            if adverse or tau < p.min_tau_s:
                quote = None
                continue
            filled, va = self._test_fill(c, side, price, va, p)
            quote[4] = va
            if filled:
                return MakerFill(ticker=m["ticker"], metal=metal, side=side,
                                 price=price, count=p.count, fair_at_quote=fair_q,
                                 quote_ts=qts, fill_ts=T, tau_at_fill=tau)
        return None
