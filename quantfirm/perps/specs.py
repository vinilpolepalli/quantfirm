"""Kalshi perpetual futures — instrument specs, venue rules, cost model.

Everything in this file is either a venue FACT with a source and a date, or a
modelling choice that says so. Facts were read on 2026-09-14/15 from the public
perps endpoints (no credentials needed):

    GET https://external-api.kalshi.com/trade-api/v2/margin/markets
    GET .../margin/risk_parameters
    GET .../margin/funding_rates/historical

plus the CFTC fee filing of 2026-06-24 (KalshiEX "Exchange Fee Schedule
(Perpetual Futures Contracts)", rules0624267243.pdf) and the help-center
articles on funding, margin, liquidation and contract specs.

Vocabulary: "perps", "margin" and "perpetual futures" are the same product;
the API says *margin* everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# --------------------------------------------------------------------- venue
PROD_BASE = "https://external-api.kalshi.com"
DEMO_BASE = "https://external-api.demo.kalshi.co"
PROD_WS = "wss://external-api-margin-ws.kalshi.com/trade-api/ws/v2/margin"
DEMO_WS = "wss://external-api-margin-ws.demo.kalshi.co/trade-api/ws/v2/margin"
API_PREFIX = "/trade-api/v2"
MARGIN = "/margin"

# Risk parameters (GET /margin/risk_parameters, 2026-09-14). The margin
# ratio is maintenance_margin / account_equity: a book enters the
# liquidation queue at 0.91 and is liquidated at 1.0. Initial margin is
# maintenance × 1.3 on every listed market.
INITIAL_MARGIN_MULT = 1.3
LIQUIDATION_MARGIN_RATIO = 1.0
QUEUE_MARGIN_RATIO = 0.91

# Funding (help.kalshi.com "How Funding Works" + observed history).
#   * crypto: three times a day, 00:00 / 08:00 / 16:00 ET (04/12/20 UTC in EDT)
#   * metals: once a day at 14:00 UTC (observed for KXGOLDPERP/KXSILVERPERP)
#   * rate = TWAP of 1-minute premiums over the interval
#   * |rate| < 0.01% per interval is rounded to ZERO (verified: the smallest
#     non-zero rate in 4,036 historical rows is exactly 0.0001)
#   * capped at ±2% per interval
#   * longs pay shorts when positive; funding pauses if the index is down
FUNDING_TIMES_UTC = {"crypto": (4, 12, 20), "metals": (14,)}
# Deadband below which the interval's rate is set to zero. Crypto T&C
# (DOTPERP filing, App. A): 0.01%. Metals T&C (GOLDPERP/SILVERPERP,
# 2026-09-08): 0.002%, paid once a day on weekdays only (Monday covers the
# weekend). Both clamp at ±2% per interval. Crypto weights the per-second
# premium linearly by recency (the filing says "this is not a TWAP");
# metals use an equal-weighted mean of per-minute premiums. Neither has an
# interest-rate term, unlike Binance/Hyperliquid.
FUNDING_ROUND_ZERO = 0.0001
FUNDING_DEADBAND = {"crypto": 0.0001, "metals": 0.00002}
FUNDING_CAP = 0.02
# Kalshi Prime (the FCM) sets a default per-market notional risk limit on new
# accounts (GET /margin/notional_risk_limit reported "5000.0000" in the docs
# example). Read it at startup; do not assume more than this until the
# account shows otherwise.
DEFAULT_NOTIONAL_RISK_LIMIT_USD = 5000.0

# Collateral earns interest at the clearinghouse ("approximately 3.25% APY,
# subject to market conditions" — help.kalshi.com "Your Perpetuals Margin
# Account"). Treated as a modelling input, not a promise.
COLLATERAL_APY = 0.0325

# Price banding (docs.kalshi.com/margin/price-banding): bids ≥ min(80% of
# best bid, best bid − 1000 ticks); asks ≤ max(120% of best ask, +1000 ticks).
PRICE_BAND_PCT = 0.20
PRICE_BAND_TICKS = 1000

# Exchange fee schedule, CFTC filing 2026-06-24. Tier by trailing 30-day
# perps + prediction volume; fees are a fraction of NOTIONAL at trade time
# (not of margin), charged on open AND close. (min_volume_usd, taker, maker).
FEE_TIERS: tuple[tuple[float, float, float], ...] = (
    (0.0, 0.0012, 0.0005),
    (100e3, 0.0010, 0.0004),
    (300e3, 0.0008, 0.00032),
    (1e6, 0.0006, 0.00024),
    (3e6, 0.0005, 0.0002),
    (10e6, 0.0004, 0.00016),
    (30e6, 0.00035, 0.00014),
    (100e6, 0.00032, 0.00012),
    (300e6, 0.0003, 0.0001),
    (1e9, 0.00028, 0.00008),
    (3e9, 0.00026, 0.00006),
)


def fee_rates(trailing_30d_volume_usd: float = 0.0) -> tuple[float, float]:
    """(taker, maker) fee rate for a trailing 30-day notional volume."""
    taker, maker = FEE_TIERS[0][1], FEE_TIERS[0][2]
    for lo, t, m in FEE_TIERS:
        if trailing_30d_volume_usd >= lo:
            taker, maker = t, m
    return taker, maker


def kalshi_funding(rate: float, asset_class: str = "crypto") -> float:
    """Apply Kalshi's deadband and cap to a raw funding rate per interval."""
    if abs(rate) < FUNDING_DEADBAND.get(asset_class, FUNDING_ROUND_ZERO):
        return 0.0
    return max(-FUNDING_CAP, min(FUNDING_CAP, rate))


# ---------------------------------------------------------------- contracts
@dataclass(frozen=True)
class PerpSpec:
    ticker: str            # Kalshi margin market ticker
    asset: str             # short name used in data files and state
    asset_class: str       # "crypto" | "metals"
    contract_size: Decimal # underlying units per contract (title: "0.0001 BTC")
    tick: Decimal          # $ per tick
    maint_rate: float      # maintenance margin / notional at ~$1k notional
    index: str             # settlement/funding reference
    proxy: str             # long-history price proxy used by the backtester
    live_since: str        # first funding row observed

    @property
    def initial_rate(self) -> float:
        return self.maint_rate * INITIAL_MARGIN_MULT

    @property
    def max_entry_leverage(self) -> float:
        """Notional you can open per $1 of collateral."""
        return 1.0 / self.initial_rate

    @property
    def funding_per_day(self) -> int:
        return len(FUNDING_TIMES_UTC[self.asset_class])


# maint_rate = 1 / leverage_estimates["1000"] as published on 2026-09-14.
# Leverage falls with notional (BTC 6.05x at $1k → 5.89x at $1M); a small
# account sits on the $1k row. Live code re-reads the estimate every tick.
SPECS: dict[str, PerpSpec] = {
    "btc": PerpSpec("KXBTCPERP", "btc", "crypto", Decimal("0.0001"), Decimal("0.0001"),
                    1 / 6.05, "CF Benchmarks BRTI (1s)", "BTC-USD", "2026-06-03"),
    "eth": PerpSpec("KXETHPERP", "eth", "crypto", Decimal("0.001"), Decimal("0.0001"),
                    1 / 4.66, "CF Benchmarks", "ETH-USD", "2026-06-03"),
    "sol": PerpSpec("KXSOLPERP", "sol", "crypto", Decimal("0.1"), Decimal("0.0001"),
                    1 / 3.02, "CF Benchmarks", "SOL-USD", "2026-06-03"),
    "xrp": PerpSpec("KXXRPPERP", "xrp", "crypto", Decimal("1"), Decimal("0.0001"),
                    1 / 2.79, "CF Benchmarks", "XRP-USD", "2026-06-03"),
    "gold": PerpSpec("KXGOLDPERP", "gold", "metals", Decimal("0.001"), Decimal("0.0001"),
                     1 / 15.26, "Pyth Metal.Index.GOLD/USD", "GC=F", "2026-09-11"),
    "silver": PerpSpec("KXSILVERPERP", "silver", "metals", Decimal("0.1"), Decimal("0.0001"),
                       1 / 7.79, "Pyth Metal.Index.SILVER/USD", "SI=F", "2026-09-11"),
}

# Listed but not in the research universe (thin books, short histories, or
# both). Leverage estimate at $1k notional, 2026-09-14, for the record.
OTHER_LISTED_LEVERAGE = {
    "KXDOGEPERP": 2.74, "KXHYPEPERP": 2.24, "KXLINKPERP": 3.56, "KXLTCPERP": 3.82,
    "KXBCHPERP": 2.92, "KXZECPERP": 2.47, "KXNEARPERP": 3.08, "KXSUIPERP": 2.50,
    "KXADAPERP": 3.05, "KXBNBPERP": 4.73, "KXAAVEPERP": 3.24, "KXVVVPERP": 1.75,
    "KXWLDPERP": 1.69, "KXKSHIBPERP": 1.99,
    # inactive on 2026-09-14
    "KXDOTPERP": 3.43, "KXHBARPERP": 2.51, "KXXLMPERP": 2.49,
}

TICKER_TO_ASSET = {s.ticker: a for a, s in SPECS.items()}
RESEARCH_UNIVERSE = ("btc", "eth", "gold", "silver")
EXTENDED_UNIVERSE = RESEARCH_UNIVERSE + ("sol", "xrp")


# ------------------------------------------------------------ cost model
@dataclass(frozen=True)
class CostModel:
    """Per-side cost as a fraction of notional: exchange fee + half-spread."""

    name: str
    fee_rate: float
    half_spread: float

    @property
    def per_side(self) -> float:
        return self.fee_rate + self.half_spread

    def round_trip(self) -> float:
        return 2 * self.per_side


# Observed top-of-book spreads 2026-09-14: BTC 5 bps, ETH 4 bps, gold 2 bps,
# silver 3.5 bps, SOL 3 bps, XRP 4 bps. Half of that is 1–2.5 bps; the taker
# model uses 2.5 bps on top of the tier-0 fee so it is not flattered.
TAKER_T0 = CostModel("taker_t0", 0.0012, 0.00025)
# Resting at the touch: no spread paid, 5 bps maker fee. Fill risk is NOT
# modelled, so this is an upper bound on what patience can recover.
MAKER_T0 = CostModel("maker_t0", 0.0005, 0.0)
# 1.5× stress: a strategy must stay net-positive here to be approved.
STRESS = CostModel("stress_1p5x", 0.0018, 0.0005)

APPROVAL_COST = TAKER_T0
SCENARIOS = (TAKER_T0, MAKER_T0, STRESS)


def cost_by_name(name: str) -> CostModel:
    for c in SCENARIOS:
        if c.name == name:
            return c
    raise KeyError(name)


# --------------------------------------------------------- margin arithmetic
def liquidation_move(weight: float, maint_rate: float) -> float:
    """Adverse price move (fraction) that liquidates a single position whose
    whole account equity backs it (portfolio margin, one market).

    weight = signed notional / equity. Long: equity E(1 − w·x) ≤ maint·w·E(1 − x)
    → x ≥ (1 − m·w) / (w·(1 − m)). Short: notional grows with the move →
    x ≥ (1 − m·w) / (w·(1 + m)). Returns +inf for a flat book and 1.0 (price
    to zero) when a long can never be liquidated.
    """
    w = abs(weight)
    if w == 0:
        return float("inf")
    m = maint_rate
    if 1 - m * w <= 0:
        return 0.0  # already below maintenance
    if weight > 0:
        return min(1.0, (1 - m * w) / (w * (1 - m)))
    return (1 - m * w) / (w * (1 + m))


def max_weight_for_distance(distance: float, maint_rate: float, short: bool = False) -> float:
    """Largest |weight| such that liquidation_move ≥ distance."""
    m = maint_rate
    if short:
        # x = (1 − m w)/(w(1+m)) ≥ d  → 1 − m w ≥ d w (1+m) → w ≤ 1/(m + d(1+m))
        return 1.0 / (m + distance * (1 + m))
    # long: 1 − m w ≥ d w (1−m) → w ≤ 1/(m + d(1−m))
    return 1.0 / (m + distance * (1 - m))


def contracts_for_notional(spec: PerpSpec, notional_usd: float, price_per_contract: float) -> Decimal:
    """Whole contracts (Kalshi allows 0.01 granularity; we trade integers)."""
    if price_per_contract <= 0:
        return Decimal(0)
    return Decimal(int(notional_usd / price_per_contract))
