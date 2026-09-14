"""Kill switch and correlation slots — no imports from paper/agent."""

from __future__ import annotations

import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KILL_SWITCH = os.path.join(REPO, "state", "KILL_SWITCH_KALSHI")

# Each name is its own book. Gold and silver (or WTI/natgas) can both
# clip the same side in one window. Day-stop is the portfolio brake.
# Same-name same-side still sits via the {metal} fallback below.
CORR_GROUPS = ()


def kill_switch_tripped() -> bool:
    return os.path.exists(KILL_SWITCH)


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
