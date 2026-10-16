"""Gaussian map for Kalshi daily temperature brackets.

Lifted from the agiprolabs weather-markets skill (MIT), rewritten against
this desk's settlement rules. Forecast skill is not a trading edge — the
12-city-day tape in research/kalshi_div_nowcast.md already lost money on
an 80-member ensemble take. These formulas exist so we do not re-invent
the off-by-one that manufactured a +1640% phantom backtest.

Settlement truth is always the venue ``result`` field. Do not score a
trade against a self-computed CLI value.
"""

from __future__ import annotations

import math
import re


def phi(x: float) -> float:
    """Standard normal CDF via erf. Same identity as ``fair.norm_cdf``."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bracket_p_yes(floor_int: int, cap_int: int, mu: float, sigma: float) -> float:
    """P(CLI ∈ {floor..cap} inclusive) under N(μ, σ) with continuity correction.

    Kalshi 2°F brackets are both-ends-inclusive. Treating them as 1°F
    half-open windows is the phantom-edge hall-of-fame entry.
    """
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    if cap_int < floor_int:
        raise ValueError("cap must be >= floor")
    return phi((cap_int + 0.5 - mu) / sigma) - phi((floor_int - 0.5 - mu) / sigma)


def threshold_p_yes(strike: int, mu: float, sigma: float, *, kind: str) -> float:
    """P(YES) for a one-sided threshold. ``kind`` is the API strike_type.

    Never infer greater/less from the ticker. ``T74`` can be either.
    """
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    k = str(kind or "").lower()
    if k in ("greater", "greater_or_equal"):
        # YES iff cli >= strike + 1  (Kalshi greater encoding)
        return 1.0 - phi((strike + 0.5 - mu) / sigma)
    if k in ("less", "less_or_equal"):
        return phi((strike - 0.5 - mu) / sigma)
    raise ValueError(f"kind must be greater/less from the API, got {kind!r}")


def mu_sigma_from_quantiles(p10: float, p50: float, p90: float,
                            *, sigma_scale: float = 1.0,
                            sigma_mult: float = 1.0) -> tuple[float, float]:
    """Ensemble 10/50/90 → (μ, σ). 2.56 is the N(0,1) 10th–90th span."""
    sigma_raw = max((p90 - p10) / 2.56, 0.5) * sigma_scale * sigma_mult
    return p50, max(sigma_raw, 0.1)


def overround(p_yes: list[float]) -> float:
    return float(sum(p_yes))


_B = re.compile(r"-B(-?\d+(?:\.\d+)?)$")
_T = re.compile(r"-T(-?\d+(?:\.\d+)?)$")


def parse_weather_ticker(ticker: str) -> dict:
    """Read B<center> / T<strike> from a Kalshi weather ticker.

    B79.5 covers the two integers {79, 80}. The date and city stay in
    the prefix; do not derive the event day from close_time.
    """
    t = str(ticker or "")
    m = _B.search(t)
    if m:
        center = float(m.group(1))
        lo = int(math.floor(center))
        hi = lo + 1
        return {"kind": "bracket", "center": center, "floor": lo, "cap": hi}
    m = _T.search(t)
    if m:
        return {"kind": "threshold", "strike": float(m.group(1))}
    return {"kind": "unknown"}
