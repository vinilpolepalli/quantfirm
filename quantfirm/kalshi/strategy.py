"""Pre-registered decision rule for the 15M metals desk ("oracle repricer").

Economic rationale (registered before backtesting, per firm convention):
the binary's strike is the window-open Pyth print and is public; a ~1 bp
accurate real-time proxy of the same index exists (Swissquote XAU/XAG); much
of the flow on these markets is slower/retail. When the underlying moves,
quotes lag or under-adjust, so the executable price can sit several cents
from model fair value. We take ONLY those displacements, as taker, and hold
to settlement (maker fee $0 / no settlement fee means one taker fee is the
entire cost). Near expiry delta explodes, so small spot moves create large,
verifiable mispricings.

Trade trigger (S1/S3 share this rule; tags differ):
    edge_yes = fair - ask - fee(ask);  edge_no = bid - fair - fee(1-bid)
    enter iff max(edge) >= theta, tau in [tau_min, tau_max], price in
    [price_min, price_max], spread <= max_spread, no macro blackout,
    concurrency + bankroll caps pass.

Sizing: kelly_mult * Kelly on (model q, all-in cost), capped at
max_stake_frac of current bankroll, integer contracts, min lot min_count.

Risk: max_open positions across metals; correlated-direction cap (gold and
silver same-direction count as one slot); daily loss stop halts entries for
the UTC day. Changing ANY constant here is a strategy change and belongs in
a reviewed commit, never a live session.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .fair import fair_yes, kelly_fraction, taker_fee


@dataclass(frozen=True)
class Params:
    theta: float = 0.05           # net edge threshold, dollars/contract
    vol_halflife_min: float = 30.0
    diurnal: bool = True
    tau_min_s: int = 120          # no entries in the last 2 minutes
    tau_max_s: int = 780          # no entries in the first 2 minutes
    price_min: float = 0.08
    price_max: float = 0.92
    max_spread: float = 0.05
    kelly_mult: float = 0.25
    max_stake_frac: float = 0.05  # of current bankroll per trade
    min_count: int = 10
    max_open: int = 2
    daily_stop_frac: float = 0.10  # halt entries for the UTC day at -10%
    macro_blackout_et: tuple = ((8, 30), (14, 0))  # ET (hour, minute)
    macro_blackout_pad_s: int = 300
    signal_max_age_s: int = 150   # stale underlying bar -> no decision
    slippage_extra: float = 0.0   # extra dollars/contract on entry (stress)
    # Backtest fill model (see backtest.py). "touch" = optimistic zero-latency
    # ceiling (fill at next-candle open if <= limit). "lag" = realistic floor
    # for a slow taker: fill ONLY when the level survived the whole fill minute
    # (uncontested), at that minute's side-price close, and cap size at the
    # minute's traded volume. The adversarial review showed candle opens are
    # carry-forward quotes, so "touch" is NOT conservative; report both.
    fill_mode: str = "touch"
    min_recent_volume: float = 100.0  # contracts traded in last 3 min; proxies
    # real counterparties. Live equivalent: size at the touch >= our count.
    # Regime condition on WHERE the divergence came from (3-min lookback):
    #   'off'        — take any divergence >= theta
    #   'flow_only'  — contract price moved (>=4c) while fair was calm (<1.5c):
    #                  fade uninformed flow (the Turbine-surviving archetype)
    #   'stale_only' — fair moved (>=4c) while the contract lagged (<1.5c):
    #                  classic stale-quote repricing
    flow_gate: str = "off"

    def blackout(self, ts: int) -> bool:
        """True if ts (unix) is within pad of a macro-release ET time."""
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # ET = UTC-4 (EDT). Metals macro prints matter Mar-Nov; EDT is correct
        # for the current backtest window. Revisit at DST change.
        et_h, et_m = (dt.hour - 4) % 24, dt.minute
        sec = et_h * 3600 + et_m * 60 + dt.second
        for h, m in self.macro_blackout_et:
            if abs(sec - (h * 3600 + m * 60)) <= self.macro_blackout_pad_s:
                return True
        return False


@dataclass
class Intent:
    """One order the strategy wants: buy `side` at `limit_price` (side-price)."""

    ticker: str
    side: str            # 'yes' | 'no'
    count: int
    limit_price: float   # price of the side being bought, dollars
    fair: float          # model P(yes)
    edge: float          # expected net dollars/contract at limit_price
    tag: str             # 'stale' | 'flow'
    tau_s: float


def decide(*, ticker: str, ts: int, s: float, k: float, sigma_1m: float,
           close_ts: int, yes_bid: float | None, yes_ask: float | None,
           bankroll: float, open_positions: int, params: Params,
           recent_fair_move: float = 0.0, recent_mkt_move: float = 0.0,
           recent_volume: float | None = None,
           ) -> Intent | None:
    """Evaluate one market at one instant. Pure function, no I/O."""
    p = params
    tau_s = close_ts - ts
    if not (p.tau_min_s <= tau_s <= p.tau_max_s):
        return None
    if yes_bid is None or yes_ask is None:
        return None
    if recent_volume is not None and recent_volume < p.min_recent_volume:
        return None
    spread = yes_ask - yes_bid
    if spread < 0 or spread > p.max_spread:
        return None
    if open_positions >= p.max_open:
        return None
    if p.blackout(ts):
        return None

    fair = fair_yes(s, k, sigma_1m, tau_s / 60.0)

    is_flow = abs(recent_mkt_move) >= 0.04 and abs(recent_fair_move) < 0.015
    is_stale = abs(recent_fair_move) >= 0.04 and abs(recent_mkt_move) < 0.015
    if p.flow_gate == "flow_only" and not is_flow:
        return None
    if p.flow_gate == "stale_only" and not is_stale:
        return None

    # YES leg: pay yes_ask (+stress), win $1 with prob fair
    # NO leg:  pay 1-yes_bid (+stress), win $1 with prob 1-fair
    cands = []
    ask_eff = yes_ask + p.slippage_extra
    if p.price_min <= yes_ask <= p.price_max:
        edge = fair - ask_eff - taker_fee(1, ask_eff)
        cands.append(("yes", ask_eff, fair, edge))
    no_price = 1.0 - yes_bid
    no_eff = no_price + p.slippage_extra
    if p.price_min <= no_price <= p.price_max:
        edge = (1.0 - fair) - no_eff - taker_fee(1, no_eff)
        cands.append(("no", no_eff, 1.0 - fair, edge))
    side, cost, q, edge = max(cands, key=lambda c: c[3], default=(None, 0, 0, -1))
    if side is None or edge < p.theta:
        return None

    # Kelly on the ALL-IN cost (price + per-contract fee), per the registered
    # spec f* = (q - a)/(1 - a), a = price + fee/contract.
    all_in = cost + taker_fee(1, cost)
    f = p.kelly_mult * kelly_fraction(q, all_in)
    stake = min(f, p.max_stake_frac) * bankroll
    count = int(stake / cost)
    if count < p.min_count:
        return None

    tag = "flow" if is_flow else ("stale" if is_stale else "mixed")
    limit = cost - p.slippage_extra  # book the stress in the fill, not the order
    return Intent(ticker=ticker, side=side, count=count,
                  limit_price=round(limit, 4), fair=fair, edge=edge,
                  tag=tag, tau_s=tau_s)
