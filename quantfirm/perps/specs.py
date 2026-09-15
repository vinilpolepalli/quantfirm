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
    """One listed Kalshi perpetual future.

    ``half_spread`` is HALF the top-of-book spread, (ask − bid) / 2 / mid, as a
    fraction of notional. It was MEASURED from top-of-book on GET /margin/markets
    on 2026-09-15 — one reading, one moment, not an average. This venue is three
    months old (BTC/ETH/SOL/XRP funded from 2026-06-03, most of the tail from
    2026-06-09 or later, ADA/BNB from 2026-08-31) and its alt books are thin:
    fourteen of the twenty quoting markets trade under $10M a day and six under
    $1.5M, with open interest in the hundreds of thousands. A book that thin
    widens the moment size arrives and can requote by a factor overnight. Treat
    this number as a point-in-time floor on the cost of a fill, never as a
    promise, and re-read it before sizing anything outside btc/eth/gold/silver.
    ``0.0`` means "not measured" (dot/hbar/xlm quote nothing at all) and makes
    CostModel.side_cost fall back to its flat modelling spread.
    """

    ticker: str            # Kalshi margin market ticker
    asset: str             # short name used in data files and state
    asset_class: str       # "crypto" | "metals"
    contract_size: Decimal # underlying units per contract (title: "0.0001 BTC")
    tick: Decimal          # $ per tick
    maint_rate: float      # maintenance margin / notional at ~$1k notional
    index: str             # settlement/funding reference
    proxy: str             # long-history price proxy used by the backtester
    live_since: str        # first funding row observed ("" = never funded)
    half_spread: float = 0.0  # measured half-spread, fraction of notional (see docstring)
    underlying_multiplier: Decimal = Decimal(1)  # venue field; 1000 for kSHIB, 1 elsewhere

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

    @property
    def half_spread_bps(self) -> float:
        return self.half_spread * 1e4

    @property
    def proxy_units_per_contract(self) -> float:
        """Units of the PROXY asset in one contract.

        ``contract_size`` counts the contract's own underlying, which for every
        market but one is the coin the proxy quotes. KXKSHIBPERP's underlying is
        kSHIB, a thousand SHIB, and the venue says so in ``underlying_multiplier``
        (1000 there, 1 everywhere else), so one contract is 1000 × 1000 =
        1,000,000 SHIB. Verified against the venue's own marks on 2026-09-15:
        0.0001 × 1 × $78,211 = $7.82 for BTC against a quote of 7.794, and
        1000 × 1000 × $0.00000521 = $5.21 for kSHIB against a quote of 5.2117.
        Multiplying by ``contract_size`` alone prices a kSHIB contract at half a
        cent and makes it look infinitely divisible to a small account.
        """
        return float(self.contract_size) * float(self.underlying_multiplier)

    def notional_per_contract(self, proxy_price: float) -> float:
        """USD notional of ONE contract at a price quoted in ``proxy`` units."""
        return self.proxy_units_per_contract * proxy_price


# Leverage estimate at $1k notional, leverage_estimates["1000"] from
# GET /margin/markets (2026-09-14 for the original six, re-read 2026-09-15 for
# all 23 — unchanged). maint_rate = 1 / this, initial = 1.3 × maint; the rule
# reproduces the six original specs to four decimals. Leverage falls with
# notional (BTC 6.05x at $1k → 5.89x at $1M) and a small account sits on the
# $1k row. Live code re-reads the estimate every tick. Each spec below repeats
# the number as 1/x so the spec and this record can be checked against each
# other (tests/test_perps_specs_broad.py does exactly that).
LEVERAGE_AT_1K: dict[str, float] = {
    "KXBTCPERP": 6.05, "KXETHPERP": 4.66, "KXXRPPERP": 2.79, "KXSILVERPERP": 7.79,
    "KXGOLDPERP": 15.26, "KXSOLPERP": 3.02, "KXZECPERP": 2.47, "KXNEARPERP": 3.08,
    "KXHYPEPERP": 2.24, "KXVVVPERP": 1.75, "KXADAPERP": 3.05, "KXSUIPERP": 2.50,
    "KXBCHPERP": 2.92, "KXLTCPERP": 3.82, "KXDOGEPERP": 2.74, "KXBNBPERP": 4.73,
    "KXLINKPERP": 3.56, "KXWLDPERP": 1.69, "KXKSHIBPERP": 1.99, "KXAAVEPERP": 3.24,
    "KXDOTPERP": 3.43, "KXHBARPERP": 2.51, "KXXLMPERP": 2.49,
}

# Earliest daily bar of each price proxy, probed 2026-09-15 (Coinbase spot for
# crypto, Yahoo futures for metals). This is what decides BREADTH_UNIVERSE
# below. Note bnb (2025-10-22) and hype (2026-02-05) begin AFTER the sealed
# holdout starts on 2025-07-01: they have no research history at all, only
# holdout history, and no DEV-window backtest can include them.
PROXY_FIRST_BAR: dict[str, str] = {
    "gold": "2000-08-30", "silver": "2000-08-30", "btc": "2015-07-20",
    "eth": "2016-05-18", "ltc": "2016-08-17", "bch": "2017-12-20",
    "xrp": "2019-02-26", "xlm": "2019-03-14", "link": "2019-06-27",
    "zec": "2020-12-08", "aave": "2020-12-15", "ada": "2021-03-18",
    "doge": "2021-06-03", "dot": "2021-06-16", "sol": "2021-06-17",
    "kshib": "2021-09-09", "near": "2022-09-01", "hbar": "2022-10-13",
    "sui": "2023-05-18", "vvv": "2025-01-28", "wld": "2025-04-30",
    "bnb": "2025-10-22", "hype": "2026-02-05",
}

# All 23 listed perps. The first six rows are UNCHANGED in every number that
# existed before (ticker, contract_size, tick, maint_rate, index, proxy,
# live_since); only the measured half_spread is new, and for those four
# researched assets it is below the flat modelling spread, so no cost changes.
#
# ``index``: BTC settles on CF Benchmarks BRTI and ETH/SOL/XRP on CF Benchmarks
# per the help centre; metals on the Pyth metal indices. For the seventeen
# tickers added on 2026-09-15 the API exposes only ``exchange_index`` (0 =
# crypto, 1 = metals) and no provider name, so that is what the field records.
# Do not upgrade those strings to a provider we have not verified.
#
# ``live_since`` is the first row of GET /margin/funding_rates/historical, read
# 2026-09-15. dot, hbar and xlm returned ZERO funding rows ever — they are
# listed and margin-able but have never funded, never traded, and quote nothing.
#
# kSHIB UNIT NOTE (the one place where the contract and the proxy disagree):
# KXKSHIBPERP's title is "1K kSHIB" and it is the only market whose venue field
# ``underlying_multiplier`` is not 1 — it is 1000. The contract's named
# underlying is a kSHIB (= 1000 SHIB); its ``contract_size`` of 1000 is already
# denominated in SHIB, i.e. in the units the proxy SHIB-USD quotes. So
# notional_per_contract() is the same plain contract_size × proxy_price as
# everywhere else: 1000 × $0.0052 ≈ $5.21, which is what the venue quoted on
# 2026-09-15 (bid 5.2026 / ask 5.2101). The trap to avoid is feeding this spec
# a kSHIB-denominated price (a "KSHIB-USD" series does not exist anywhere) or
# reading the venue's own per-contract mark as a per-coin price: either is a
# 1000× error in notional, contracts and P&L. underlying_multiplier is carried
# on the spec so that conversion is explicit rather than folklore.
SPECS: dict[str, PerpSpec] = {
    "btc": PerpSpec("KXBTCPERP", "btc", "crypto", Decimal("0.0001"), Decimal("0.0001"),
                    1 / 6.05, "CF Benchmarks BRTI (1s)", "BTC-USD", "2026-06-03", 0.00002),
    "eth": PerpSpec("KXETHPERP", "eth", "crypto", Decimal("0.001"), Decimal("0.0001"),
                    1 / 4.66, "CF Benchmarks", "ETH-USD", "2026-06-03", 0.00004),
    "sol": PerpSpec("KXSOLPERP", "sol", "crypto", Decimal("0.1"), Decimal("0.0001"),
                    1 / 3.02, "CF Benchmarks", "SOL-USD", "2026-06-03", 0.00018),
    "xrp": PerpSpec("KXXRPPERP", "xrp", "crypto", Decimal("1"), Decimal("0.0001"),
                    1 / 2.79, "CF Benchmarks", "XRP-USD", "2026-06-03", 0.00018),
    "gold": PerpSpec("KXGOLDPERP", "gold", "metals", Decimal("0.001"), Decimal("0.0001"),
                     1 / 15.26, "Pyth Metal.Index.GOLD/USD", "GC=F", "2026-09-11", 0.00006),
    "silver": PerpSpec("KXSILVERPERP", "silver", "metals", Decimal("0.1"), Decimal("0.0001"),
                       1 / 7.79, "Pyth Metal.Index.SILVER/USD", "SI=F", "2026-09-11", 0.00015),
    # --- added 2026-09-15: the rest of the listed board, by 24h notional volume
    "zec": PerpSpec("KXZECPERP", "zec", "crypto", Decimal("0.01"), Decimal("0.0001"),
                    1 / 2.47, "exchange_index 0", "ZEC-USD", "2026-06-24", 0.00076),
    "near": PerpSpec("KXNEARPERP", "near", "crypto", Decimal("1"), Decimal("0.0001"),
                     1 / 3.08, "exchange_index 0", "NEAR-USD", "2026-06-24", 0.00082),
    "hype": PerpSpec("KXHYPEPERP", "hype", "crypto", Decimal("0.1"), Decimal("0.0001"),
                     1 / 2.24, "exchange_index 0", "HYPE-USD", "2026-06-08", 0.00036),
    "vvv": PerpSpec("KXVVVPERP", "vvv", "crypto", Decimal("0.1"), Decimal("0.0001"),
                    1 / 1.75, "exchange_index 0", "VVV-USD", "2026-08-28", 0.00066),
    "ada": PerpSpec("KXADAPERP", "ada", "crypto", Decimal("1"), Decimal("0.0001"),
                    1 / 3.05, "exchange_index 0", "ADA-USD", "2026-08-31", 0.00048),
    "sui": PerpSpec("KXSUIPERP", "sui", "crypto", Decimal("10"), Decimal("0.0001"),
                    1 / 2.50, "exchange_index 0", "SUI-USD", "2026-06-09", 0.00067),
    "bch": PerpSpec("KXBCHPERP", "bch", "crypto", Decimal("0.01"), Decimal("0.0001"),
                    1 / 2.92, "exchange_index 0", "BCH-USD", "2026-06-09", 0.00038),
    "ltc": PerpSpec("KXLTCPERP", "ltc", "crypto", Decimal("0.1"), Decimal("0.0001"),
                    1 / 3.82, "exchange_index 0", "LTC-USD", "2026-06-09", 0.00026),
    "doge": PerpSpec("KXDOGEPERP", "doge", "crypto", Decimal("100"), Decimal("0.0001"),
                     1 / 2.74, "exchange_index 0", "DOGE-USD", "2026-06-09", 0.00035),
    "bnb": PerpSpec("KXBNBPERP", "bnb", "crypto", Decimal("0.001"), Decimal("0.0001"),
                    1 / 4.73, "exchange_index 0", "BNB-USD", "2026-08-31", 0.00049),
    "link": PerpSpec("KXLINKPERP", "link", "crypto", Decimal("1"), Decimal("0.0001"),
                     1 / 3.56, "exchange_index 0", "LINK-USD", "2026-06-09", 0.00097),
    "wld": PerpSpec("KXWLDPERP", "wld", "crypto", Decimal("1"), Decimal("0.0001"),
                    1 / 1.69, "exchange_index 0", "WLD-USD", "2026-08-29", 0.00091),
    # contract_size is 1000 SHIB (= 1 kSHIB) and the proxy quotes SHIB — see the
    # kSHIB UNIT NOTE above; underlying_multiplier 1000 is the venue's own field.
    "kshib": PerpSpec("KXKSHIBPERP", "kshib", "crypto", Decimal("1000"), Decimal("0.0001"),
                      1 / 1.99, "exchange_index 0", "SHIB-USD", "2026-06-09", 0.00063,
                      Decimal("1000")),
    "aave": PerpSpec("KXAAVEPERP", "aave", "crypto", Decimal("0.01"), Decimal("0.0001"),
                     1 / 3.24, "exchange_index 0", "AAVE-USD", "2026-08-28", 0.00074),
    # --- listed, margin-able, NOT tradable on 2026-09-15: status "inactive",
    # zero open interest, zero 24h volume, no bid and no ask, no funding row
    # ever. half_spread stays 0.0 because there is no spread to measure.
    "dot": PerpSpec("KXDOTPERP", "dot", "crypto", Decimal("10"), Decimal("0.0001"),
                    1 / 3.43, "exchange_index 0", "DOT-USD", ""),
    "hbar": PerpSpec("KXHBARPERP", "hbar", "crypto", Decimal("100"), Decimal("0.0001"),
                     1 / 2.51, "exchange_index 0", "HBAR-USD", ""),
    "xlm": PerpSpec("KXXLMPERP", "xlm", "crypto", Decimal("10"), Decimal("0.0001"),
                    1 / 2.49, "exchange_index 0", "XLM-USD", ""),
}

# Retained for the earlier write-ups, which quote it: the tickers that were
# outside the research universe when the desk was built. Every one of them now
# has a full spec above, so this is just the leverage record for those rows.
OTHER_LISTED_LEVERAGE = {t: LEVERAGE_AT_1K[t] for t in (
    "KXDOGEPERP", "KXHYPEPERP", "KXLINKPERP", "KXLTCPERP", "KXBCHPERP", "KXZECPERP",
    "KXNEARPERP", "KXSUIPERP", "KXADAPERP", "KXBNBPERP", "KXAAVEPERP", "KXVVVPERP",
    "KXWLDPERP", "KXKSHIBPERP",
    # inactive on 2026-09-14 and still inactive on 2026-09-15
    "KXDOTPERP", "KXHBARPERP", "KXXLMPERP")}

TICKER_TO_ASSET = {s.ticker: a for a, s in SPECS.items()}

# ------------------------------------------------------------------ universes
# RESEARCH_UNIVERSE is FROZEN AT FOUR. Every published number on this desk —
# the first tournament, the ten-family campaign, the one holdout opening — was
# produced on btc/eth/gold/silver. Widening this tuple would silently make old
# and new results incomparable. New work declares its own universe.
RESEARCH_UNIVERSE = ("btc", "eth", "gold", "silver")
EXTENDED_UNIVERSE = RESEARCH_UNIVERSE + ("sol", "xrp")

# Everything Kalshi lists (23 markets, GET /margin/markets 2026-09-15).
LISTED_UNIVERSE = tuple(SPECS)

# TRADABLE_UNIVERSE — the 20 markets with a real two-sided quote on 2026-09-15,
# ordered by 24h notional volume: btc and eth ($560M / $540M a day) down to
# aave ($267k). Membership = LISTED minus dot, hbar and xlm, which are listed
# and margin-able but had status "inactive", $0 open interest, $0 24h volume,
# no bid, no ask and not one funding row in the venue's history. You cannot
# enter or exit them, so nothing may size them, and the reason is liquidity,
# not history: dot and xlm have years of Coinbase data.
TRADABLE_UNIVERSE = (
    "btc", "eth", "xrp", "silver", "gold", "sol", "zec", "near", "hype", "vvv",
    "ada", "sui", "bch", "ltc", "doge", "bnb", "link", "wld", "kshib", "aave",
)

# BREADTH_UNIVERSE — the 14 tradable markets whose price proxy starts on or
# before 2021-09-30, so a cross-sectional backtest beginning 2021-10 can rank
# every one of them from its first day instead of growing its universe mid-run
# (a survivorship-shaped trap). Members, with the proxy's first bar:
#   gold 2000-08-30, silver 2000-08-30 (Yahoo GC=F / SI=F, decades of history),
#   btc 2015-07-20, eth 2016-05-18, ltc 2016-08-17, bch 2017-12-20,
#   xrp 2019-02-26, link 2019-06-27, zec 2020-12-08, aave 2020-12-15,
#   ada 2021-03-18, doge 2021-06-03, sol 2021-06-17, kshib 2021-09-09.
# Excluded though tradable: near (2022-09-01), sui (2023-05-18), vvv
# (2025-01-28), wld (2025-04-30), bnb (2025-10-22), hype (2026-02-05). The last
# two start AFTER the sealed holdout opens on 2025-07-01 and therefore have no
# research history whatsoever. Twelve of the fourteen are crypto, which is what
# makes a cross-sectional test meaningful for the first time: the old four were
# two bets at 0.9 btc-eth correlation.
BREADTH_UNIVERSE = (
    "btc", "eth", "gold", "silver", "ltc", "bch", "xrp", "link", "zec", "aave",
    "ada", "doge", "sol", "kshib",
)
BREADTH_PROXY_CUTOFF = "2021-09-30"


# ------------------------------------------------------------ cost model
@dataclass(frozen=True)
class CostModel:
    """Per-side cost as a fraction of notional: exchange fee + half-spread.

    ``half_spread`` here is the FLAT modelling assumption every published
    result on this desk was produced with. ``side_cost(asset)`` refines it with
    the per-market spread measured on 2026-09-15:

        side_cost(asset) = fee_rate + max(half_spread, SPECS[asset].half_spread)

    The max is what keeps the record comparable. btc, eth, gold and silver all
    quote INSIDE the flat 2.5 bps (0.2 / 0.4 / 0.6 / 1.5 bps measured), so for
    the four researched assets the taker and stress models return exactly the
    per_side they always returned and every tournament and campaign number
    still stands. The thin alts pay what they actually quote — link 9.7 bps,
    near 8.2, zec 7.6, aave 7.4, sui 6.7, kshib 6.3 — which is the whole point:
    a breadth strategy that trades the tail must be charged for the tail.

    Three things stated rather than hidden:
      * Nothing changes for existing callers. ``per_side`` is untouched and
        backtest.py still uses it; a caller opts into per-asset costs by
        passing an asset.
      * An asset with no spec, or a spec whose half_spread is 0.0 because
        nothing quotes (dot, hbar, xlm), falls back to the flat spread.
      * MAKER_T0 sets half_spread to 0.0 by construction — resting at the touch
        pays no spread — so the rule adds the measured spread to it for every
        asset, btc included (5.0 bps → 5.2 bps). That is the rule as specified
        and it only makes the maker bound less flattering; callers that want
        the old maker number keep calling ``per_side``.
    """

    name: str
    fee_rate: float
    half_spread: float

    @property
    def per_side(self) -> float:
        """Flat, asset-agnostic per-side cost. Unchanged, and the published
        results depend on it — do not repoint this at side_cost()."""
        return self.fee_rate + self.half_spread

    def side_cost(self, asset: str | None = None) -> float:
        """Per-side cost for one asset; ``None`` reproduces ``per_side``."""
        if asset is None:
            return self.per_side
        spec = SPECS.get(asset)
        spread = self.half_spread if spec is None else max(self.half_spread, spec.half_spread)
        return self.fee_rate + spread

    def round_trip(self, asset: str | None = None) -> float:
        return 2 * self.side_cost(asset)


# Observed top-of-book spreads 2026-09-14: BTC 5 bps, ETH 4 bps, gold 2 bps,
# silver 3.5 bps, SOL 3 bps, XRP 4 bps. Half of that is 1–2.5 bps; the taker
# model uses 2.5 bps on top of the tier-0 fee so it is not flattered. The
# per-market half-spreads measured on 2026-09-15 live on PerpSpec.half_spread
# and reach a backtest through side_cost(asset), which can only raise this
# floor, never lower it.
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
