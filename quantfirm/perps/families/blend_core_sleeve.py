"""blend_core_sleeve — the paper candidate: the long book plus a residual-momentum sleeve.

This is not a new idea and it is not a new trial. It is the deployable form of
two things the desk has already measured separately:

* ``vol_target_hold`` on (btc, eth, gold, silver) — the core, and the posture
  the desk would run on its own;
* ``xsmom_residual`` on the tradable crypto perps — a dollar-neutral sleeve
  measured at −0.156 correlation to that core.

Blending notional weights at (1−w, w) gives a book whose return is exactly
(1−w)·core + w·sleeve, which is the quantity
``research/kalshi_perps/families/xsmom_residual.md`` reports out of sample:
at w = 0.30, Sharpe 1.694 against the core's 1.255, the same 15.2% return,
volatility 12.25% → 8.99% and drawdown −10.12% → −8.64%.

``sleeve_weight`` is fixed at 0.30 and is NOT a parameter to search. Every
weight from 0.20 to 0.60 beat the core out of sample, so 0.30 is the
conservative end of a flat region rather than a peak; sweeping it here would
be fitting the one number the evidence does not pin down.

Caveats carried from that report, because a paper book should not be started
without them: three years and four folds is one regime; the effect is well
published and likely crowded; the sleeve turns over 13 to 19 times a year on
names whose round trip is 29 to 43 bps; the universe is the set Kalshi lists
today, so survivorship is present in both legs; and the blend FAILS the firm's
deflated-Sharpe gate (0.695 against 0.95) because 1,119 out-of-sample days
need a Sharpe of 2.33 to clear it. That is why this is a paper book and not a
promotion.
"""
from __future__ import annotations

import pandas as pd

from ..data import align
from ..specs import RESEARCH_UNIVERSE
from ..strategies import register, REGISTRY, cap_weights

SLEEVE_WEIGHT = 0.30


@register("blend_core_sleeve", control=True)
def blend_core_sleeve(panel, target_vol: float = 0.12, sleeve_weight: float = SLEEVE_WEIGHT,
                      max_gross: float = 1.5, max_asset: float = 0.75,
                      min_liq_distance: float = 0.35, **kw) -> pd.DataFrame:
    """(1 − w) × the four-asset long book + w × the residual-momentum sleeve.

    Registered as a control rather than a candidate: it is a deployment of two
    already-registered strategies at a pre-committed weight, so it must not add
    a trial to the registry and raise the deflated-Sharpe bar for everyone.
    """
    closes = align(panel)
    out = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)

    core_names = [a for a in RESEARCH_UNIVERSE if a in panel]
    if core_names:
        core = REGISTRY["vol_target_hold"]({a: panel[a] for a in core_names}, target_vol=target_vol)
        out[core_names] = out[core_names].add(
            core.reindex(index=out.index, columns=core_names).fillna(0.0) * (1.0 - sleeve_weight),
            fill_value=0.0)

    sleeve = REGISTRY["xsmom_residual"](panel, target_vol=target_vol, **kw)
    sleeve = sleeve.reindex(index=out.index, columns=out.columns).fillna(0.0)
    out = out.add(sleeve * sleeve_weight, fill_value=0.0)

    # the two books are capped independently, so the sum needs one more pass
    return cap_weights(out, max_gross, max_asset, min_liq_distance)
