"""Kill switch and correlation slots — no imports from paper/agent."""

from __future__ import annotations

import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KILL_SWITCH = os.path.join(REPO, "state", "KILL_SWITCH_KALSHI")

# One slot per cluster. Metals, energy, and crypto can all sit on the
# $250 in the same window; gold+silver share a side, WTI/natgas share a
# side. Copper, BTC, and ETH are their own books — we can be in BTC and
# ETH together.
CORR_GROUPS = (
    frozenset({"gold", "silver"}),
    frozenset({"wti", "natgas"}),
)


def kill_switch_tripped() -> bool:
    return os.path.exists(KILL_SWITCH)


def blocked_by_corr(metal: str, side: str, open_positions) -> bool:
    """True if an open position in the same cluster already holds this side."""
    group = next((g for g in CORR_GROUPS if metal in g), frozenset({metal}))
    for p in open_positions:
        other = getattr(p, "metal", None)
        pside = getattr(p, "side", None)
        if other in group and pside == side:
            return True
    return False
