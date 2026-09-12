"""Fair value, vol, fees, and sizing for the 15-minute metals binaries.

Model: over horizons tau <= 15 min the underlying index is a driftless
diffusion, so the binary "close >= K" is worth

    P_fair = N( ln(S/K) / (sigma_1m * sqrt(tau_minutes)) )

with sigma_1m the one-minute log-return vol NOW (EWMA of recent 1-min
returns times a deterministic time-of-day multiplier). The strike K is the
window-open print and is known exactly; S is the live settlement proxy.

Fees (verified, all metals series fee_type=quadratic, multiplier=1):
    taker = ceil_to_cent(0.07 * C * P * (1-P)) per order; maker = $0;
    no settlement fee. We book the conservative cent-ceil everywhere.

Sizing: fractional Kelly for a binary bought at all-in cost a per contract
(price + fee/contract): f* = (q - a) / (1 - a); we trade kelly_mult * f*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fair_yes(s: float, k: float, sigma_1m: float, tau_minutes: float) -> float:
    """P(underlying close >= K at window end). sigma_1m = 1-min log-return vol."""
    if tau_minutes <= 0:
        return 1.0 if s >= k else 0.0
    denom = sigma_1m * math.sqrt(tau_minutes)
    if denom <= 0:
        return 1.0 if s >= k else 0.0
    d = math.log(s / k) / denom
    return norm_cdf(d)


def taker_fee(count: float, price: float) -> float:
    """Kalshi quadratic taker fee, conservative cent ceiling, per order."""
    raw = 0.07 * count * price * (1.0 - price)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def kelly_fraction(q: float, all_in_cost: float) -> float:
    """Kelly fraction of bankroll for a $1 binary at all-in cost per contract."""
    if all_in_cost >= 1.0 or all_in_cost <= 0.0:
        return 0.0
    return max(0.0, (q - all_in_cost) / (1.0 - all_in_cost))


@dataclass
class VolEstimator:
    """Causal EWMA of squared 1-min log returns with hour-of-week multipliers.

    The diurnal profile is learned online (EWMA per bucket of the ratio of
    squared return to the base EWMA) so the backtest never sees the future.
    """

    halflife_min: float = 30.0
    diurnal: bool = True
    seed_sigma: float = 0.0009  # ~9 bp/min, generous prior before data arrives
    _var: float = field(default=None, init=False)  # type: ignore[assignment]
    _mult: dict = field(default_factory=dict, init=False)
    _mult_n: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        self._var = self.seed_sigma ** 2
        self._alpha = 1.0 - 0.5 ** (1.0 / self.halflife_min)

    @staticmethod
    def bucket(ts: int) -> int:
        """Hour-of-week bucket (0..167) for a unix ts, UTC."""
        return (int(ts) // 3600) % 168

    def update(self, ts: int, log_ret_1m: float) -> None:
        r2 = log_ret_1m * log_ret_1m
        self._var = (1 - self._alpha) * self._var + self._alpha * r2
        if self.diurnal and self._var > 0:
            b = self.bucket(ts)
            ratio = r2 / self._var
            m, n = self._mult.get(b, 1.0), self._mult_n.get(b, 0)
            a = max(0.02, 1.0 / (n + 1))
            self._mult[b] = (1 - a) * m + a * ratio
            self._mult_n[b] = n + 1

    def sigma_1m(self, ts: int) -> float:
        base = math.sqrt(max(self._var, 1e-12))
        if not self.diurnal:
            return base
        m = self._mult.get(self.bucket(ts), 1.0)
        # cap the multiplier so one CPI print does not poison a bucket
        m = min(max(m, 0.25), 6.0)
        return base * math.sqrt(m)
