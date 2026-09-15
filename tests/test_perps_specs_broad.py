"""The broad Kalshi perps universe: specs, measured spreads, cost rule, universes.

Everything here is checked against the venue readings of 2026-09-15 that are
recorded in the task brief and in ``quantfirm/perps/specs.py``. NO NETWORK: the
expected numbers are written out below so the test is an independent copy of
the measurement, not a re-derivation from the module under test.
"""
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.perps import specs as SP  # noqa: E402
from quantfirm.perps.specs import (BREADTH_PROXY_CUTOFF, BREADTH_UNIVERSE,  # noqa: E402
                                   EXTENDED_UNIVERSE, LEVERAGE_AT_1K, LISTED_UNIVERSE,
                                   MAKER_T0, PROXY_FIRST_BAR, RESEARCH_UNIVERSE, SPECS,
                                   STRESS, TAKER_T0, TICKER_TO_ASSET, TRADABLE_UNIVERSE)

# GET /margin/markets, 2026-09-15: ticker → (asset, contract_size, leverage@$1k,
# half-spread in BPS, quotes two-sided?). This is the whole listed board.
VENUE = {
    "KXBTCPERP":    ("btc",    "0.0001", 6.05,  0.2,  True),
    "KXETHPERP":    ("eth",    "0.001",  4.66,  0.4,  True),
    "KXXRPPERP":    ("xrp",    "1",      2.79,  1.8,  True),
    "KXSILVERPERP": ("silver", "0.1",    7.79,  1.5,  True),
    "KXGOLDPERP":   ("gold",   "0.001",  15.26, 0.6,  True),
    "KXSOLPERP":    ("sol",    "0.1",    3.02,  1.8,  True),
    "KXZECPERP":    ("zec",    "0.01",   2.47,  7.6,  True),
    "KXNEARPERP":   ("near",   "1",      3.08,  8.2,  True),
    "KXHYPEPERP":   ("hype",   "0.1",    2.24,  3.6,  True),
    "KXVVVPERP":    ("vvv",    "0.1",    1.75,  6.6,  True),
    "KXADAPERP":    ("ada",    "1",      3.05,  4.8,  True),
    "KXSUIPERP":    ("sui",    "10",     2.50,  6.7,  True),
    "KXBCHPERP":    ("bch",    "0.01",   2.92,  3.8,  True),
    "KXLTCPERP":    ("ltc",    "0.1",    3.82,  2.6,  True),
    "KXDOGEPERP":   ("doge",   "100",    2.74,  3.5,  True),
    "KXBNBPERP":    ("bnb",    "0.001",  4.73,  4.9,  True),
    "KXLINKPERP":   ("link",   "1",      3.56,  9.7,  True),
    "KXWLDPERP":    ("wld",    "1",      1.69,  9.1,  True),
    "KXKSHIBPERP":  ("kshib",  "1000",   1.99,  6.3,  True),
    "KXAAVEPERP":   ("aave",   "0.01",   3.24,  7.4,  True),
    "KXDOTPERP":    ("dot",    "10",     3.43,  0.0,  False),
    "KXHBARPERP":   ("hbar",   "100",    2.51,  0.0,  False),
    "KXXLMPERP":    ("xlm",    "10",     2.49,  0.0,  False),
}

# The six specs that existed before the universe was widened, exactly as
# published. If any of these change, every tournament and campaign number on
# this desk becomes incomparable — that is what the assertion is for.
FROZEN_SIX = {
    "btc":    ("KXBTCPERP",    "crypto", "0.0001", 1 / 6.05,  "BTC-USD", "2026-06-03"),
    "eth":    ("KXETHPERP",    "crypto", "0.001",  1 / 4.66,  "ETH-USD", "2026-06-03"),
    "sol":    ("KXSOLPERP",    "crypto", "0.1",    1 / 3.02,  "SOL-USD", "2026-06-03"),
    "xrp":    ("KXXRPPERP",    "crypto", "1",      1 / 2.79,  "XRP-USD", "2026-06-03"),
    "gold":   ("KXGOLDPERP",   "metals", "0.001",  1 / 15.26, "GC=F",    "2026-09-11"),
    "silver": ("KXSILVERPERP", "metals", "0.1",    1 / 7.79,  "SI=F",    "2026-09-11"),
}

NO_QUOTE = ("dot", "hbar", "xlm")


class TestBroadSpecs(unittest.TestCase):
    def test_every_listed_perp_has_a_spec(self):
        self.assertEqual(len(SPECS), 23)
        self.assertEqual(sorted(s.ticker for s in SPECS.values()), sorted(VENUE))
        for ticker, (asset, csize, _lev, _hs, _q) in VENUE.items():
            self.assertIn(asset, SPECS, ticker)
            spec = SPECS[asset]
            self.assertEqual(spec.ticker, ticker)
            self.assertEqual(spec.asset, asset)
            self.assertEqual(spec.contract_size, Decimal(csize))
            self.assertEqual(spec.tick, Decimal("0.0001"))   # every market, no exceptions
            self.assertEqual(TICKER_TO_ASSET[ticker], asset)
        self.assertEqual(sorted(a for a, s in SPECS.items() if s.asset_class == "metals"),
                         ["gold", "silver"])
        self.assertTrue(all(s.asset_class == "crypto" for a, s in SPECS.items()
                            if a not in ("gold", "silver")))

    def test_maint_rate_is_one_over_leverage(self):
        """maint = 1/leverage@$1k for all 23, including the six that had one."""
        self.assertEqual(sorted(LEVERAGE_AT_1K), sorted(VENUE))
        for ticker, (asset, _c, lev, _hs, _q) in VENUE.items():
            with self.subTest(ticker=ticker):
                self.assertEqual(LEVERAGE_AT_1K[ticker], lev)
                self.assertAlmostEqual(SPECS[asset].maint_rate, 1 / lev, places=3)
                # initial = 1.3 × maint is the venue rule on every market
                self.assertAlmostEqual(SPECS[asset].initial_rate, 1.3 / lev, places=3)
        # the six original rows to four decimals, the tolerance the rule was
        # validated at when the desk was built
        for asset, (_t, _cls, _c, maint, _p, _ls) in FROZEN_SIX.items():
            self.assertAlmostEqual(SPECS[asset].maint_rate, maint, places=4)

    def test_original_six_are_byte_for_byte_unchanged(self):
        for asset, (ticker, cls, csize, maint, proxy, live) in FROZEN_SIX.items():
            spec = SPECS[asset]
            with self.subTest(asset=asset):
                self.assertEqual(spec.ticker, ticker)
                self.assertEqual(spec.asset_class, cls)
                self.assertEqual(spec.contract_size, Decimal(csize))
                self.assertEqual(spec.maint_rate, maint)      # exact, not almost
                self.assertEqual(spec.proxy, proxy)
                self.assertEqual(spec.live_since, live)
                self.assertEqual(spec.tick, Decimal("0.0001"))

    def test_measured_half_spreads(self):
        for ticker, (asset, _c, _lev, hs_bps, quotes) in VENUE.items():
            spec = SPECS[asset]
            with self.subTest(ticker=ticker):
                self.assertAlmostEqual(spec.half_spread, hs_bps / 1e4, places=9)
                self.assertAlmostEqual(spec.half_spread_bps, hs_bps, places=6)
                # a quoting market has a measured spread; a dead one has none
                self.assertEqual(spec.half_spread > 0.0, quotes)
        # the four researched assets all quote inside the flat 2.5 bps model
        for a in RESEARCH_UNIVERSE:
            self.assertLess(SPECS[a].half_spread, TAKER_T0.half_spread)
        # the tail does not
        for a in ("link", "near", "zec", "aave", "sui", "kshib", "wld", "vvv"):
            self.assertGreater(SPECS[a].half_spread, TAKER_T0.half_spread)

    def test_live_since_matches_funding_history(self):
        """First funding row per ticker, read 2026-09-15; "" = never funded."""
        for a in NO_QUOTE:
            self.assertEqual(SPECS[a].live_since, "")
        for a in TRADABLE_UNIVERSE:
            self.assertTrue(SPECS[a].live_since.startswith("2026-"), a)

    def test_proxies_are_distinct_and_dated(self):
        proxies = [s.proxy for s in SPECS.values()]
        self.assertEqual(len(proxies), len(set(proxies)))
        self.assertEqual(SPECS["gold"].proxy, "GC=F")
        self.assertEqual(SPECS["silver"].proxy, "SI=F")
        for a, s in SPECS.items():
            if a not in ("gold", "silver"):
                self.assertTrue(s.proxy.endswith("-USD"), a)
            self.assertIn(a, PROXY_FIRST_BAR)
            self.assertRegex(PROXY_FIRST_BAR[a], r"^\d{4}-\d{2}-\d{2}$")


class TestKshibUnits(unittest.TestCase):
    """KXKSHIBPERP is the one contract whose unit is not the proxy's unit."""

    def test_contract_is_a_thousand_shib_priced_off_shib_usd(self):
        k = SPECS["kshib"]
        self.assertEqual(k.ticker, "KXKSHIBPERP")
        self.assertEqual(k.contract_size, Decimal("1000"))   # 1000 kSHIB per contract
        self.assertEqual(k.proxy, "SHIB-USD")                # priced per ONE shib
        self.assertEqual(k.underlying_multiplier, Decimal("1000"))   # 1 kSHIB = 1000 SHIB
        # so one contract is 1,000,000 SHIB, which at the 2026-09-15 SHIB price
        # of $0.00000521 reproduces the venue's own quote of 5.2117.
        self.assertEqual(k.proxy_units_per_contract, 1_000_000.0)
        self.assertAlmostEqual(k.notional_per_contract(0.00000521), 5.21, places=4)

    def test_every_other_market_has_multiplier_one(self):
        for a, s in SPECS.items():
            self.assertEqual(s.underlying_multiplier,
                             Decimal("1000") if a == "kshib" else Decimal(1), a)

    def test_naive_per_coin_notional_is_a_thousand_times_wrong(self):
        """The trap: treating the venue's per-contract mark as a coin price."""
        k = SPECS["kshib"]
        shib = 0.00000521
        self.assertAlmostEqual(k.notional_per_contract(shib)
                               / (float(k.contract_size) * shib), 1000.0, places=6)
        # and one contract is worth a normal few dollars, like every other market
        self.assertTrue(1.0 < k.notional_per_contract(shib) < 20.0)


class TestPerAssetCost(unittest.TestCase):
    def test_scalar_per_side_is_untouched(self):
        self.assertAlmostEqual(TAKER_T0.per_side, 0.0012 + 0.00025)
        self.assertAlmostEqual(MAKER_T0.per_side, 0.0005)
        self.assertAlmostEqual(STRESS.per_side, 0.0018 + 0.0005)
        for c in (TAKER_T0, MAKER_T0, STRESS):
            self.assertEqual(c.side_cost(), c.per_side)        # no asset → old number
            self.assertEqual(c.round_trip(), 2 * c.per_side)

    def test_researched_four_keep_exactly_the_old_cost(self):
        """btc/eth/gold/silver quote inside 2.5 bps, so every published
        tournament and campaign number stays comparable."""
        for a in RESEARCH_UNIVERSE:
            with self.subTest(asset=a):
                self.assertEqual(TAKER_T0.side_cost(a), TAKER_T0.per_side)
                self.assertEqual(STRESS.side_cost(a), STRESS.per_side)
                self.assertEqual(TAKER_T0.round_trip(a), TAKER_T0.round_trip())
        # sol and xrp too, at 1.8 bps measured
        for a in ("sol", "xrp"):
            self.assertEqual(TAKER_T0.side_cost(a), TAKER_T0.per_side)

    def test_thin_alts_pay_their_measured_spread(self):
        # link: 12 bps fee + 9.7 bps measured half-spread = 21.7 bps a side
        self.assertAlmostEqual(TAKER_T0.side_cost("link"), 0.0012 + 0.00097, places=12)
        self.assertGreater(TAKER_T0.side_cost("link"), TAKER_T0.per_side)
        self.assertAlmostEqual(TAKER_T0.round_trip("link"), 2 * (0.0012 + 0.00097), places=12)
        self.assertAlmostEqual(STRESS.side_cost("link"), 0.0018 + 0.00097, places=12)
        for a in ("near", "zec", "aave", "wld", "sui", "vvv", "kshib", "ada", "bnb",
                  "bch", "doge", "hype", "ltc"):
            with self.subTest(asset=a):
                self.assertAlmostEqual(TAKER_T0.side_cost(a),
                                       0.0012 + max(0.00025, SPECS[a].half_spread), places=12)

    def test_taker_rule_is_fee_plus_max_of_the_two_spreads(self):
        for c in (TAKER_T0, STRESS):
            for a in LISTED_UNIVERSE:
                with self.subTest(cost=c.name, asset=a):
                    self.assertAlmostEqual(
                        c.side_cost(a), c.fee_rate + max(c.half_spread, SPECS[a].half_spread),
                        places=12)
                    self.assertGreaterEqual(c.side_cost(a), c.per_side)   # never cheaper

    def test_a_maker_model_pays_no_spread_on_any_asset(self):
        """A resting order crosses no spread, on BTC or on the thinnest alt.

        Composing MAKER_T0 (flat half-spread 0.0) with a measured spread would
        charge a patient order the price of an impatient one, and would move a
        cost scenario that seven published family reports quote.
        """
        for a in LISTED_UNIVERSE:
            with self.subTest(asset=a):
                self.assertAlmostEqual(MAKER_T0.side_cost(a), MAKER_T0.fee_rate, places=12)
                self.assertAlmostEqual(MAKER_T0.side_cost(a), MAKER_T0.per_side, places=12)

    def test_unknown_or_unmeasured_assets_fall_back_to_the_flat_spread(self):
        self.assertEqual(TAKER_T0.side_cost("no_such_asset"), TAKER_T0.per_side)
        for a in NO_QUOTE:                      # spec exists, half_spread 0.0
            self.assertEqual(TAKER_T0.side_cost(a), TAKER_T0.per_side)


class TestUniverses(unittest.TestCase):
    def test_research_universe_is_frozen(self):
        self.assertEqual(RESEARCH_UNIVERSE, ("btc", "eth", "gold", "silver"))
        self.assertEqual(EXTENDED_UNIVERSE, ("btc", "eth", "gold", "silver", "sol", "xrp"))

    def test_membership_and_nesting(self):
        """Nothing is disjoint from anything: research ⊆ breadth ⊆ tradable ⊆ listed."""
        self.assertEqual(len(LISTED_UNIVERSE), 23)
        self.assertEqual(len(TRADABLE_UNIVERSE), 20)
        self.assertEqual(len(BREADTH_UNIVERSE), 14)
        for u in (RESEARCH_UNIVERSE, EXTENDED_UNIVERSE, TRADABLE_UNIVERSE,
                  BREADTH_UNIVERSE, LISTED_UNIVERSE):
            self.assertEqual(len(u), len(set(u)))             # no duplicates
            for a in u:
                self.assertIn(a, SPECS)                       # every member has a spec
        self.assertLessEqual(set(RESEARCH_UNIVERSE), set(BREADTH_UNIVERSE))
        self.assertLessEqual(set(EXTENDED_UNIVERSE), set(TRADABLE_UNIVERSE))
        self.assertLessEqual(set(BREADTH_UNIVERSE), set(TRADABLE_UNIVERSE))
        self.assertLessEqual(set(TRADABLE_UNIVERSE), set(LISTED_UNIVERSE))
        self.assertEqual(set(LISTED_UNIVERSE), set(SPECS))

    def test_tradable_excludes_exactly_the_dead_books(self):
        self.assertEqual(sorted(set(LISTED_UNIVERSE) - set(TRADABLE_UNIVERSE)),
                         sorted(NO_QUOTE))
        for a in NO_QUOTE:
            self.assertEqual(SPECS[a].half_spread, 0.0)
            self.assertEqual(SPECS[a].live_since, "")
        # exclusion is about liquidity, not history: dot and xlm have years of it
        for a in ("dot", "xlm"):
            self.assertLess(PROXY_FIRST_BAR[a], BREADTH_PROXY_CUTOFF)

    def test_breadth_is_exactly_the_tradable_assets_with_history(self):
        derived = tuple(a for a in TRADABLE_UNIVERSE
                        if PROXY_FIRST_BAR[a] <= BREADTH_PROXY_CUTOFF)
        self.assertEqual(sorted(derived), sorted(BREADTH_UNIVERSE))
        self.assertEqual(BREADTH_PROXY_CUTOFF, "2021-09-30")
        self.assertEqual(sorted(set(TRADABLE_UNIVERSE) - set(BREADTH_UNIVERSE)),
                         ["bnb", "hype", "near", "sui", "vvv", "wld"])
        # kshib is the last one in, at 2021-09-09
        self.assertIn("kshib", BREADTH_UNIVERSE)
        self.assertEqual(max(PROXY_FIRST_BAR[a] for a in BREADTH_UNIVERSE), "2021-09-09")
        # bnb and hype begin inside the sealed holdout, so they have no research
        # history at all — never silently usable in a DEV-window backtest
        for a in ("bnb", "hype"):
            self.assertGreater(PROXY_FIRST_BAR[a], "2025-07-01")
        # breadth is 12 crypto + 2 metals: the point of widening the board
        self.assertEqual(sum(SPECS[a].asset_class == "crypto" for a in BREADTH_UNIVERSE), 12)


class TestNoNetwork(unittest.TestCase):
    def test_specs_module_never_reaches_the_network(self):
        with open(SP.__file__) as f:
            src = f.read()
        for forbidden in ("import requests", "urllib", "socket", "http.client", "httpx"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
