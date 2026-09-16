"""Per-book P&L statistics, with the t-stat CLUSTERED BY MARKET.

One 15-minute market settles once. Every fill inside it -- both legs of a
double-entry, a maker fill and the shadow fill that mirrored it, two sizes of
the same view -- resolves on that single settlement draw. Treating those rows
as independent observations is pseudo-replication: it inflates n without
adding information, and the t-stat grows like sqrt(rows/market) for free.

This is the same trap that made the passive-edge study read t=+23.3 when the
clustered answer was t=+0.38 (docs/KALSHI.md 3d). It reached the desk's own
headline via concurrent engines double-entering markets, so the correction
lives in one place and every reporting surface imports it.

`n` stays the fill count, because "how many fills" is an honest descriptive
number and the hit rate is a property of fills. Only the INFERENCE clusters.
"""
from __future__ import annotations

import collections
import math
import statistics as st

__all__ = ["book_stats"]


def _t(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    sd = st.stdev(vals)
    if sd <= 0:
        return 0.0
    return st.mean(vals) / (sd / math.sqrt(len(vals)))


def book_stats(rows, adapter: str) -> dict | None:
    """rows: dicts from the paper trade log. Returns None if the book is empty."""
    rs = [r for r in rows if r.get("adapter") == adapter]
    p: list[float] = []
    per_market: dict[str, float] = collections.defaultdict(float)
    for r in rs:
        try:
            pnl = float(r["pnl"])
        except (KeyError, TypeError, ValueError):
            continue
        p.append(pnl)
        per_market[str(r.get("ticker"))] += pnl
    if not p:
        return None
    n = len(p)
    wins = [x for x in p if x > 0]
    losses = [x for x in p if x <= 0]
    mu = st.mean(p)
    sd = st.stdev(p) if n > 1 else 0.0
    clustered = list(per_market.values())
    aw = st.mean(wins) if wins else 0.0
    al = st.mean(losses) if losses else 0.0
    be = abs(al) / (aw + abs(al)) if (aw + abs(al)) > 0 else None
    return {
        "n": n,
        "n_markets": len(clustered),
        "pnl": round(sum(p), 2),
        "hit": round(len(wins) / n, 4),
        "mean": round(mu, 3),
        "sd": round(sd, 2),
        # headline t: one market = one observation
        "t": round(_t(clustered), 2),
        # kept so the inflation is visible rather than silently corrected
        "t_naive": round(mu / (sd / math.sqrt(n)), 2) if sd > 0 else 0.0,
        "avg_win": round(aw, 2),
        "avg_loss": round(al, 2),
        "breakeven_hit": round(be, 4) if be else None,
        "cushion_pp": round(100 * (len(wins) / n - be), 2) if be else None,
    }
