"""Ladder / nowcast math. No network."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.kalshi.fair import taker_fee
from quantfirm.kalshi.ladder import (
    LadderLeg, ensemble_to_brackets, exclusive_dutch, exclusive_mid_sum,
    fee_aware_edge, nested_monotone, nowcast_to_nested, parse_strikes,
    takeable_edge,
)
from quantfirm.kalshi.nowcast import mom_from_index, parse_fred_csv, seasonal_claims_expect, event_date_from_ticker
from quantfirm.kalshi.universe import (CRYPTO_LIVE, PAPER_ASSETS, PAPER_STRATEGY,
                                       SERIES_CRYPTO_EXTRA)


def _leg(tkr, **kw):
    return LadderLeg(ticker=tkr, **kw)


class TestExclusiveDutch(unittest.TestCase):
    def test_buy_all_yes_positive_after_fees(self):
        legs = [
            _leg("A", floor=0, cap=1, yes_ask=0.20, yes_ask_size=10,
                 yes_bid=0.18, yes_bid_size=10),
            _leg("B", floor=1, cap=2, yes_ask=0.30, yes_ask_size=8,
                 yes_bid=0.28, yes_bid_size=8),
            _leg("C", floor=2, cap=None, yes_ask=0.40, yes_ask_size=5,
                 yes_bid=0.38, yes_bid_size=5),
        ]
        d = exclusive_dutch(legs)
        self.assertTrue(d["buy_complete"])
        self.assertEqual(d["buy_count"], 5)
        self.assertAlmostEqual(d["sum_ask"], 0.90)
        fees = sum(taker_fee(5, p) for p in (0.20, 0.30, 0.40))
        self.assertAlmostEqual(d["buy_fees"], fees)
        self.assertGreater(d["buy_edge"], 0)
        self.assertTrue(d["tradeable"])

    def test_missing_wing_is_not_an_arb(self):
        legs = [
            _leg("A", yes_ask=0.20, yes_ask_size=10, yes_bid=0.18, yes_bid_size=10),
            _leg("B", yes_ask=0.30, yes_ask_size=8, yes_bid=0.28, yes_bid_size=8),
            _leg("C", yes_ask=None, yes_ask_size=0, yes_bid=None, yes_bid_size=0),
        ]
        d = exclusive_dutch(legs)
        self.assertFalse(d["buy_complete"])
        self.assertFalse(d["tradeable"])
        self.assertEqual(d["buy_reason"], "missing_ask")

    def test_one_cent_empty_wing_is_not_an_arb(self):
        legs = [
            _leg("A", yes_ask=0.49, yes_ask_size=20, yes_bid=0.47, yes_bid_size=20),
            _leg("B", yes_ask=0.49, yes_ask_size=20, yes_bid=0.47, yes_bid_size=20),
            _leg("C", yes_ask=0.01, yes_ask_size=0, yes_bid=0.00, yes_bid_size=0),
        ]
        d = exclusive_dutch(legs)
        self.assertFalse(d["buy_complete"])
        self.assertEqual(d["buy_reason"], "no_ask_depth")

    def test_sell_all_yes_when_bids_sum_over_one(self):
        legs = [
            _leg("A", yes_ask=0.55, yes_ask_size=4, yes_bid=0.50, yes_bid_size=4),
            _leg("B", yes_ask=0.45, yes_ask_size=4, yes_bid=0.40, yes_bid_size=4),
            _leg("C", yes_ask=0.25, yes_ask_size=4, yes_bid=0.20, yes_bid_size=4),
        ]
        d = exclusive_dutch(legs)
        self.assertTrue(d["sell_complete"])
        self.assertAlmostEqual(d["sum_bid"], 1.10)
        self.assertGreater(d["sell_edge"], 0)

    def test_mid_sum_is_diagnostic(self):
        legs = [
            _leg("A", yes_bid=0.2, yes_ask=0.3),
            _leg("B", yes_bid=0.2, yes_ask=0.3),
        ]
        s = exclusive_mid_sum(legs)
        self.assertAlmostEqual(s["mid_sum"], 0.5)
        self.assertEqual(s["n_missing_mid"], 0)


class TestNestedMonotone(unittest.TestCase):
    def test_locked_inversion(self):
        # P(>0.2) ask 0.40, P(>0.4) bid 0.50 — inverted and locked.
        legs = [
            _leg("T20", threshold=0.2, yes_bid=0.38, yes_ask=0.40,
                 yes_bid_size=10, yes_ask_size=10),
            _leg("T40", threshold=0.4, yes_bid=0.50, yes_ask=0.52,
                 yes_bid_size=10, yes_ask_size=10),
        ]
        d = nested_monotone(legs)
        self.assertEqual(d["n_mid_inversions"], 1)
        self.assertTrue(d["tradeable"])
        self.assertGreater(d["locked"][0]["edge_1"], 0)
        self.assertEqual(d["locked"][0]["count"], 10)

    def test_monotone_book_has_no_lock(self):
        legs = [
            _leg("T20", threshold=0.2, yes_bid=0.60, yes_ask=0.62,
                 yes_bid_size=10, yes_ask_size=10),
            _leg("T40", threshold=0.4, yes_bid=0.40, yes_ask=0.42,
                 yes_bid_size=10, yes_ask_size=10),
        ]
        d = nested_monotone(legs)
        self.assertEqual(d["n_mid_inversions"], 0)
        self.assertFalse(d["tradeable"])


class TestEnsembleBrackets(unittest.TestCase):
    def test_histogram(self):
        legs = [
            _leg("lo", floor=None, cap=70, strike_type="less"),
            _leg("mid", floor=70, cap=75, strike_type="between"),
            _leg("hi", floor=75, cap=None, strike_type="greater"),
        ]
        d = ensemble_to_brackets([68, 70, 74, 75, 80], legs)
        self.assertEqual(d["n_members"], 5)
        self.assertEqual(d["counts"]["lo"], 1)   # 68
        self.assertEqual(d["counts"]["mid"], 3)  # 70, 74, 75 inclusive
        self.assertEqual(d["counts"]["hi"], 1)   # 80
        self.assertEqual(d["unmapped"], 0)

    def test_weather_inclusive_between(self):
        legs = [
            _leg("lo", floor=None, cap=75, strike_type="less"),
            _leg("mid", floor=75, cap=76, strike_type="between"),
            _leg("hi", floor=76, cap=None, strike_type="greater"),
        ]
        d = ensemble_to_brackets([74, 75, 76, 77], legs)
        self.assertEqual(d["counts"]["lo"], 1)
        self.assertEqual(d["counts"]["mid"], 2)
        self.assertEqual(d["counts"]["hi"], 1)
        self.assertEqual(d["unmapped"], 0)

    def test_round_to_integer_fills_gaps(self):
        legs = [
            _leg("a", floor=80, cap=81, strike_type="between"),
            _leg("b", floor=82, cap=83, strike_type="between"),
        ]
        raw = ensemble_to_brackets([81.4, 81.6], legs)
        self.assertEqual(raw["unmapped"], 2)  # 81.4 and 81.6 sit in the 81–82 hole
        rnd = ensemble_to_brackets([81.4, 81.6], legs, round_to=1.0)
        self.assertEqual(rnd["unmapped"], 0)
        self.assertEqual(rnd["counts"]["a"], 1)
        self.assertEqual(rnd["counts"]["b"], 1)

    def test_nowcast_step_and_band(self):
        legs = [_leg("T03", threshold=0.3), _leg("T04", threshold=0.4)]
        step = nowcast_to_nested(0.35, legs, sigma=None)
        self.assertEqual(step["probs"]["T03"], 1.0)
        self.assertEqual(step["probs"]["T04"], 0.0)
        band = nowcast_to_nested(0.35, legs, sigma=0.05)
        self.assertGreater(band["probs"]["T03"], 0.5)
        self.assertLess(band["probs"]["T04"], 0.5)

    def test_fee_aware_edge_prefers_yes_when_cheap(self):
        e = fee_aware_edge(0.80, yes_ask=0.50, yes_bid=0.48, count=10)
        self.assertEqual(e["side"], "yes")
        self.assertGreater(e["yes_edge"], 0)

    def test_takeable_edge_skips_one_cent_leftover(self):
        # Ensemble p=0 on a dead tail still "beats" a 1¢ ask. That is not a take.
        junk = takeable_edge(0.0, yes_ask=0.01, yes_bid=0.0, count=5)
        self.assertIsNone(junk["side"])
        real = takeable_edge(0.55, yes_ask=0.28, yes_bid=0.26, count=5)
        self.assertEqual(real["side"], "yes")

    def test_parse_strikes_ticker_threshold(self):
        floor, cap, thresh, st = parse_strikes({
            "ticker": "KXCPICORE-26SEP-T0.3",
            "floor_strike": 0.3, "cap_strike": None,
            "strike_type": "greater",
        })
        self.assertAlmostEqual(thresh, 0.3)
        self.assertEqual(st, "greater")
        self.assertIsNone(cap)


class TestNowcastHelpers(unittest.TestCase):
    def test_mom(self):
        self.assertAlmostEqual(mom_from_index(100.0, 100.3), 0.3, places=6)

    def test_fred_and_seasonal(self):
        text = "DATE,ICSA\n2024-09-07,220000\n2025-09-06,230000\n2026-09-05,240000\n"
        rows = parse_fred_csv(text)
        self.assertEqual(len(rows), 3)
        # pad a few more weeks so the helper has length
        hist = [(f"2026-0{i}-01", 200000.0 + i) for i in range(1, 9)]
        hist.append(("2026-09-05", 240000.0))
        s = seasonal_claims_expect(hist)
        self.assertIsNotNone(s)
        self.assertEqual(s["last"], 240000.0)

    def test_weather_event_date_from_ticker_not_close(self):
        self.assertEqual(event_date_from_ticker("KXHIGHNY-26SEP11"), "2026-09-11")
        self.assertEqual(event_date_from_ticker("KXHIGHCHI-26AUG31"), "2026-08-31")

    def test_extra_crypto_not_live(self):
        from quantfirm.kalshi.universe import CRYPTO_PAPER, CRYPTO_OVERLAY
        self.assertEqual(PAPER_STRATEGY, "desk_book")
        self.assertEqual(CRYPTO_LIVE, ("btc", "eth"))
        self.assertNotIn("sol", PAPER_ASSETS)
        self.assertNotIn("doge", PAPER_ASSETS)
        self.assertNotIn("hype", PAPER_ASSETS)
        self.assertIn("KXSOL15M", SERIES_CRYPTO_EXTRA)
        self.assertEqual(CRYPTO_PAPER, ("doge", "xrp", "near"))
        self.assertIn("doge", CRYPTO_OVERLAY)
        self.assertIn("near", CRYPTO_OVERLAY)
        self.assertIn("sol", CRYPTO_OVERLAY)
        self.assertNotIn("near", PAPER_ASSETS)


if __name__ == "__main__":
    unittest.main()
