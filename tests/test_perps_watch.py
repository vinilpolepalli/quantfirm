"""The weekly watch must report CHANGES, not standing facts.

A watch that re-sends the same finding every week is worse than no watch: the
owner learns to skip the address, and the one week it says something new goes
unread with all the others. So the contract under test is narrow and strict:

  * a first reading INSIDE the deadband is confirmation of what the docs already
    say, and is silent;
  * a first reading OUTSIDE it is news, and is reported exactly once;
  * a sample too short to support a rate is never reported as a rate, and is not
    recorded either, so the real first reading still gets to speak;
  * crossings in both directions are news; drift below the thresholds is not;
  * the headline annualisation averages over EVERY interval, zeros included,
    because a holder sits through the zeros too.

No network: the venue side is not exercised here, only the change logic and the
mark file it is built on.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import perps_watch as W  # noqa: E402


def reading(zero_share, annualised=0.0, intervals=90):
    return {"intervals": intervals, "zero_share": zero_share,
            "median_nonzero": annualised / (3 * 365), "annualised": annualised}


class TestFundingChange(unittest.TestCase):
    def test_first_reading_inside_deadband_is_silent(self):
        # 89% zero is ETH as documented. Saying so is not a finding.
        self.assertIsNone(W.funding_changed(None, reading(0.889, -0.13)))

    def test_first_reading_outside_deadband_is_news(self):
        why = W.funding_changed(None, reading(0.244, 0.178))
        self.assertIsNotNone(why)
        self.assertIn("live", why)

    def test_same_reading_twice_reports_once(self):
        first = reading(0.244, 0.178)
        self.assertIsNotNone(W.funding_changed(None, first))
        self.assertIsNone(W.funding_changed(first, first))

    def test_small_drift_is_not_news(self):
        # the 90-interval window rolls every day; it must not email on that alone
        self.assertIsNone(W.funding_changed(reading(0.244, 0.178), reading(0.30, 0.20)))

    def test_crossing_back_into_the_deadband_is_news(self):
        why = W.funding_changed(reading(0.244, 0.178), reading(0.80, 0.02))
        self.assertIsNotNone(why)
        self.assertIn("QUIET", why)

    def test_big_deadband_move_without_crossing_is_news(self):
        why = W.funding_changed(reading(0.10, 0.18), reading(0.40, 0.11))
        self.assertIsNotNone(why)

    def test_carry_doubling_is_news_even_at_the_same_deadband_share(self):
        why = W.funding_changed(reading(0.244, 0.09), reading(0.244, 0.22))
        self.assertIsNotNone(why)
        self.assertIn("carry", why)


class TestAnnualisation(unittest.TestCase):
    """The headline rate must be what HOLDING costs, not what a charging interval costs.

    On a market inside the deadband most of the time these differ by the reciprocal
    of the live share, which is an order of magnitude on ETH. Reporting the wrong one
    tells the owner that a long ETH book is paid 13% a year when it is paid 1.5%.
    """

    def test_headline_averages_over_the_zeros(self):
        import pandas as pd
        rate = 0.0001
        # nine zeros and one charging interval: holding costs a TENTH of the live rate
        s = pd.Series([0.0] * 9 + [rate],
                      index=pd.date_range("2026-01-01", periods=10, freq="8h", tz="UTC"))
        got = W.summarise_funding(s, n=10)
        self.assertAlmostEqual(got["zero_share"], 0.9)
        self.assertAlmostEqual(got["annualised_when_live"], round(rate * 3 * 365, 4), places=9)
        self.assertAlmostEqual(got["annualised"], round(rate * 3 * 365 / 10, 4), places=9)
        self.assertLess(got["annualised"], got["annualised_when_live"])

    def test_a_market_that_always_charges_makes_the_two_agree(self):
        import pandas as pd
        rate = 0.0001
        s = pd.Series([rate] * 10,
                      index=pd.date_range("2026-01-01", periods=10, freq="8h", tz="UTC"))
        got = W.summarise_funding(s, n=10)
        self.assertAlmostEqual(got["annualised"], got["annualised_when_live"], places=9)

    def test_no_live_intervals_at_all_does_not_divide_by_zero(self):
        import pandas as pd
        s = pd.Series([0.0] * 10,
                      index=pd.date_range("2026-01-01", periods=10, freq="8h", tz="UTC"))
        got = W.summarise_funding(s, n=10)
        self.assertEqual(got["zero_share"], 1.0)
        self.assertEqual(got["annualised"], 0.0)
        self.assertEqual(got["annualised_when_live"], 0.0)

    def test_both_conventions_are_reported(self):
        # a caller that wants the conditional figure must not have to recompute it
        import pandas as pd
        got = W.summarise_funding(
            pd.Series([0.0, 0.0001] * 5,
                      index=pd.date_range("2026-01-01", periods=10, freq="8h", tz="UTC")), n=10)
        self.assertEqual(set(got) >= {"annualised", "annualised_when_live", "zero_share",
                                      "median_nonzero", "intervals"}, True)

    def test_metals_use_one_print_a_day_not_three(self):
        # Gold and silver fund once a weekday. Treating them as crypto 3x/day
        # triples the cost of holding — the error this desk already made once
        # on ETH by annualising the live median.
        import pandas as pd
        rate = 0.0001
        s = pd.Series([0.0] * 9 + [rate],
                      index=pd.date_range("2026-01-01", periods=10, freq="D", tz="UTC"))
        crypto = W.summarise_funding(s, n=10, funding_per_day=3)
        metals = W.summarise_funding(s, n=10, funding_per_day=1)
        self.assertAlmostEqual(crypto["annualised"], round(rate * 3 * 365 / 10, 4), places=9)
        self.assertAlmostEqual(metals["annualised"], round(rate * 1 * 365 / 10, 4), places=9)
        self.assertGreater(crypto["annualised"], metals["annualised"])


class TestThinSample(unittest.TestCase):
    def test_floor_is_ten_days(self):
        # four intervals of metals history is two observations and a slope
        self.assertGreaterEqual(W.MIN_FUNDING_INTERVALS, 30)


class TestMark(unittest.TestCase):
    def test_round_trips_and_survives_a_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            old = W.MARK
            try:
                W.MARK = os.path.join(d, "mark.json")
                self.assertEqual(W.load_mark(), {})          # never written yet
                W.save_mark({"funding": {"btc": reading(0.244, 0.178)}})
                self.assertEqual(W.load_mark()["funding"]["btc"]["zero_share"], 0.244)
                with open(W.MARK, "w") as f:                 # truncated by a killed run
                    f.write("{not json")
                self.assertEqual(W.load_mark(), {})
            finally:
                W.MARK = old


class TestNotableKinds(unittest.TestCase):
    def test_every_notable_kind_is_one_the_checks_can_emit(self):
        import inspect
        src = inspect.getsource(W)
        for kind in ("new_listing", "delisting", "funding_change", "vol_drift", "venue_unreachable"):
            self.assertIn(f'"kind": "{kind}"', src, f"main() filters on {kind} but nothing emits it")

    def test_confirmatory_kinds_are_not_notable(self):
        import inspect
        notable = inspect.getsource(W.main)
        for kind in ("funding_stable", "funding_thin", "tracking", "too_early"):
            self.assertNotIn(f'"{kind}"', notable, f"{kind} is confirmation, not a finding")


if __name__ == "__main__":
    unittest.main()
