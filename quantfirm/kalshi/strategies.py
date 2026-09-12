"""Pre-registered 15-minute commodity strategies.

Each function has the same signature as ``strategy.decide`` plus ignored
``**kwargs`` so the backtest can pass extra snapshot fields. Parameters are
frozen here — sweeping them on the test split is a new registered trial.

Economic priors (external, not fit on this sample):
  * Whelan et al. 2025: Kalshi favorites (≥50¢) earn, longshots lose;
    makers beat takers. 15-minute metals were not in that sample.
  * Prior desk (docs/KALSHI.md): REST-latency taker stale-quote sniping
    loses (winner's curse). First ~3 minutes and longshot buys lose.
  * OddsShopper 2026-09-11: 15-minute books reprice off the settlement
    index within seconds; the remaining edge is the spread, i.e. making.
  * PredictionMarketsPicks: no 15-minute options IV; fair value is
    driftless GBM + realized vol; quadratic fee is the cost wall.

Strategies that ignore those priors (always-yes, coin-flip) are CONTROLS.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .fair import fair_yes, implied_sigma_1m, kelly_fraction, taker_fee
from .strategy import Intent, Params, decide


def _size(ticker, side, cost, q, edge, fair, tau_s, bankroll, params, tag,
          allow_min: bool = False) -> Intent | None:
    if cost <= 0 or cost >= 1:
        return None
    all_in = cost + taker_fee(1, cost)
    f = params.kelly_mult * kelly_fraction(q, all_in)
    stake = min(max(f, 0.0), params.max_stake_frac) * bankroll
    count = int(stake / cost)
    if count < params.min_count:
        # Structural signals (FLB / late lock) can have a thin assumed edge
        # after the quadratic fee. On a $250 book Kelly then undershoots
        # min_count; take the minimum lot if it still fits the stake cap.
        if allow_min and params.min_count * cost <= params.max_stake_frac * bankroll:
            count = params.min_count
        else:
            return None
    return Intent(ticker=ticker, side=side, count=count,
                  limit_price=round(cost, 4), fair=fair, edge=edge,
                  tag=tag, tau_s=tau_s)


def _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params,
           recent_volume=None) -> tuple[float, float] | None:
    tau_s = close_ts - ts
    if not (params.tau_min_s <= tau_s <= params.tau_max_s):
        return None
    if yes_bid is None or yes_ask is None:
        return None
    if recent_volume is not None and recent_volume < params.min_recent_volume:
        return None
    spread = yes_ask - yes_bid
    if spread < 0 or spread > params.max_spread:
        return None
    if open_positions >= params.max_open:
        return None
    if params.blackout(ts):
        return None
    return tau_s, spread


def oracle(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask, bankroll,
           open_positions, params, recent_fair_move=0.0, recent_mkt_move=0.0,
           recent_volume=None, **_):
    """Registered stale-quote / flow taker from strategy.decide."""
    return decide(ticker=ticker, ts=ts, s=s, k=k, sigma_1m=sigma_1m,
                  close_ts=close_ts, yes_bid=yes_bid, yes_ask=yes_ask,
                  bankroll=bankroll, open_positions=open_positions, params=params,
                  recent_fair_move=recent_fair_move, recent_mkt_move=recent_mkt_move,
                  recent_volume=recent_volume)


def favorite_blind(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                   bankroll, open_positions, params, recent_volume=None, **_):
    """Buy the market favorite (side priced ≥ price_min) and hold.

    No model. Tests whether Whelan's favorite-longshot bias exists on
    15-minute commodities after the quadratic taker fee.
    """
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    cands = []
    if params.price_min <= yes_ask <= params.price_max:
        q = min(0.97, yes_ask + 0.03)  # assumed 3pp FLB, not a forecast
        edge = q - yes_ask - taker_fee(1, yes_ask)
        cands.append(("yes", yes_ask, q, edge, yes_ask))
    no_px = 1.0 - yes_bid
    if params.price_min <= no_px <= params.price_max:
        q = min(0.97, no_px + 0.03)
        edge = q - no_px - taker_fee(1, no_px)
        cands.append(("no", no_px, q, edge, 1.0 - no_px))
    if not cands:
        return None
    side, cost, q, edge, fair = max(cands, key=lambda c: c[1])  # richer favorite
    if cost < params.price_min:
        return None
    return _size(ticker, side, cost, q, edge, fair, tau_s, bankroll, params,
                 "favorite", allow_min=True)


def favorite_confirmed(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                       bankroll, open_positions, params, recent_volume=None, **_):
    """Favorite taker only when the driftless GBM agrees on the side."""
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    fair = fair_yes(s, k, sigma_1m, tau_s / 60.0)
    fair = min(max(fair, params.prob_clamp), 1.0 - params.prob_clamp)
    if fair >= 0.62 and params.price_min <= yes_ask <= params.price_max:
        edge = fair - yes_ask - taker_fee(1, yes_ask)
        if edge >= 0.0:
            return _size(ticker, "yes", yes_ask, fair, edge, fair, tau_s,
                         bankroll, params, "fav_conf", allow_min=True)
    no_px = 1.0 - yes_bid
    if fair <= 0.38 and params.price_min <= no_px <= params.price_max:
        q = 1.0 - fair
        edge = q - no_px - taker_fee(1, no_px)
        if edge >= 0.0:
            return _size(ticker, "no", no_px, q, edge, fair, tau_s,
                         bankroll, params, "fav_conf", allow_min=True)
    return None


def late_lock(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
              bankroll, open_positions, params, recent_volume=None, **_):
    """Buy a near-certain favorite in the last few minutes.

    Latency is less lethal here: reversing a 2-sigma displacement in 3
    minutes is rare, so a REST-latency fill still usually settles our way.
    Fees shrink in the wings (0.63¢ at 90¢ vs 1.75¢ at 50¢).
    """
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    fair = fair_yes(s, k, sigma_1m, tau_s / 60.0)
    fair = min(max(fair, params.prob_clamp), 1.0 - params.prob_clamp)
    # require both model certainty AND a still-cheap-enough book
    if fair >= 0.88 and yes_ask <= 0.96:
        edge = fair - yes_ask - taker_fee(1, yes_ask)
        if edge >= params.theta:
            return _size(ticker, "yes", yes_ask, fair, edge, fair, tau_s,
                         bankroll, params, "late_lock", allow_min=True)
    no_px = 1.0 - yes_bid
    if fair <= 0.12 and no_px <= 0.96:
        q = 1.0 - fair
        edge = q - no_px - taker_fee(1, no_px)
        if edge >= params.theta:
            return _size(ticker, "no", no_px, q, edge, fair, tau_s,
                         bankroll, params, "late_lock", allow_min=True)
    return None


def open_fade(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
              bankroll, open_positions, params, recent_volume=None,
              f_now=None, f_open=None, open_ts=None, **_):
    """Fade a large first-3-minute underlying move for the rest of the window.

    Short-horizon commodity microstructure often mean-reverts after an
    opening impulse (inventory / stop-run). If the first 3 minutes ran
    ≥15 bp, bet the remaining 12 minutes go the other way.
    """
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None or f_now is None or f_open is None or not f_open:
        return None
    tau_s, _ = g
    if open_ts is not None and ts < open_ts + 240:
        return None  # wait for the 3-minute print
    move = (f_now / f_open) - 1.0
    if abs(move) < 0.0015:
        return None
    # fade: up open -> buy NO; down open -> buy YES
    if move > 0:
        no_px = 1.0 - yes_bid
        if not (params.price_min <= no_px <= params.price_max):
            return None
        # weak prior: 55% that the fade works
        q, cost, side = 0.55, no_px, "no"
        fair = 1.0 - q
    else:
        if not (params.price_min <= yes_ask <= params.price_max):
            return None
        q, cost, side = 0.55, yes_ask, "yes"
        fair = q
    edge = q - cost - taker_fee(1, cost)
    if edge < 0:
        return None
    return _size(ticker, side, cost, q, edge, fair, tau_s, bankroll, params,
                 "open_fade", allow_min=True)


def open_follow(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                bankroll, open_positions, params, recent_volume=None,
                f_now=None, f_open=None, open_ts=None, **_):
    """Opposite of open_fade: follow a ≥15 bp first-3-minute impulse."""
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None or f_now is None or f_open is None or not f_open:
        return None
    tau_s, _ = g
    if open_ts is not None and ts < open_ts + 240:
        return None
    move = (f_now / f_open) - 1.0
    if abs(move) < 0.0015:
        return None
    if move > 0:
        if not (params.price_min <= yes_ask <= params.price_max):
            return None
        q, cost, side, fair = 0.55, yes_ask, "yes", 0.55
    else:
        no_px = 1.0 - yes_bid
        if not (params.price_min <= no_px <= params.price_max):
            return None
        q, cost, side, fair = 0.55, no_px, "no", 0.45
    edge = q - cost - taker_fee(1, cost)
    if edge < 0:
        return None
    return _size(ticker, side, cost, q, edge, fair, tau_s, bankroll, params,
                 "open_follow", allow_min=True)


def session_favorite(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                     bankroll, open_positions, params, recent_volume=None, **kw):
    """Favorite-confirmed only in the London/NY overlap (12:00–17:00 UTC)."""
    hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
    if not (12 <= hour < 17):
        return None
    return favorite_confirmed(ticker, ts, s, k, sigma_1m, close_ts, yes_bid,
                              yes_ask, bankroll, open_positions, params,
                              recent_volume=recent_volume, **kw)


def iv_rich_favorite(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                     bankroll, open_positions, params, recent_volume=None, **_):
    """If the book implies more vol than we have realized, buy the favorite.

    High implied vol cheapens the favorite relative to a realized-vol GBM.
    Unstable when S≈K, so we require |ln(S/K)| ≥ 8 bp.
    """
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    if s <= 0 or k <= 0 or abs(__import__("math").log(s / k)) < 0.0008:
        return None
    mid = (yes_bid + yes_ask) / 2
    sig_imp = implied_sigma_1m(s, k, mid, tau_s / 60.0)
    if sig_imp is None or sigma_1m <= 0 or sig_imp < 1.4 * sigma_1m:
        return None
    return favorite_confirmed(ticker, ts, s, k, sigma_1m, close_ts, yes_bid,
                              yes_ask, bankroll, open_positions, params,
                              recent_volume=recent_volume)


def always_yes(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
               bankroll, open_positions, params, recent_volume=None, **_):
    """Control: buy YES once per window around minute 5."""
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    # fire in a 60s band so we get one shot
    if not (600 <= tau_s < 660):
        return None
    if yes_ask is None or yes_ask <= 0 or yes_ask >= 0.99:
        return None
    return _size(ticker, "yes", yes_ask, 0.50, 0.50 - yes_ask, 0.50, tau_s,
                 bankroll, params, "ctrl_yes", allow_min=True)


def always_no(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
              bankroll, open_positions, params, recent_volume=None, **_):
    """Control: buy NO once per window around minute 5."""
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    if not (600 <= tau_s < 660):
        return None
    no_px = 1.0 - yes_bid
    if no_px <= 0 or no_px >= 0.99:
        return None
    return _size(ticker, "no", no_px, 0.50, 0.50 - no_px, 0.50, tau_s,
                 bankroll, params, "ctrl_no", allow_min=True)


def coin_flip(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
              bankroll, open_positions, params, recent_volume=None, **_):
    """Control: take the 45–55¢ YES ask. Should lose the fee + spread."""
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    if not (0.45 <= yes_ask <= 0.55):
        return None
    if not (540 <= tau_s < 600):
        return None
    return _size(ticker, "yes", yes_ask, 0.50, 0.50 - yes_ask, 0.50, tau_s,
                 bankroll, params, "ctrl_atm", allow_min=True)


@dataclass(frozen=True)
class Spec:
    name: str
    fn: Callable
    params: Params
    fill_mode: str
    note: str


def _p(**kw) -> Params:
    base = dict(
        kelly_mult=0.25,
        max_stake_frac=0.08,
        min_count=5,
        max_open=2,
        daily_stop_frac=0.10,
        max_spread=0.06,
        min_recent_volume=80.0,
        macro_blackout_et=((8, 30), (14, 0)),
        fill_mode="lag",
        slippage_extra=0.0,
    )
    base.update(kw)
    return Params(**base)


def registry() -> list[Spec]:
    """Frozen list. Adding a row is a new registered trial."""
    return [
        Spec("ctrl_always_yes", always_yes,
             _p(tau_min_s=120, tau_max_s=780, price_min=0.05, price_max=0.99,
                theta=0.0),
             "lag", "CONTROL: buy YES every window at minute 5"),
        Spec("ctrl_always_no", always_no,
             _p(tau_min_s=120, tau_max_s=780, price_min=0.05, price_max=0.99,
                theta=0.0),
             "lag", "CONTROL: buy NO every window at minute 5"),
        Spec("ctrl_coin_flip", coin_flip,
             _p(tau_min_s=120, tau_max_s=780, price_min=0.40, price_max=0.60,
                theta=0.0, max_spread=0.08),
             "lag", "CONTROL: take 45-55c YES; should lose fee+spread"),
        Spec("oracle_lag", oracle,
             _p(theta=0.07, vol_halflife_min=30.0, tau_min_s=300, tau_max_s=600,
                price_min=0.35, price_max=0.92, flow_gate="off"),
             "lag", "Prior-desk registered taker at realistic latency (known loser)"),
        Spec("oracle_flow", oracle,
             _p(theta=0.05, vol_halflife_min=30.0, tau_min_s=180, tau_max_s=720,
                price_min=0.30, price_max=0.92, flow_gate="flow_only"),
             "lag", "Fade uninformed book flow (REST-latency friendly in theory)"),
        Spec("favorite_blind", favorite_blind,
             _p(tau_min_s=180, tau_max_s=720, price_min=0.72, price_max=0.94,
                theta=0.0),
             "lag", "Whelan FLB: take favorites ≥72c, no model"),
        Spec("favorite_confirmed", favorite_confirmed,
             _p(tau_min_s=180, tau_max_s=720, price_min=0.68, price_max=0.94,
                theta=0.0),
             "lag", "FLB + GBM side agreement"),
        Spec("late_lock", late_lock,
             _p(theta=0.03, tau_min_s=90, tau_max_s=360, price_min=0.50,
                price_max=0.96, max_spread=0.08),
             "lag", "Near-certain favorite in last 6 minutes"),
        Spec("open_fade", open_fade,
             _p(tau_min_s=120, tau_max_s=660, price_min=0.20, price_max=0.85,
                theta=0.0),
             "lag", "Fade ≥15bp first-3-minute underlying impulse"),
        Spec("open_follow", open_follow,
             _p(tau_min_s=120, tau_max_s=660, price_min=0.20, price_max=0.85,
                theta=0.0),
             "lag", "Follow ≥15bp first-3-minute underlying impulse"),
        Spec("session_favorite", session_favorite,
             _p(tau_min_s=180, tau_max_s=720, price_min=0.68, price_max=0.94,
                theta=0.0),
             "lag", "Favorite-confirmed in London/NY overlap only"),
        Spec("iv_rich_favorite", iv_rich_favorite,
             _p(tau_min_s=180, tau_max_s=600, price_min=0.60, price_max=0.94,
                theta=0.0),
             "lag", "Buy favorite when book IV >> realized vol"),
    ]
