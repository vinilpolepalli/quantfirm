"""Venue cost model.

Robinhood Crypto has no commission but embeds a spread in execution prices.
Measured live on 2026-07-31 via GET /marketdata/best_bid_ask/ (BTC-USD):
    buy_spread  = 0.00926681   (~0.93% above mid)
    sell_spread = 0.00926681   (~0.93% below mid)
so a market-order round trip costs ~1.85% of notional.

Limit orders let us set our own price; resting at/near mid can recover much of
the spread but adds fill risk. The backtester therefore prices every strategy
under multiple cost scenarios; a strategy is only approved if it survives the
WORST one it would actually trade under.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    name: str
    per_side: float  # fraction of notional paid per fill

    def round_trip(self) -> float:
        return 2 * self.per_side


# Market orders: pay the full measured spread each side.
RH_MARKET = CostModel("rh_market", 0.0093)

# Marketable limit near the far touch: assume ~2/3 of spread paid.
RH_LIMIT_AGGRESSIVE = CostModel("rh_limit_aggressive", 0.0062)

# Patient limit near mid, accepting fill risk: assume ~1/3 of spread paid.
RH_LIMIT_PATIENT = CostModel("rh_limit_patient", 0.0031)

# The cost regime every strategy MUST survive to be approved for live capital.
APPROVAL_COST = RH_MARKET

SCENARIOS = [RH_MARKET, RH_LIMIT_AGGRESSIVE, RH_LIMIT_PATIENT]
