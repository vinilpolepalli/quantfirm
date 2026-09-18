"""Paper / demo / live engine for the perps desk.

One ``tick()`` does, in order (the LLM is nowhere in this path):

  1. load the daily panel (refreshed by ``cli update-data``) and refuse to act
     on a stale one
  2. read venue truth: marks, top of book, exchange status, and for demo/live
     the account's positions — a mismatch with the local book HALTS
  3. accrue funding actually charged by Kalshi since the last tick, and
     interest on unencumbered collateral
  4. compute the deterministic target weights for today from the registered
     strategy, apply the drawdown ladder, and cap by the risk policy
  5. for every asset whose |target − held| exceeds the band on a rebalance
     day, run the pre-trade gate, then place ONE aggressive IOC limit inside
     the price band (reduce-only when it reduces risk); shadow books the
     fill at the far touch, demo/live book what the venue reports
  6. keep a server-side stop (bracket exit trigger) under every live position
  7. persist the book and the desk status

Adapters: ``shadow`` (public data, no orders — default), ``demo``
(fake money, real order plumbing on demo tickers), ``live`` (real money;
needs a prod key, ``KALSHI_LIVE=1``, ``config/perps.json`` live=true and no
``state/KILL_SWITCH_PERPS``). Every fill, skip and halt is logged as JSON.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal

import pandas as pd

from . import data as D
from .client import KalshiApiError, MarginClient, PerpQuote, banded_price, inside_band
from .risk import PROFILES, KILL_SWITCH, PerpsRiskPolicy, check_pre_trade, kill_switch_tripped, ladder_scale, trip_kill_switch
from .specs import COLLATERAL_APY, SPECS, TAKER_T0, PerpSpec, fee_rates
from .strategies import REGISTRY, resolve_band, cap_weights

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_DIR = os.path.join(ROOT, "state")
STATE_PATH = os.path.join(STATE_DIR, "perps_paper_state.json")
STATUS_PATH = os.path.join(STATE_DIR, "perps_desk_status.json")
DECISIONS_PATH = os.path.join(STATE_DIR, "perps_decisions.jsonl")
CONFIG_PATH = os.path.join(ROOT, "config", "perps.json")


def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"bankroll_usd": 250, "strategy": "trend_long_only", "params": {}, "profile": "balanced",
                "universe": ["btc", "eth", "gold", "silver"], "live": False}


@dataclass
class Position:
    asset: str
    ticker: str
    contracts: float          # signed
    avg_price: float          # $/contract
    opened: str

    def notional(self, price: float) -> float:
        return self.contracts * price


@dataclass
class Book:
    adapter: str
    bankroll0: float
    cash: float
    positions: dict = field(default_factory=dict)   # asset -> Position dict
    realized: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    interest: float = 0.0
    peak_equity: float = 0.0
    day: str = ""
    day_start_equity: float = 0.0
    week: str = ""
    week_start_equity: float = 0.0
    last_funding_ts: dict = field(default_factory=dict)  # asset -> iso ts of last funding applied
    last_interest_ts: float = 0.0
    last_rebalance_day: str = ""
    n_ticks: int = 0
    halted: str = ""
    started: str = ""
    updated: str = ""

    @staticmethod
    def new(adapter: str, bankroll: float) -> "Book":
        now = _now_iso()
        return Book(adapter=adapter, bankroll0=bankroll, cash=bankroll, peak_equity=bankroll,
                    last_interest_ts=time.time(), started=now, updated=now)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _iso_to_unix(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _week_of(ts: str) -> str:
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%G-W%V")
    except (TypeError, ValueError):
        return ""


def _position_fields(p: dict) -> dict:
    return {
        "asset": p["asset"],
        "ticker": p["ticker"],
        "contracts": float(p["contracts"]),
        "avg_price": float(p["avg_price"]),
        "opened": p["opened"],
    }


def book_from_status(status: dict, adapter: str) -> Book | None:
    """Rebuild the local paper book from the committed desk status.

    Paper state is gitignored; the status snapshot is what survives a fresh
    clone or a GitHub Actions runner. Without this, every new checkout
    silently opens a brand-new $250 book and the frozen legs disappear.
    ``last_funding_ts`` is the status timestamp so we accrue from then
    forward and do not replay funding the last tick already booked.
    """
    if not status or status.get("adapter") != adapter:
        return None
    raw_pos = status.get("positions") or []
    try:
        positions = {p["asset"]: _position_fields(p) for p in raw_pos}
    except (KeyError, TypeError, ValueError):
        return None
    ts = status.get("ts") or ""
    started = status.get("started") or ts
    equity = float(status.get("equity") or status.get("cash") or 0.0)
    cash = float(status.get("cash") if status.get("cash") is not None else equity)
    return Book(
        adapter=adapter,
        bankroll0=float(status.get("bankroll0") or 250.0),
        cash=cash,
        positions=positions,
        realized=float(status.get("realized") or 0.0),
        fees=float(status.get("fees") or 0.0),
        funding=float(status.get("funding") or 0.0),
        interest=float(status.get("interest") or 0.0),
        peak_equity=float(status.get("peak_equity") or equity or 250.0),
        day=ts[:10] if ts else "",
        day_start_equity=equity,
        week=_week_of(ts),
        week_start_equity=equity,
        last_funding_ts={a: ts for a in positions},
        last_interest_ts=_iso_to_unix(ts),
        last_rebalance_day=(started[:10] if started else ""),
        n_ticks=int(status.get("n_ticks") or 0),
        halted=status.get("halted") or "",
        started=started,
        updated=ts,
    )


def book_from_status_file(path: str, adapter: str) -> Book | None:
    try:
        with open(path) as f:
            return book_from_status(json.load(f), adapter)
    except (FileNotFoundError, TypeError, json.JSONDecodeError):
        return None


class PaperEngine:
    def __init__(self, strategy: str, params: dict | None = None, policy: PerpsRiskPolicy | None = None,
                 adapter: str = "shadow", bankroll: float = 250.0, universe=("btc", "eth", "gold", "silver"),
                 client: MarginClient | None = None, state_path: str | None = None,
                 book: str | None = None,
                 rebalance_every_days: int = 7, band: float = 0.03, slack_ticks: int = 20,
                 stop_distance: float = 0.20, log=None):
        assert adapter in ("shadow", "demo", "live")
        self.strategy_name = strategy
        self.strategy = REGISTRY[strategy]
        self.params = params or {}
        self.policy = policy or PROFILES["balanced"]
        self.adapter = adapter
        self.universe = tuple(universe)
        self.client = client or MarginClient("demo" if adapter == "demo" else "prod")
        # One engine per BOOK. `book=None` keeps the legacy unsuffixed paths, so
        # the incumbent's state, status and decision history carry on unbroken;
        # a named book gets its own three files and cannot touch them. Two books
        # running side by side is how the promotion gate in docs/KALSHI_PERPS.md
        # compares a candidate against the incumbent on the same live prices.
        self.book_name = book
        suffix = f"_{book}" if book else ""
        self.state_path = state_path or os.path.join(STATE_DIR, f"perps_paper_state{suffix}.json")
        self.status_path = os.path.join(STATE_DIR, f"perps_desk_status{suffix}.json")
        self.decisions_path = os.path.join(STATE_DIR, f"perps_decisions{suffix}.jsonl")
        self.rebalance_every_days = rebalance_every_days
        # The band stops volatility drift from trading, and only works if ONE
        # weight step is bigger than it. On a wide book the step scales down
        # (0.05 x 4/n) while a fixed 0.03 does not, so most legs never clear it:
        # a 20-name blend wanting 1-2% per alt would hold only its four core
        # legs and quietly stop being the strategy it claims to be. "auto"
        # scales the band with the universe and is exactly 0.03 at four names.
        self.band = resolve_band(band, len(self.universe))
        self.slack_ticks = slack_ticks
        self.stop_distance = stop_distance
        self.log = log or (lambda *a: None)
        self.book = self._load() or Book.new(adapter, bankroll)
        self.taker_fee, self.maker_fee = fee_rates(0.0)
        self._marks: dict[str, float] = {}
        self._quotes: dict[str, PerpQuote] = {}

    # ------------------------------------------------------------ persistence
    def _load_paper_state(self) -> Book | None:
        try:
            with open(self.state_path) as f:
                d = json.load(f)
            if d.get("adapter") != self.adapter:
                return None
            return Book(**d)
        except (FileNotFoundError, TypeError, json.JSONDecodeError):
            return None

    def _load(self) -> Book | None:
        return self._load_paper_state() or book_from_status_file(self.status_path, self.adapter)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        self.book.updated = _now_iso()
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(self.book), f, indent=1)
        os.replace(tmp, self.state_path)

    def decision(self, kind: str, **kw) -> None:
        rec = {"ts": _now_iso(), "kind": kind, "adapter": self.adapter, **kw}
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(self.decisions_path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        self.log(f"[{rec['ts']}] {kind} {kw}")

    # ---------------------------------------------------------------- marks
    def ticker_for(self, asset: str) -> str:
        t = SPECS[asset].ticker
        return t + "1" if self.adapter == "demo" else t   # demo lists KX...PERP1

    def refresh_marks(self) -> None:
        mk = {m["ticker"]: m for m in self.client.markets()}
        for a in self.universe:
            t = self.ticker_for(a)
            m = mk.get(t)
            if not m:
                continue
            sm = (m.get("settlement_mark_price") or {}).get("price") or m.get("price")
            if sm:
                self._marks[a] = float(sm)
            try:
                self._quotes[a] = self.client.quote(t)
            except KalshiApiError as e:
                self.decision("quote_error", asset=a, error=str(e))

    def mark(self, a: str) -> float | None:
        return self._marks.get(a)

    # --------------------------------------------------------------- equity
    def positions(self) -> dict[str, Position]:
        return {a: Position(**p) for a, p in self.book.positions.items()}

    def equity(self) -> float:
        eq = self.book.cash
        for a, p in self.positions().items():
            m = self.mark(a) or p.avg_price
            eq += p.contracts * (m - p.avg_price) + 0.0  # unrealized; margin sits in cash
        return eq

    def weights(self) -> dict[str, float]:
        eq = max(self.equity(), 1e-9)
        return {a: p.contracts * (self.mark(a) or p.avg_price) / eq for a, p in self.positions().items()}

    # -------------------------------------------------------------- accruals
    def accrue_funding(self) -> None:
        for a, p in self.positions().items():
            if p.contracts == 0:
                continue
            since = self.book.last_funding_ts.get(a)
            try:
                rows = self.client.funding_history(SPECS[a].ticker)
            except KalshiApiError as e:
                self.decision("funding_error", asset=a, error=str(e))
                continue
            rows = sorted(rows, key=lambda r: r["funding_time"])
            newest = since
            for r in rows:
                ft = r["funding_time"]
                if since and ft <= since:
                    continue
                if ft <= p.opened:
                    newest = max(newest or "", ft)
                    continue
                rate = float(r["funding_rate"])
                mark = float(r["mark_price"])
                pay = -p.contracts * mark * rate       # long pays when positive
                self.book.cash += pay
                self.book.funding += pay
                newest = max(newest or "", ft)
                if rate != 0:
                    self.decision("funding", asset=a, rate=rate, paid=round(pay, 4), funding_time=ft)
            if newest:
                self.book.last_funding_ts[a] = newest

    def accrue_interest(self) -> None:
        now = time.time()
        dt_s = max(0.0, now - (self.book.last_interest_ts or now))
        if dt_s <= 0:
            self.book.last_interest_ts = now
            return
        im_used = sum(abs(p.contracts) * (self.mark(a) or p.avg_price) * SPECS[a].initial_rate
                      for a, p in self.positions().items())
        free = max(self.equity() - im_used, 0.0)
        inc = free * COLLATERAL_APY * dt_s / (365 * 86400)
        self.book.cash += inc
        self.book.interest += inc
        self.book.last_interest_ts = now

    def roll_day(self) -> None:
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        week = dt.datetime.now(dt.timezone.utc).strftime("%G-W%V")
        eq = self.equity()
        if self.book.day != today:
            self.book.day, self.book.day_start_equity = today, eq
        if self.book.week != week:
            self.book.week, self.book.week_start_equity = week, eq
        self.book.peak_equity = max(self.book.peak_equity, eq)

    # ---------------------------------------------------------- reconcile
    def reconcile(self) -> bool:
        """Venue truth vs local book (demo/live). Any mismatch halts."""
        if self.adapter == "shadow" or not self.client.can_trade:
            return True
        try:
            venue = {p["market_ticker"]: float(p["position"]) for p in self.client.positions()}
        except KalshiApiError as e:
            self.decision("reconcile_error", error=str(e))
            return False
        ok = True
        for a in self.universe:
            t = self.ticker_for(a)
            mine = self.book.positions.get(a, {}).get("contracts", 0.0)
            theirs = venue.get(t, 0.0)
            if abs(mine - theirs) > 0.5:
                ok = False
                self.decision("reconcile_mismatch", asset=a, local=mine, venue=theirs)
        if not ok:
            self.book.halted = "reconcile_mismatch"
        return ok

    # -------------------------------------------------------------- targets
    def targets(self) -> tuple[dict[str, float], float]:
        panel = D.load_panel(self.universe)
        last = max(d.index[-1] for d in panel.values())
        age_h = (pd.Timestamp.now(tz="UTC") - last).total_seconds() / 3600
        W = self.strategy(panel, **self.params)
        w = W.iloc[-1].to_dict()
        w = cap_weights(pd.DataFrame([w]), self.policy.max_gross_leverage, self.policy.max_asset_weight,
                        self.policy.min_liq_distance).iloc[0].to_dict()
        scale = ladder_scale(self.equity(), self.book.peak_equity, self.policy)
        return {a: float(v) * scale for a, v in w.items()}, age_h

    # -------------------------------------------------------------- orders
    def _fill_shadow(self, a: str, side: str, contracts: float) -> tuple[float, float] | None:
        q = self._quotes.get(a)
        if not q or q.bid is None or q.ask is None:
            return None
        px = float(q.ask if side == "bid" else q.bid)
        fee = abs(contracts) * px * self.taker_fee
        return px, fee

    def _fill_venue(self, a: str, side: str, contracts: float, reduce_only: bool) -> tuple[float, float] | None:
        q = self._quotes.get(a)
        spec = SPECS[a]
        if not q:
            return None
        price = banded_price(side, q.bid, q.ask, spec.tick, self.slack_ticks)
        if price is None or not inside_band(side, price, q.bid, q.ask, spec.tick):
            self.decision("skip_band", asset=a, side=side)
            return None
        coid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"perps/{self.book.day}/{a}/{side}/{self.book.n_ticks}"))
        self.decision("order_intent", asset=a, side=side, contracts=contracts, price=str(price), client_order_id=coid)
        try:
            resp = self.client.create_order(self.ticker_for(a), side, Decimal(str(abs(contracts))), price,
                                            time_in_force="immediate_or_cancel", reduce_only=reduce_only,
                                            client_order_id=coid)
        except KalshiApiError as e:
            self.decision("order_error", asset=a, error=str(e), client_order_id=coid)
            self.book.halted = "order_error_in_doubt" if e.status == 0 else ""
            return None
        filled = float(resp.get("fill_count") or 0)
        if filled <= 0:
            self.decision("no_fill", asset=a, side=side, resp=resp)
            return None
        px = float(resp.get("average_fill_price") or price)
        fee = float(resp.get("average_fee_paid") or 0) * filled
        return px, fee, filled

    def _apply_fill(self, a: str, side: str, contracts: float, px: float, fee: float) -> None:
        pos = self.positions().get(a) or Position(a, self.ticker_for(a), 0.0, px, _now_iso())
        signed = contracts if side == "bid" else -contracts
        # realized P&L on the closing part
        if pos.contracts != 0 and (pos.contracts > 0) != (signed > 0):
            closing = min(abs(pos.contracts), abs(signed))
            pnl = closing * (px - pos.avg_price) * (1 if pos.contracts > 0 else -1)
            self.book.cash += pnl
            self.book.realized += pnl
        new = pos.contracts + signed
        if new == 0:
            self.book.positions.pop(a, None)
        else:
            if pos.contracts == 0 or (pos.contracts > 0) == (new > 0) and abs(new) > abs(pos.contracts):
                # adding: blend the average price on the added part
                added = abs(new) - abs(pos.contracts) if pos.contracts != 0 else abs(new)
                base = abs(pos.contracts)
                avg = (pos.avg_price * base + px * added) / (base + added) if base + added > 0 else px
            else:
                avg = pos.avg_price if (pos.contracts > 0) == (new > 0) else px
            self.book.positions[a] = asdict(Position(a, self.ticker_for(a), new, avg,
                                                     pos.opened if pos.contracts != 0 else _now_iso()))
        self.book.cash -= fee
        self.book.fees += fee
        self.decision("fill", asset=a, side=side, contracts=contracts, price=px, fee=round(fee, 4),
                      position=new, cash=round(self.book.cash, 2))

    def protect(self) -> None:
        """Server-side stop under every venue position (demo/live)."""
        if self.adapter == "shadow" or not self.client.can_trade:
            return
        for a, p in self.positions().items():
            m = self.mark(a)
            if not m or p.contracts == 0:
                continue
            stop = m * (1 - self.stop_distance) if p.contracts > 0 else m * (1 + self.stop_distance)
            try:
                self.client.set_bracket(self.ticker_for(a), stop_loss_price=Decimal(str(round(stop, 4))),
                                        mode="cross")
            except KalshiApiError as e:
                self.decision("bracket_error", asset=a, error=str(e))

    # ----------------------------------------------------------------- tick
    def tick(self) -> list[str]:
        notes: list[str] = []
        self.book.n_ticks += 1
        if kill_switch_tripped():
            self.book.halted = "kill_switch"
            notes.append("halted: KILL_SWITCH_PERPS")
            self.save()
            return notes
        if self.book.halted == "kill_switch":
            self.book.halted = ""
            notes.append("resumed: kill switch lifted")
            self.decision("resumed", reason="kill_switch_lifted")
        try:
            st = self.client.exchange_status()
        except KalshiApiError as e:
            notes.append(f"exchange status error: {e}")
            return notes
        if not (st.get("exchange_active") and st.get("trading_active")):
            notes.append("venue paused; no orders")
            return notes
        self.refresh_marks()
        if not self.reconcile():
            notes.append("HALT: reconcile mismatch")
            self.save()
            return notes
        self.accrue_funding()
        self.accrue_interest()
        self.roll_day()
        eq = self.equity()
        if self.book.halted and self.book.halted != "kill_switch":
            notes.append(f"halted: {self.book.halted}")
            self.save()
            return notes
        # drawdown kill: flatten everything and trip the switch
        if ladder_scale(eq, self.book.peak_equity, self.policy) == 0.0 and self.positions():
            for a, p in self.positions().items():
                self._trade(a, -p.contracts, reduces_risk=True, eq=eq, age_h=0.0, reason="dd_kill")
            trip_kill_switch(f"perps drawdown {eq / self.book.peak_equity - 1:.2%} from peak")
            notes.append("DRAWDOWN KILL: flattened and tripped KILL_SWITCH_PERPS")
            self.save()
            return notes
        # weekly rebalance check (a flatten never waits)
        today = self.book.day
        due = (not self.book.last_rebalance_day or
               (dt.date.fromisoformat(today) - dt.date.fromisoformat(self.book.last_rebalance_day)).days
               >= self.rebalance_every_days)
        try:
            tgt, age_h = self.targets()
        except FileNotFoundError as e:
            notes.append(f"no data: {e}")
            return notes
        cur = self.weights()
        self.decision("targets", targets={k: round(v, 3) for k, v in tgt.items()},
                      held={k: round(v, 3) for k, v in cur.items()}, equity=round(eq, 2),
                      data_age_h=round(age_h, 1), rebalance_due=due)
        n_orders = 0
        for a in self.universe:
            t = tgt.get(a, 0.0)
            c = cur.get(a, 0.0)
            reduces = abs(t) < abs(c) - 1e-9 and (t == 0 or (t > 0) == (c > 0))
            if abs(t - c) <= self.band and not reduces:
                continue
            if not due and not reduces:
                continue
            m = self.mark(a)
            if not m:
                continue
            target_contracts = int(t * eq / m)
            delta = target_contracts - int(round(self.positions().get(a, Position(a, "", 0, 0, "")).contracts))
            if delta == 0:
                continue
            if self._trade(a, delta, reduces_risk=reduces, eq=eq, age_h=age_h, reason="rebalance",
                           weights_after={**cur, a: t}, n_orders=n_orders):
                n_orders += 1
        if due and n_orders >= 0:
            self.book.last_rebalance_day = today
        self.protect()
        self.save()
        write_status(self)
        notes.append(f"equity {eq:.2f} weights {{{', '.join(f'{k}:{v:+.2f}' for k, v in self.weights().items())}}} "
                     f"orders {n_orders}")
        return notes

    def _trade(self, a: str, delta_contracts: float, *, reduces_risk: bool, eq: float, age_h: float,
               reason: str, weights_after: dict | None = None, n_orders: int = 0) -> bool:
        side = "bid" if delta_contracts > 0 else "ask"
        m = self.mark(a) or 0.0
        notional = abs(delta_contracts) * m
        q = self._quotes.get(a)
        limit = float(banded_price(side, q.bid, q.ask, SPECS[a].tick, self.slack_ticks) or 0) if q else None
        v = check_pre_trade(self.policy, equity_usd=eq, peak_equity_usd=self.book.peak_equity,
                            order_notional_usd=notional, weights_after=weights_after or self.weights(),
                            data_age_hours=age_h,
                            day_pnl_frac=(eq / self.book.day_start_equity - 1) if self.book.day_start_equity else 0.0,
                            week_pnl_frac=(eq / self.book.week_start_equity - 1) if self.book.week_start_equity else 0.0,
                            mark=m, limit_price=limit, reduces_risk=reduces_risk, n_orders_this_tick=n_orders)
        if v:
            self.decision("blocked", asset=a, side=side, contracts=delta_contracts, violations=v, reason=reason)
            return False
        if self.adapter == "shadow" or not self.client.can_trade:
            f = self._fill_shadow(a, side, abs(delta_contracts))
            if not f:
                self.decision("no_quote", asset=a)
                return False
            px, fee = f
            self._apply_fill(a, side, abs(delta_contracts), px, fee)
            return True
        r = self._fill_venue(a, side, abs(delta_contracts), reduce_only=reduces_risk)
        if not r:
            return False
        px, fee, filled = r
        self._apply_fill(a, side, filled, px, fee)
        return True


def write_status(engine: PaperEngine) -> dict:
    b = engine.book
    eq = engine.equity()
    status = {
        "ts": _now_iso(), "book": engine.book_name or "incumbent",
        "adapter": engine.adapter, "strategy": engine.strategy_name,
        "universe": list(engine.universe), "profile": asdict(engine.policy),
        "bankroll0": b.bankroll0, "equity": round(eq, 2), "cash": round(b.cash, 2),
        "realized": round(b.realized, 2), "fees": round(b.fees, 4), "funding": round(b.funding, 4),
        "interest": round(b.interest, 4), "peak_equity": round(b.peak_equity, 2),
        "drawdown": round(eq / b.peak_equity - 1, 4) if b.peak_equity else 0.0,
        "positions": [{**p, "mark": engine.mark(a), "weight": round(w, 4)}
                      for (a, p), w in zip(b.positions.items(), engine.weights().values())],
        "gross_leverage": round(sum(abs(w) for w in engine.weights().values()), 3),
        "halted": b.halted, "kill_switch": kill_switch_tripped(), "n_ticks": b.n_ticks,
        "started": b.started,
    }
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(engine.status_path, "w") as f:
        json.dump(status, f, indent=1)
    return status
