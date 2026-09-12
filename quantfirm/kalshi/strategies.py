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

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable

from .fair import fair_yes, implied_sigma_1m, kelly_fraction, taker_fee
from .strategy import Intent, Params, decide
from .universe import CRYPTO_LIVE


def _size(ticker, side, cost, q, edge, fair, tau_s, bankroll, params, tag,
          allow_min: bool = False, fill_cap: bool = False) -> Intent | None:
    if cost <= 0 or cost >= 1:
        return None
    if fill_cap:
        # Spend the stake cap (crypto: ~$10 each). Quarter-Kelly of a
        # 3pp assumed edge collapses to 4 lots at 72¢; BTC and ETH are
        # independent books, not a split budget.
        stake = params.max_stake_frac * bankroll
    else:
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
    # Fees count toward the cap so an 88¢ clip does not silently spend
    # more than the risk budget once the quadratic taker fee is added.
    cap = params.max_stake_frac * bankroll
    while count >= params.min_count and count * cost + taker_fee(count, cost) > cap + 1e-9:
        count -= 1
    if count < params.min_count:
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


def _fee_eats_payout(cost: float, max_fee_frac: float = 0.15,
                    min_net: float = 0.07) -> bool:
    """True when the quadratic taker fee leaves a junk payday.

    A priori from Kalshi's fee schedule, not a test-set fit. A 94¢
    fill pays 6¢ and the 1¢ ceil-fee is 17% of that. An 88¢ fill pays
    12¢; the same 1¢ fee is 8%. Skip the former.
    """
    win = 1.0 - cost
    if win <= 0:
        return True
    fee1 = taker_fee(1, cost)
    if fee1 > max_fee_frac * win:
        return True
    return (win - fee1) < min_net


def favorite_blind(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                   bankroll, open_positions, params, recent_volume=None,
                   fill_cap: bool = False, **_):
    """Buy the market favorite (side priced ≥ price_min) and hold.

    No model. Tests whether Whelan's favorite-longshot bias exists on
    15-minute commodities after the quadratic taker fee.

    Sit out only bad evidence: coin-flip (side < price_min), longshot /
    99¢ locks (price_max + fee-eat), empty or inverted book. One-sided
    and wide books still clip — requiring a two-sided 5¢ 88–94¢ band
    sat out whole windows that had a 60–90¢ favorite (03:45Z WTI ~70¢).
    If the richer side is fee-eat, fall through to the other favorite.
    """
    tau_s = close_ts - ts
    if not (params.tau_min_s <= tau_s <= params.tau_max_s):
        return None
    if open_positions >= params.max_open:
        return None
    if params.blackout(ts):
        return None
    if recent_volume is not None and recent_volume < params.min_recent_volume:
        return None
    if yes_bid is None and yes_ask is None:
        return None
    if (yes_bid is not None and yes_ask is not None and yes_ask < yes_bid):
        return None
    cands = []
    if yes_ask is not None and params.price_min <= yes_ask <= params.price_max:
        if not _fee_eats_payout(yes_ask):
            q = min(0.97, yes_ask + 0.03)  # assumed 3pp FLB, not a forecast
            edge = q - yes_ask - taker_fee(1, yes_ask)
            cands.append(("yes", yes_ask, q, edge, yes_ask))
    no_px = (1.0 - yes_bid) if yes_bid is not None else None
    if no_px is not None and params.price_min <= no_px <= params.price_max:
        if not _fee_eats_payout(no_px):
            q = min(0.97, no_px + 0.03)
            edge = q - no_px - taker_fee(1, no_px)
            cands.append(("no", no_px, q, edge, 1.0 - no_px))
    if not cands:
        return None
    side, cost, q, edge, fair = max(cands, key=lambda c: c[1])  # richer favorite
    return _size(ticker, side, cost, q, edge, fair, tau_s, bankroll, params,
                 "favorite", allow_min=True, fill_cap=fill_cap)


# Open flicker: a 60–64¢ favorite in the first 2–3 minutes often dies
# (13:15Z ETH NO T+19s @ 61¢ −$8.77). Sit the first 3 minutes, then clip
# ≥75¢ (1¢ mixed-book sweep: 60 red both names, 68 both-green, 75 the
# wait-3 peak; 72/74 dump ETH). No-wait 79¢ looks strong on ALL but
# weekend ETH still red and W37 BTC dies — keep the wait. Crypto also
# sits when Poly's ≥55¢ favorite disagrees. Missing Poly does not sit.
OPEN_WAIT_S = 180
CRYPTO_OPEN_WAIT_S = OPEN_WAIT_S
BTC_OPEN_WAIT_S = OPEN_WAIT_S


def crypto_params(base: Params) -> Params:
    """Chill crypto overlay: clip every window that has a real favorite.

    Same FLB bar as commodities (≥75¢). Stake is 4% of the book
    (~$9–10) **per name** — BTC and ETH are independent, not a split
    of one 4% budget. Quarter-Kelly of a 3pp assumed edge was collapsing
    72¢ clips to 4 lots (~$3). Coin-flips and 60–74¢ still sit.
    93¢+ stay out via fee-eat / price_max.
    """
    return replace(
        base,
        price_min=0.75,
        price_max=0.92,
        max_stake_frac=0.04,
        kelly_mult=0.25,
        tau_min_s=0,
        tau_max_s=900,
        min_count=4,
        max_spread=1.0,
        min_recent_volume=0.0,
        signal_max_age_s=0,
    )


def crypto_wait_params(base: Params, wait_s: int = OPEN_WAIT_S) -> Params:
    """4% crypto overlay plus a first-N-minute sit (default 3)."""
    return replace(crypto_params(base), tau_max_s=900 - wait_s)


def commodity_wait_params(base: Params, wait_s: int = OPEN_WAIT_S) -> Params:
    """8% commodity overlay plus the same first-N-minute sit."""
    return replace(base, tau_max_s=900 - wait_s)


def crypto_fav(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
               bankroll, open_positions, params, recent_volume=None, **kw):
    """Standalone BTC/ETH 15m FLB (for backtests). Same overlay as desk_book."""
    it = favorite_blind(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        fill_cap=True, **kw)
    if it is not None:
        it.tag = "crypto_fav"
    return it


def desk_book(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
              bankroll, open_positions, params, recent_volume=None,
              metal=None, poly_yes_bid=None, poly_yes_ask=None,
              poly_down_ask=None, wait_s=None, max_spread=None,
              mkt_move_max=None, price_min_ov=None, price_max_ov=None,
              tau_min_ov=None, skip_eth=False, **kw):
    """Commodity rich_fav + cautious BTC and ETH, both allowed.

    Whole book waits the first 3 minutes. Commodities: 8% / ≥75¢ after
    that (no Poly 15m book). BTC and ETH: 4% / ≥75¢ after the wait, and
    sit when Polymarket's 15m favorite disagrees. Names are independent:
    BTC YES and ETH NO in the same window is allowed. Missing Poly does
    not sit. Fee-eat still skips 93¢+ last ticks; 60–74¢ sits.
    """
    if skip_eth and metal == "eth":
        return None
    if max_spread is not None and yes_bid is not None and yes_ask is not None:
        if yes_ask - yes_bid > max_spread:
            return None
    if mkt_move_max is not None and abs(kw.get("recent_mkt_move") or 0) > mkt_move_max:
        return None
    wait = OPEN_WAIT_S if wait_s is None else wait_s
    if metal in CRYPTO_LIVE:
        p = crypto_wait_params(params, wait)
        if price_min_ov is not None:
            p = replace(p, price_min=price_min_ov)
        if price_max_ov is not None:
            p = replace(p, price_max=price_max_ov)
        if tau_min_ov is not None:
            p = replace(p, tau_min_s=tau_min_ov)
        it = favorite_blind(
            ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
            bankroll, open_positions, p,
            recent_volume=recent_volume, fill_cap=True, **kw)
        if it is None:
            return None
        if poly_yes_bid is not None or poly_yes_ask is not None:
            from .poly import PolyQuote, poly_favorite
            q = PolyQuote(asset=str(metal), slug="", up_bid=poly_yes_bid,
                           up_ask=poly_yes_ask, down_bid=None,
                           down_ask=poly_down_ask, ts=float(ts))
            side = poly_favorite(q, price_min=0.55)
            if side is None or side != it.side:
                return None
        it.tag = "crypto_fav"
        return it
    p = commodity_wait_params(params, wait)
    if price_min_ov is not None:
        p = replace(p, price_min=price_min_ov)
    if price_max_ov is not None:
        p = replace(p, price_max=price_max_ov)
    if tau_min_ov is not None:
        p = replace(p, tau_min_s=tau_min_ov)
    return favorite_blind(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, p,
        recent_volume=recent_volume, **kw)


def wait7_book(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
               bankroll, open_positions, params, recent_volume=None, **kw):
    """OSS hamad-khawaja observation phase: sit first 7 minutes, then desk_book."""
    return desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        wait_s=420, **kw)


def persist_book(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                  bankroll, open_positions, params, recent_volume=None, **kw):
    """OSS edge-persistence: sit a book that just ripped >8¢ in 3 min."""
    return desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        mkt_move_max=0.08, **kw)


def tight_book(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                bankroll, open_positions, params, recent_volume=None, **kw):
    """OSS spread filter: desk_book only when the book is ≤3¢ wide."""
    return desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        max_spread=0.03, **kw)


def late_sit_book(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                   bankroll, open_positions, params, recent_volume=None, **kw):
    """OSS hamad final phase: desk_book but no new entries in last 2 minutes."""
    return desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        tau_min_ov=120, **kw)


def richer_wait(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                 bankroll, open_positions, params, recent_volume=None, **kw):
    """Named alias for wait + 68¢. That is now the live desk_book bar."""
    return desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        price_min_ov=0.68, **kw)


def no_eth_book(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                 bankroll, open_positions, params, recent_volume=None, **kw):
    """desk_book with ETH off. ETH is the documented 15m hole."""
    return desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        skip_eth=True, **kw)


def settle_ride(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                 bankroll, open_positions, params, recent_volume=None,
                 metal=None, **kw):
    """OSS hamad settlement ride: last 5 min, ≥70¢ favorite, sit last 60s."""
    tau_s = close_ts - ts
    if not (60 <= tau_s <= 300):
        return None
    if metal in CRYPTO_LIVE:
        p = replace(crypto_params(params), tau_min_s=60, tau_max_s=300,
                     price_min=0.70)
        it = favorite_blind(
            ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
            bankroll, open_positions, p, recent_volume=recent_volume,
            fill_cap=True, **kw)
        if it is not None:
            it.tag = "settle_ride"
        return it
    p = replace(params, tau_min_s=60, tau_max_s=300, price_min=0.70)
    it = favorite_blind(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, p, recent_volume=recent_volume, **kw)
    if it is not None:
        it.tag = "settle_ride"
    return it


def longshot_no(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                 bankroll, open_positions, params, recent_volume=None, **kw):
    """OSS DanMcInerney longshot.yaml as a taker: YES 2–19¢ → buy NO (81–98¢)."""
    tau_s = close_ts - ts
    if not (params.tau_min_s <= tau_s <= params.tau_max_s):
        return None
    if yes_ask is None or yes_ask < 0.02 or yes_ask > 0.19:
        return None
    no_px = (1.0 - yes_bid) if yes_bid is not None else None
    if no_px is None or no_px < 0.81:
        return None
    if _fee_eats_payout(no_px):
        return None
    q = min(0.97, no_px + 0.03)
    edge = q - no_px - taker_fee(1, no_px)
    return _size(ticker, "no", no_px, q, edge, 1.0 - no_px, tau_s, bankroll,
                 params, "longshot_no", allow_min=True, fill_cap=True)


def dir_zone(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
               bankroll, open_positions, params, recent_volume=None, **kw):
    """OSS hamad directional zone: 7 min wait, trade 25–58¢ (NOT the favorite)."""
    return desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        wait_s=420, price_min_ov=0.25, price_max_ov=0.58, **kw)


def _book_favorite(yes_bid, yes_ask, price_min: float = 0.60) -> str | None:
    cands = []
    if yes_ask is not None and yes_ask >= price_min:
        cands.append(("yes", yes_ask))
    if yes_bid is not None and (1.0 - yes_bid) >= price_min:
        cands.append(("no", 1.0 - yes_bid))
    if not cands:
        return None
    return max(cands, key=lambda c: c[1])[0]


def same_side_book(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                    bankroll, open_positions, params, recent_volume=None,
                    metal=None, peer_yes_bid=None, peer_yes_ask=None, **kw):
    """Rejected reading of "win on both". Live wants each name's P&L,
    not side agreement — BTC YES and ETH NO in one window is allowed.
    This overlay sits disagreement and stays off the live loop.
    """
    it = desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        metal=metal, **kw)
    if it is None or metal not in CRYPTO_LIVE:
        return it
    if peer_yes_bid is None and peer_yes_ask is None:
        return None
    peer = _book_favorite(peer_yes_bid, peer_yes_ask, 0.60)
    if peer is None or peer != it.side:
        return None
    it.tag = "same_side"
    return it


def spot_desk(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                bankroll, open_positions, params, recent_volume=None, **kw):
    """desk_book only when spot agrees with the favorite (S vs K)."""
    it = desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume, **kw)
    if it is None:
        return it
    if s is None or k is None:
        return None
    if it.side == "yes" and s < k:
        return None
    if it.side == "no" and s >= k:
        return None
    it.tag = "spot_desk"
    return it


def poly_confirm(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                  bankroll, open_positions, params, recent_volume=None,
                  metal=None, poly_yes_bid=None, poly_yes_ask=None,
                  poly_down_ask=None, **kw):
    """desk_book, but crypto sits when Polymarket's 15m Up/Down disagrees.

    Missing Poly quote does not sit (feed outage ≠ a signal). Coin-flip
    on Poly (both sides <55¢) sits. Off the live loop until the logged
    basis is scored. Commodities have no Poly 15m book — pass through.
    """
    from .poly import PolyQuote, poly_favorite
    it = desk_book(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, params, recent_volume=recent_volume,
        metal=metal, poly_yes_bid=poly_yes_bid, poly_yes_ask=poly_yes_ask,
        poly_down_ask=poly_down_ask, **kw)
    if it is None or metal not in CRYPTO_LIVE:
        return it
    if poly_yes_bid is None and poly_yes_ask is None:
        return it
    q = PolyQuote(asset=str(metal), slug="", up_bid=poly_yes_bid,
                   up_ask=poly_yes_ask, down_bid=None, down_ask=poly_down_ask,
                   ts=float(ts))
    side = poly_favorite(q, price_min=0.55)
    if side is None or side != it.side:
        return None
    it.tag = "poly_confirm"
    return it


def poly_book(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
              bankroll, open_positions, params, recent_volume=None,
              metal=None, poly_yes_bid=None, poly_yes_ask=None,
              poly_down_ask=None, **kw):
    """Poly picks the side; Kalshi is the fill. Paper / compare sleeve.

    Not a locked arb (Chainlink TWAP ≠ CF last print). Rule:

      * crypto only (no Poly 15m gold/WTI)
      * missing Poly quote → sit (this sleeve *is* the Poly signal)
      * Poly must have a ≥60¢ favorite (Up=YES, Down=NO)
      * take that side on Kalshi only if Kalshi also has that side ≥60¢
        and not fee-eat
      * disagreement (Kalshi first favorite is the other way) → sit

    Same 4% crypto size. Off the live loop; compare to ``desk_book`` live
    fills by end of day before promoting.
    """
    from .poly import PolyQuote, poly_favorite
    if metal not in CRYPTO_LIVE:
        return None
    if poly_yes_bid is None and poly_yes_ask is None:
        return None
    q = PolyQuote(asset=str(metal), slug="", up_bid=poly_yes_bid,
                   up_ask=poly_yes_ask, down_bid=None, down_ask=poly_down_ask,
                   ts=float(ts))
    side = poly_favorite(q, price_min=0.60)
    if side is None:
        return None
    p = replace(crypto_params(params), price_min=params.price_min)
    it = favorite_blind(
        ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
        bankroll, open_positions, p,
        recent_volume=recent_volume, fill_cap=True, **kw)
    if it is None or it.side != side:
        return None
    it.tag = "poly_book"
    return it


def _size_lock(ticker, side, cost, fair, tau_s, bankroll, params, tag,
               target_frac: float = 0.01) -> Intent | None:
    """Size so a *win* is about ``target_frac`` of bankroll, capped by stake.

    At 90¢, 8% of $250 ≈ 22 contracts → about +$2.20 (0.9%) if it pays,
    −$20 if it doesn't. 99¢ locks are skipped by the caller: you cannot
    make 1% of the book without putting almost all of it at risk.
    """
    if cost <= 0 or cost >= 1:
        return None
    win_per = 1.0 - cost
    if win_per < 0.025:
        return None
    if _fee_eats_payout(cost):
        return None
    fee1 = taker_fee(1, cost)
    cap = int(params.max_stake_frac * bankroll / cost)
    want = int(target_frac * bankroll / win_per)
    count = min(cap, max(params.min_count, want))
    if count < params.min_count:
        return None
    while count >= params.min_count and count * cost + taker_fee(count, cost) > params.max_stake_frac * bankroll + 1e-9:
        count -= 1
    if count < params.min_count:
        return None
    edge = win_per - fee1
    return Intent(ticker=ticker, side=side, count=count,
                  limit_price=round(cost, 4), fair=fair, edge=edge,
                  tag=tag, tau_s=tau_s)


def offhours_lock(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                  bankroll, open_positions, params, recent_volume=None, **kw):
    """spot_lock that sits out London/NY metals hours.

    Train-only lock scan (close < 2026-08-27): sequential first-fill 88–94¢
    spot-agree locks were flat overall (n=192, t=−0.12) but split hard by
    session. 12:00–21:00 UTC (London open through COMEX/NY) hit 79.6% and
    lost (n=93, t=−1.14). The complementary 21:00–12:00 UTC book hit 87.9%
    (n=99, t=+1.18) with gold and silver both green, and the same sign in
    train weeks 34 and 35. Week 33 (thin books) was red everywhere.

    Prior: informed 15-minute flow lives in COMEX/London hours, so an
    88–94¢ favorite there is often about to reverse. Off-hours the same
    quote is inventory; lag-fillable locks stick. Do not retune the hour
    window from test.
    """
    hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
    if 12 <= hour < 21:
        return None
    return one_pct(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                    bankroll, open_positions, params,
                    recent_volume=recent_volume, tag="offhours", **kw)


def one_pct(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
            bankroll, open_positions, params, recent_volume=None, tag="one_pct",
            target_frac: float = 0.01, **_):
    """Last-minute ≥90¢ lock, sized for ~1% of bankroll on a win.

    Sit out 50/50 books. Wait until the last ~90 seconds when one side is
    already 90–97¢ *and* spot agrees with that side. REST cannot honestly
    trade the last literal second; 8–90s is the fillable window.

    1.01^96 ≈ 2.6×/day only if almost every window fills. Most will not lock;
    those we skip. One miss at this size is ~8% — the daily stop is 10%.
    """
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    cands = []
    if params.price_min <= yes_ask <= params.price_max:
        if s is None or k is None or s >= k:
            cands.append(("yes", yes_ask, yes_ask))
    no_px = (1.0 - yes_bid) if yes_bid is not None else None
    if no_px is not None and params.price_min <= no_px <= params.price_max:
        if s is None or k is None or s < k:
            cands.append(("no", no_px, 1.0 - no_px))
    if not cands:
        return None
    side, cost, fair = max(cands, key=lambda c: c[1])
    return _size_lock(ticker, side, cost, fair, tau_s, bankroll, params, tag,
                      target_frac=target_frac)


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


def model_fav(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
              bankroll, open_positions, params, recent_volume=None, **_):
    """late_lock that refuses cheap books.

    Train autopsy (n=11): the losers were 22–70¢ fills where the GBM was
    'certain' — same winner's-curse as oracle_lag. Require the *book* to
    already be an 80–94¢ favorite so we are not lifting a stale longshot.
    """
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params, recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    fair = fair_yes(s, k, sigma_1m, tau_s / 60.0)
    fair = min(max(fair, params.prob_clamp), 1.0 - params.prob_clamp)
    if (fair >= 0.88 and params.price_min <= yes_ask <= params.price_max):
        edge = fair - yes_ask - taker_fee(1, yes_ask)
        if edge >= params.theta:
            return _size(ticker, "yes", yes_ask, fair, edge, fair, tau_s,
                         bankroll, params, "model_fav", allow_min=True)
    no_px = 1.0 - yes_bid
    if (fair <= 0.12 and params.price_min <= no_px <= params.price_max):
        q = 1.0 - fair
        edge = q - no_px - taker_fee(1, no_px)
        if edge >= params.theta:
            return _size(ticker, "no", no_px, q, edge, fair, tau_s,
                         bankroll, params, "model_fav", allow_min=True)
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


def longshot(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
             bankroll, open_positions, params, recent_volume=None, **_):
    """Buy the 8–25¢ underdog and hold. Lottery ticket, not FLB.

    A 10¢ fill that hits pays +$0.90/contract. A few hits in a week at
    10% of the book is the only convex path toward a 2× week. Whelan
    says this loses; it is registered as the risky alternative, not a prior.
    """
    g = _gates(ts, close_ts, yes_bid, yes_ask, open_positions, params,
               recent_volume)
    if g is None:
        return None
    tau_s, _ = g
    cands = []
    if params.price_min <= yes_ask <= params.price_max:
        cands.append(("yes", yes_ask, yes_ask))
    no_px = (1.0 - yes_bid) if yes_bid is not None else None
    if no_px is not None and params.price_min <= no_px <= params.price_max:
        cands.append(("no", no_px, 1.0 - no_px))
    if not cands:
        return None
    side, cost, fair = min(cands, key=lambda c: c[1])
    q = min(0.40, cost + 0.08)
    edge = q - cost - taker_fee(1, cost)
    return _size(ticker, side, cost, q, edge, fair, tau_s, bankroll, params,
                 "longshot", allow_min=True)


def yolo_book(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
              bankroll, open_positions, params, recent_volume=None, **kw):
    """Risky mix aimed at a 2× week: sprint lock, mid favorite, then
    opening-impulse follow.

    Last-minute 88–97¢ is the compounding leg (paper 2s poll, not 1-min
    lag). Mid 88–94¢ is the REST-fillable favorite. Follow is the momentum
    sleeve. Longshots are registered separately — they zeroed the mix.
    Not a claim of edge.
    """
    from dataclasses import replace
    tau_s = close_ts - ts
    if 8 <= tau_s <= 90:
        p = replace(params, tau_min_s=8, tau_max_s=90, price_min=0.88,
                     price_max=0.97, max_spread=0.06)
        it = one_pct(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                     bankroll, open_positions, p, recent_volume=recent_volume,
                     tag="sprint", target_frac=0.04, **kw)
        if it is not None:
            return it
    if 180 <= tau_s <= 660:
        p = replace(params, tau_min_s=180, tau_max_s=660, price_min=0.88,
                     price_max=0.94, max_spread=0.06)
        it = favorite_blind(ticker, ts, s, k, sigma_1m, close_ts, yes_bid,
                            yes_ask, bankroll, open_positions, p,
                            recent_volume=recent_volume, **kw)
        if it is not None:
            return it
    p = replace(params, tau_min_s=120, tau_max_s=660, price_min=0.20,
                 price_max=0.85, max_spread=0.08)
    return open_follow(ticker, ts, s, k, sigma_1m, close_ts, yes_bid, yes_ask,
                       bankroll, open_positions, p, recent_volume=recent_volume,
                       **kw)


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
        Spec("favorite_div", favorite_blind,
             _p(tau_min_s=180, tau_max_s=720, price_min=0.72, price_max=0.94,
                theta=0.0, max_open=5, max_stake_frac=0.04, min_count=4),
             "lag",
             "Prior live book: 72c FLB, 4% cap, 5 commodity slots"),
        Spec("one_pct", one_pct,
             _p(tau_min_s=8, tau_max_s=90, price_min=0.90, price_max=0.97,
                theta=0.0, max_open=6, max_stake_frac=0.08, min_count=4,
                max_spread=0.04, min_recent_volume=40.0),
             "lag",
             "Last 90s ≥90c lock, ~1% of bankroll on a win; BTC/ETH included"),
        # Train-only scan (2026-09-12): tau=60 locks are ~99% raced_out.
        # Positive lag-EV cells were 88–94¢ favorites with 3–10 minutes left.
        # These three freeze that finding. Do not add more rows from test.
        Spec("mid_lock", one_pct,
             _p(tau_min_s=180, tau_max_s=300, price_min=0.88, price_max=0.94,
                theta=0.0, max_open=6, max_stake_frac=0.04, min_count=4,
                max_spread=0.04, min_recent_volume=40.0),
             "lag",
             "Spot-agree 88–94¢ lock, 3–5 min left (REST-fillable vs last 90s)"),
        Spec("spot_lock", one_pct,
             _p(tau_min_s=180, tau_max_s=660, price_min=0.88, price_max=0.94,
                theta=0.0, max_open=6, max_stake_frac=0.04, min_count=4,
                max_spread=0.04, min_recent_volume=40.0),
             "lag",
             "Spot-agree 88–94¢ lock, first chance from 11 min to 3 min left"),
        Spec("offhours_lock", offhours_lock,
             _p(tau_min_s=180, tau_max_s=660, price_min=0.88, price_max=0.94,
                theta=0.0, max_open=6, max_stake_frac=0.04, min_count=4,
                max_spread=0.04, min_recent_volume=40.0),
             "lag",
             "spot_lock sitting out 12:00-21:00 UTC (London/NY metals hours)"),
        Spec("rich_fav", favorite_blind,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.94,
                theta=0.0, max_open=6, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "FLB ≥60¢ until close; skip coin-flip / fee-eat; 8% half-Kelly"),
        Spec("crypto_fav", crypto_fav,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.75, price_max=0.92,
                theta=0.0, max_open=6, max_stake_frac=0.04, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.25,
                signal_max_age_s=0),
             "lag",
             "BTC/ETH 15m FLB ≥75¢ until close, 4% each (~$10), not a split"),
        Spec("desk_book", desk_book,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.75, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "Whole book waits 3 min; commodities 8%; BTC/ETH 4% / ≥75¢ + Poly"),
        Spec("wait7_book", wait7_book,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "OSS: sit first 7 min then desk_book (hamad observation phase)"),
        Spec("persist_book", persist_book,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "OSS: desk_book, sit if the book ripped >8¢ in 3 min"),
        Spec("tight_book", tight_book,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "OSS: desk_book only on ≤3¢ books"),
        Spec("late_sit_book", late_sit_book,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "OSS: desk_book, no new entries last 2 min"),
        Spec("richer_wait", richer_wait,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.68, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "alias: wait + 68¢ (now the live desk_book bar)"),
        Spec("no_eth_book", no_eth_book,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "desk_book with ETH off (ETH is the 15m hole)"),
        Spec("settle_ride", settle_ride,
             _p(tau_min_s=60, tau_max_s=300, price_min=0.70, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "OSS hamad settlement ride: last 5 min, ≥70¢, sit last 60s"),
        Spec("longshot_no", longshot_no,
             _p(tau_min_s=180, tau_max_s=720, price_min=0.81, price_max=0.98,
                theta=0.0, max_open=7, max_stake_frac=0.04, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.25,
                signal_max_age_s=0),
             "lag",
             "OSS DanMcInerney: YES 2–19¢, take NO as taker (81–98¢ fav)"),
        Spec("dir_zone", dir_zone,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.25, price_max=0.58,
                theta=0.0, max_open=7, max_stake_frac=0.04, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.25,
                signal_max_age_s=0),
             "lag",
             "OSS hamad directional zone: 7 min wait, 25–58¢ (control)"),
        Spec("same_side_book", same_side_book,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "OFF: agreement gate (wrong reading of both-green)"),
        Spec("spot_desk", spot_desk,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "desk_book only when spot S vs K agrees with the favorite"),
        Spec("poly_confirm", poly_confirm,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.08, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.5,
                signal_max_age_s=0),
             "lag",
             "desk_book + sit crypto when Polymarket 15m favorite disagrees"),
        Spec("poly_book", poly_book,
             _p(tau_min_s=0, tau_max_s=900, price_min=0.60, price_max=0.92,
                theta=0.0, max_open=2, max_stake_frac=0.04, min_count=4,
                max_spread=1.0, min_recent_volume=0.0, kelly_mult=0.25,
                signal_max_age_s=0),
             "lag",
             "Poly ≥60¢ picks side; Kalshi executes if that side is also ≥60¢"),
        Spec("model_fav", model_fav,
             _p(theta=0.03, tau_min_s=120, tau_max_s=360, price_min=0.80,
                price_max=0.94, max_spread=0.06, max_open=6,
                max_stake_frac=0.04, min_count=4, min_recent_volume=40.0),
             "lag",
             "GBM ≥88¢ AND book already 80–94¢, last 6 min; skip cheap 'certain'"),
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
        # Risky / diverse book. Owner asked whether a 2× week is possible.
        # High stake, loose daily stop, crypto on, last-minute + longshot.
        # Not selected from test. Paper measurement only.
        Spec("sprint", one_pct,
             _p(tau_min_s=8, tau_max_s=90, price_min=0.88, price_max=0.97,
                theta=0.0, max_open=7, max_stake_frac=0.15, min_count=4,
                max_spread=0.06, min_recent_volume=20.0,
                daily_stop_frac=0.40),
             "lag",
             "YOLO last 90s 88–97¢ lock, 15% stake, 4% of book on a win"),
        Spec("yolo_lock", favorite_blind,
             _p(tau_min_s=180, tau_max_s=660, price_min=0.88, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.18, min_count=4,
                max_spread=0.06, min_recent_volume=20.0,
                daily_stop_frac=0.40, kelly_mult=1.0),
             "lag",
             "YOLO 88–94¢ FLB at 18% stake (size-up of rich_fav)"),
        Spec("nuke_lock", favorite_blind,
             _p(tau_min_s=180, tau_max_s=660, price_min=0.88, price_max=0.94,
                theta=0.0, max_open=7, max_stake_frac=0.35, min_count=4,
                max_spread=0.06, min_recent_volume=20.0,
                daily_stop_frac=0.60, kelly_mult=3.0),
             "lag",
             "35% stake 88–94¢ — the 'can a week 2×' overbet"),
        Spec("longshot", longshot,
             _p(tau_min_s=120, tau_max_s=720, price_min=0.08, price_max=0.22,
                theta=0.0, max_open=7, max_stake_frac=0.10, min_count=4,
                max_spread=0.08, min_recent_volume=20.0,
                daily_stop_frac=0.40),
             "lag",
             "Buy 8–22¢ underdogs, 10% stake — convex lottery"),
        Spec("yolo_follow", open_follow,
             _p(tau_min_s=120, tau_max_s=660, price_min=0.20, price_max=0.85,
                theta=0.0, max_open=7, max_stake_frac=0.15, min_count=4,
                max_spread=0.08, min_recent_volume=20.0,
                daily_stop_frac=0.40),
             "lag",
             "YOLO follow ≥15bp first-3-minute impulse, 15% stake"),
        Spec("yolo_book", yolo_book,
             _p(tau_min_s=8, tau_max_s=780, price_min=0.05, price_max=0.97,
                theta=0.0, max_open=7, max_stake_frac=0.15, min_count=4,
                max_spread=0.08, min_recent_volume=20.0,
                daily_stop_frac=0.40, kelly_mult=1.0),
             "lag",
             "Risky mix: last-90s lock + 88–94¢ fav + impulse follow"),
    ]
