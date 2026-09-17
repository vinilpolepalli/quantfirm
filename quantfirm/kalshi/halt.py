"""Kill switch and correlation slots — no imports from paper/agent."""

from __future__ import annotations

import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KILL_SWITCH = os.path.join(REPO, "state", "KILL_SWITCH_KALSHI")

# The incentive book halts on its OWN file, for the same reason INCENTIVE_LIVE
# is separate from KALSHI_LIVE: the two desks share a venue but nothing else.
# KILL_SWITCH_KALSHI halts the 15m metals desk and is currently present, so
# while the incentive book read it too, arming the incentive book meant
# removing the halt from a $250 live metals desk the owner explicitly does not
# want running. That coupling made "run incentives only" impossible to express.
#
# The cost is that KILL_SWITCH_KALSHI no longer stops the incentive book.
# Stopping EVERYTHING on Kalshi is now two files, and docs/KALSHI_INCENTIVE.md
# says so in the stop procedure.
INCENTIVE_KILL_SWITCH = os.path.join(REPO, "state", "KILL_SWITCH_INCENTIVE")

# Each name is its own book. Gold and silver (or WTI/natgas) can both
# clip the same side in one window. Day-stop is the portfolio brake.
# Same-name same-side still sits via the {metal} fallback below.
CORR_GROUPS = ()


def kill_switch_tripped() -> bool:
    return os.path.exists(KILL_SWITCH)


def incentive_kill_tripped() -> bool:
    """Halt for the LIP incentive book only. See INCENTIVE_KILL_SWITCH above."""
    return os.path.exists(INCENTIVE_KILL_SWITCH)


def blocked_by_corr(metal: str, side: str, open_positions) -> bool:
    """True only if this name+side is already open (don't double a clip).

    Clusters are not one-slot. Gold and silver can both be NO in the
    same window. Day-stop is the portfolio brake.
    """
    group = next((g for g in CORR_GROUPS if metal in g), frozenset({metal}))
    for p in open_positions:
        other = getattr(p, "metal", None)
        pside = getattr(p, "side", None)
        if other in group and pside == side:
            return True
    return False
