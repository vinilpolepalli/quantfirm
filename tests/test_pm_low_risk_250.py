"""Arithmetic behind research/pm_low_risk_250.md. No network."""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from quantfirm.kalshi.fair import kelly_fraction, taker_fee
from pm_low_risk_250 import (APY, BANKROLL, RISK_FRAC, WHELAN_MAKER_MU,
                             WHELAN_MAKER_SD, apy_year, clip,
                             lip_collateral, n_for_mean_ci, volume_cap)


class TestFees(unittest.TestCase):
    def test_100_lots_atm_matches_schedule(self):
        # Kalshi table: 100 contracts at 50¢, M=1 → $1.75
        self.assertAlmostEqual(taker_fee(100, 0.50), 1.75)

    def test_small_clip_rounds_up_hard(self):
        # 1 contract at 50¢ raw = 1.75¢ → cent-ceil 2¢. This is why $5 clips die.
        self.assertAlmostEqual(taker_fee(1, 0.50), 0.02)


class TestClip(unittest.TestCase):
    def test_two_percent_of_250_is_five_dollars(self):
        self.assertAlmostEqual(BANKROLL * RISK_FRAC, 5.0)

    def test_90c_clip_stays_inside_budget(self):
        c = clip(0.90)
        self.assertGreater(c["n"], 0)
        self.assertLessEqual(c["max_loss"], BANKROLL * RISK_FRAC + 1e-9)
        # one more lot would breach
        extra = (c["n"] + 1) * 0.90 + taker_fee(c["n"] + 1, 0.90)
        self.assertGreater(extra, BANKROLL * RISK_FRAC)

    def test_90c_breakeven_is_above_the_price(self):
        c = clip(0.90)
        self.assertGreater(c["breakeven_hit"], 0.90)

    def test_10c_longshot_breakeven_exceeds_price(self):
        c = clip(0.10)
        # Fee drag: a fairly priced 10¢ dog is still -EV as a taker.
        self.assertGreater(c["breakeven_hit"], 0.10)
        self.assertLessEqual(c["max_loss"], BANKROLL * RISK_FRAC + 1e-9)


class TestWhelanMath(unittest.TestCase):
    def test_n_for_95pct_is_hundreds(self):
        n = n_for_mean_ci(WHELAN_MAKER_MU, WHELAN_MAKER_SD, z=1.65)
        self.assertGreaterEqual(n, 400)
        self.assertLess(n, 500)

    def test_quarter_kelly_on_a_dime_edge_is_small(self):
        f = 0.25 * kelly_fraction(0.60, 0.50)
        self.assertAlmostEqual(f, 0.05)
        self.assertAlmostEqual(f * BANKROLL, 12.50)


class TestLipAndYield(unittest.TestCase):
    def test_1000_lots_at_1c_both_sides_fits(self):
        cap = lip_collateral(1000, 0.01, 0.01)
        self.assertAlmostEqual(cap, 20.0)
        self.assertLess(cap, BANKROLL)

    def test_1000_lots_atm_does_not_fit(self):
        cap = lip_collateral(1000, 0.50, 0.50)
        self.assertAlmostEqual(cap, 1000.0)
        self.assertGreater(cap, BANKROLL)

    def test_apy_is_eight_dollars_a_year(self):
        self.assertAlmostEqual(apy_year(), BANKROLL * APY)
        self.assertAlmostEqual(apy_year(), 8.125)

    def test_volume_cap_cannot_pay_the_taker_fee(self):
        n = int(BANKROLL / 0.50)
        self.assertLess(volume_cap(n), taker_fee(n, 0.50))


if __name__ == "__main__":
    unittest.main()
