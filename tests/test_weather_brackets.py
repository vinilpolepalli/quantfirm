"""Offline tests for weather-bracket math and cancel classification."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.kalshi.client import classify_cancel
from quantfirm.kalshi.fair import taker_fee
from quantfirm.kalshi.weather_brackets import (
    bracket_p_yes, mu_sigma_from_quantiles, overround, parse_weather_ticker,
    phi, threshold_p_yes,
)


class TestWeatherBrackets(unittest.TestCase):
    def test_phi_matches_fair_norm(self):
        from quantfirm.kalshi.fair import norm_cdf
        self.assertAlmostEqual(phi(0), 0.5)
        self.assertAlmostEqual(phi(1.96), 0.975, places=3)
        self.assertAlmostEqual(phi(0.4), norm_cdf(0.4))

    def test_inclusive_two_degree_bracket(self):
        # N(74.5, 0.01) should put ~all mass on {74, 75} = B74.5
        p = bracket_p_yes(74, 75, 74.5, 0.01)
        self.assertGreater(p, 0.99)
        # A 1°F half-open reading of the same ticker is the phantom bug.
        half_open = phi((74.5 - 74.5) / 0.01) - phi((74.0 - 74.5) / 0.01)
        self.assertLess(half_open, 0.6)

    def test_mass_splits_across_neighbors(self):
        mu, sigma = 74.0, 2.5
        brackets = [(70, 71), (72, 73), (74, 75), (76, 77), (78, 79)]
        ps = [bracket_p_yes(lo, hi, mu, sigma) for lo, hi in brackets]
        self.assertGreater(ps[2], ps[0])
        self.assertGreater(ps[2], ps[4])
        self.assertLess(overround(ps), 1.0)  # tails omitted

    def test_threshold_requires_api_kind(self):
        with self.assertRaises(ValueError):
            threshold_p_yes(74, 74.0, 2.5, kind="")
        g = threshold_p_yes(74, 80.0, 1.0, kind="greater")
        less = threshold_p_yes(74, 80.0, 1.0, kind="less")
        self.assertGreater(g, 0.9)
        self.assertLess(less, 0.1)

    def test_quantiles_floor(self):
        mu, sigma = mu_sigma_from_quantiles(74.0, 74.0, 74.0)
        self.assertEqual(mu, 74.0)
        self.assertGreaterEqual(sigma, 0.5)

    def test_parse_ticker(self):
        b = parse_weather_ticker("KXHIGHNY-26SEP11-B79.5")
        self.assertEqual(b["kind"], "bracket")
        self.assertEqual(b["floor"], 79)
        self.assertEqual(b["cap"], 80)
        t = parse_weather_ticker("KXHIGHNY-26SEP10-T85")
        self.assertEqual(t["kind"], "threshold")
        self.assertEqual(t["strike"], 85.0)
        self.assertEqual(
            parse_weather_ticker("KXHIGHNY-26SEP11")["kind"], "unknown")


class TestFeeAndCancelHygiene(unittest.TestCase):
    def test_taker_fee_matches_published_ceil(self):
        # agiprolabs sizing.py: ceil(0.07 * C * p * (1-p) * 100) / 100
        for p, n in ((0.01, 1), (0.10, 5), (0.50, 10), (0.88, 20)):
            theirs = math.ceil(0.07 * n * p * (1.0 - p) * 100.0) / 100.0
            self.assertAlmostEqual(taker_fee(n, p), theirs, places=2)

    def test_classify_cancel(self):
        self.assertEqual(classify_cancel(200), "cancelled")
        self.assertEqual(classify_cancel(204), "cancelled")
        self.assertEqual(classify_cancel(404), "already_gone")
        self.assertEqual(classify_cancel(409), "already_gone")
        self.assertEqual(classify_cancel(429), "failed")
        self.assertEqual(classify_cancel(500), "failed")

    def test_cancel_checked_classifies_404(self):
        from unittest import mock
        from quantfirm.kalshi.client import KalshiApiError, KalshiClient
        c = KalshiClient(env="prod")
        with mock.patch.object(c, "cancel_order",
                               side_effect=KalshiApiError(404, "gone")):
            out = c.cancel_order_checked("ord_1")
        self.assertEqual(out["outcome"], "already_gone")
        self.assertEqual(out["status"], 404)


class TestOssEvalOffline(unittest.TestCase):
    def test_replay_matches_recorded_ensemble_pnl(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts"))
        import kalshi_oss_skills_eval as ev
        h = ev.replay_hist()
        self.assertEqual(h["n_events"], 12)
        self.assertEqual(h["modal_hits"], 2)
        self.assertAlmostEqual(h["ensemble_take"]["pnl"], -12.29, places=2)
        self.assertGreaterEqual(h["flb_taker_from_recorded_quotes"]["n"], 1)

    def test_fade_longshot_hit_loses(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts"))
        import kalshi_oss_skills_eval as ev
        # 10¢ YES that wins: taker bought NO at 91¢ and is wiped.
        tk = ev.fade_taker(0.10, 0.09, won_yes=True, count=1)
        self.assertLess(tk["pnl"], 0)
        mk = ev.fade_maker_upper(0.10, won_yes=True, count=1)
        self.assertAlmostEqual(mk["pnl"], -0.90)
        # 10¢ YES that loses: maker keeps the dime.
        mk2 = ev.fade_maker_upper(0.10, won_yes=False, count=1)
        self.assertAlmostEqual(mk2["pnl"], 0.10)


if __name__ == "__main__":
    unittest.main()
