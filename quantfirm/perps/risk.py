"""Perps risk policy — the layer that says no.

Leverage turns an ordinary drawdown into a liquidation, so every limit here
is stated in the venue's own terms (maintenance margin, margin ratio,
liquidation distance) and checked by code before every order. The policy is
config, changed only by a reviewed commit; the strategy proposes, this file
approves. Nothing may re-enable trading after a kill without a human.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .specs import SPECS

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KILL_SWITCH = os.path.join(REPO, "state", "KILL_SWITCH_PERPS")


@dataclass(frozen=True)
class PerpsRiskPolicy:
    bankroll_usd: float = 250.0
    target_vol: float = 0.12            # ex-ante annualised portfolio vol
    max_gross_leverage: float = 1.5     # Σ|notional| / equity
    max_asset_weight: float = 0.75      # |notional_i| / equity
    min_liq_distance: float = 0.35      # adverse move that would liquidate, at all times
    daily_loss_stop: float = 0.03       # of start-of-day equity → no new risk until next UTC day
    weekly_loss_stop: float = 0.06      # of start-of-week equity → no new risk until Monday
    dd_soft: float = 0.08               # from peak: halve all sizing
    dd_kill: float = 0.15               # from peak: flatten, trip kill switch, stop
    max_order_notional_usd: float = 1000.0
    max_orders_per_tick: int = 12
    max_data_age_hours: float = 30.0    # daily bars: refuse to act on a stale panel
    price_collar: float = 0.005         # limit price within ±0.5% of the venue mark
    min_margin_ratio_headroom: float = 0.5   # maintenance / equity must stay ≤ this after the trade
    consecutive_loss_days_pause: int = 5


# Three rungs. Vol targets are the knob; caps scale with it so a rung is a
# posture, not a different strategy. Measured numbers live in
# research/kalshi_perps/ and docs/KALSHI_PERPS.md — pick by evidence.
PROFILES: dict[str, PerpsRiskPolicy] = {
    "conservative": PerpsRiskPolicy(target_vol=0.08, max_gross_leverage=1.0, max_asset_weight=0.5,
                                    dd_soft=0.06, dd_kill=0.12, daily_loss_stop=0.02),
    "balanced": PerpsRiskPolicy(target_vol=0.12, max_gross_leverage=1.5, max_asset_weight=0.75),
    "growth": PerpsRiskPolicy(target_vol=0.18, max_gross_leverage=2.0, max_asset_weight=1.0,
                              min_liq_distance=0.30, dd_soft=0.10, dd_kill=0.20,
                              daily_loss_stop=0.04, weekly_loss_stop=0.08),
}


def kill_switch_tripped() -> bool:
    return os.path.exists(KILL_SWITCH)


def trip_kill_switch(reason: str) -> None:
    os.makedirs(os.path.dirname(KILL_SWITCH), exist_ok=True)
    with open(KILL_SWITCH, "w") as f:
        json.dump({"reason": reason,
                   "tripped_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, f, indent=1)


def ladder_scale(equity: float, peak: float, policy: PerpsRiskPolicy) -> float:
    """1.0 normal, 0.5 past the soft line, 0.0 past the kill line."""
    if peak <= 0:
        return 1.0
    dd = equity / peak - 1.0
    if dd <= -policy.dd_kill:
        return 0.0
    if dd <= -policy.dd_soft:
        return 0.5
    return 1.0


def account_liq_distance(weights: dict[str, float], maint: dict[str, float] | None = None) -> float:
    """Uniform adverse move (every position against us at once) that takes
    account equity to the maintenance requirement. Portfolio margin:
    equity(x) = 1 − G·x, maintenance(x) ≈ Σ|w_i| m_i (1 ± x) → to first
    order x ≥ (1 − Σ|w_i| m_i) / (G + Σ|w_i| m_i). Infinite for a flat book.
    """
    maint = maint or {a: s.maint_rate for a, s in SPECS.items()}
    gross = sum(abs(w) for w in weights.values())
    if gross == 0:
        return float("inf")
    mreq = sum(abs(w) * maint.get(a, 0.35) for a, w in weights.items())
    if mreq >= 1.0:
        return 0.0
    return (1.0 - mreq) / (gross + mreq)


def margin_ratio(weights: dict[str, float], maint: dict[str, float] | None = None) -> float:
    """maintenance margin / equity for a book of weights (the venue liquidates at 1.0)."""
    maint = maint or {a: s.maint_rate for a, s in SPECS.items()}
    return sum(abs(w) * maint.get(a, 0.35) for a, w in weights.items())


def check_pre_trade(policy: PerpsRiskPolicy, *, equity_usd: float, peak_equity_usd: float,
                    order_notional_usd: float, weights_after: dict[str, float],
                    data_age_hours: float, day_pnl_frac: float = 0.0,
                    week_pnl_frac: float = 0.0, mark: float | None = None,
                    limit_price: float | None = None, reduces_risk: bool = False,
                    n_orders_this_tick: int = 0) -> list[str]:
    """Return the list of violations; empty means the order may go.

    ``reduces_risk`` orders (flattening, de-levering) are exempt from the
    loss-stop and ladder checks — a stop must never be blocked by a stop.
    """
    v: list[str] = []
    if kill_switch_tripped():
        v.append("kill_switch")
    if data_age_hours > policy.max_data_age_hours:
        v.append(f"stale_data:{data_age_hours:.1f}h>{policy.max_data_age_hours}h")
    if n_orders_this_tick >= policy.max_orders_per_tick:
        v.append("too_many_orders_this_tick")
    if abs(order_notional_usd) > policy.max_order_notional_usd:
        v.append(f"order_too_large:{order_notional_usd:.2f}>{policy.max_order_notional_usd}")
    if mark and limit_price and abs(limit_price / mark - 1.0) > policy.price_collar:
        v.append(f"price_collar:{limit_price / mark - 1:.3%}")
    gross = sum(abs(w) for w in weights_after.values())
    if not reduces_risk:
        if peak_equity_usd > 0 and ladder_scale(equity_usd, peak_equity_usd, policy) == 0.0:
            v.append(f"drawdown_kill:{equity_usd / peak_equity_usd - 1:.2%}")
        if day_pnl_frac <= -policy.daily_loss_stop:
            v.append(f"daily_stop:{day_pnl_frac:.2%}")
        if week_pnl_frac <= -policy.weekly_loss_stop:
            v.append(f"weekly_stop:{week_pnl_frac:.2%}")
        if gross > policy.max_gross_leverage + 1e-9:
            v.append(f"gross_leverage:{gross:.2f}>{policy.max_gross_leverage}")
        for a, w in weights_after.items():
            if abs(w) > policy.max_asset_weight + 1e-9:
                v.append(f"asset_weight:{a}:{w:.2f}")
        d = account_liq_distance(weights_after)
        if d < policy.min_liq_distance:
            v.append(f"liq_distance:{d:.2%}<{policy.min_liq_distance:.0%}")
        if margin_ratio(weights_after) > policy.min_margin_ratio_headroom:
            v.append(f"margin_ratio:{margin_ratio(weights_after):.2f}")
    return v


def policy_dict(p: PerpsRiskPolicy) -> dict:
    return asdict(p)
