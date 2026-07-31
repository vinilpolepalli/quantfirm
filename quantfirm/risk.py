"""Risk policy — the firm's non-negotiable layer.

The user accepts high risk; the risk desk's job is still to prevent RUIN and
operational blowups, because a dead bankroll can't compound. Limits here are
generous by institutional standards but hard: the engine refuses to trade
when any check fails, and a drawdown breach trips the kill switch (a file in
state/ that every future run honors until a human or the risk-committee agent
removes it).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass(frozen=True)
class RiskPolicy:
    bankroll_usd: float = 250.0          # capital the bot may manage
    max_position_usd: float = 260.0      # hard cap incl. appreciation slack
    min_trade_usd: float = 5.0           # hysteresis: ignore smaller rebalances
    max_trade_usd: float = 260.0         # single-order cap
    kill_drawdown: float = 0.40          # trip kill switch at -40% from peak
    max_data_age_hours: float = 3.0      # refuse to trade on stale candles
    max_orders_per_run: int = 2


DEFAULT = RiskPolicy()


def check_pre_trade(policy: RiskPolicy, *, equity_usd: float, peak_equity_usd: float,
                    order_usd: float, position_after_usd: float,
                    data_age_hours: float) -> list[str]:
    """Return list of violations; empty list means the order may proceed."""
    v = []
    if data_age_hours > policy.max_data_age_hours:
        v.append(f"stale_data:{data_age_hours:.1f}h>{policy.max_data_age_hours}h")
    if peak_equity_usd > 0 and equity_usd / peak_equity_usd - 1 < -policy.kill_drawdown:
        v.append(f"drawdown_breach:{equity_usd / peak_equity_usd - 1:.2%}")
    if abs(order_usd) > policy.max_trade_usd:
        v.append(f"order_too_large:{order_usd:.2f}>{policy.max_trade_usd}")
    if position_after_usd > policy.max_position_usd:
        v.append(f"position_cap:{position_after_usd:.2f}>{policy.max_position_usd}")
    return v


def kill_switch_path(state_dir: str) -> str:
    return os.path.join(state_dir, "KILL_SWITCH")


def kill_switch_active(state_dir: str) -> bool:
    return os.path.exists(kill_switch_path(state_dir))


def trip_kill_switch(state_dir: str, reason: str) -> None:
    with open(kill_switch_path(state_dir), "w") as f:
        json.dump({"reason": reason,
                   "tripped_at": datetime.now(timezone.utc).isoformat()}, f, indent=2)
